"""
Stripe Auth Single Card Checker
===============================
Handles /au command for Stripe authentication checks.

Uses ONLY the external API: https://dclub.site/apis/stripe/auth/st7.php
All checks are done via this API with site rotation on errors.
"""

import re
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode, ChatType

from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.gc.credit import has_credits, deduct_credit

# Import ONLY the external API functions - no other checking logic is used
from BOT.Auth.StripeAuth.api import check_stripe_auth_with_retry, determine_status

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None


def extract_card(text: str):
    """Extract card details from text in format cc|mm|yy|cvv."""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


def format_response(fullcc: str, result: dict, user_info: dict, time_taken: float, retry_count: int = 0) -> str:
    """Format the Stripe Auth response in professional style with accurate status display."""
    parts = fullcc.split("|")
    cc = parts[0] if len(parts) > 0 else "Unknown"
    
    response = result.get("response", "UNKNOWN")
    message = result.get("message", "Unknown")
    site = result.get("site", "Unknown")
    
    # Use the pre-computed status if available, otherwise determine
    status_text = result.get("status_text")
    header = result.get("header")
    is_live = result.get("success", False)
    
    if not status_text or not header:
        status_text, header, is_live = determine_status(result)
    
    # Clean up response for display
    response_display = response.replace("_", " ").title() if response else "Unknown"
    message_display = message[:100] if message else "Unknown"
    
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
    
    # Build additional info lines
    extra_lines = []
    if retry_count > 0:
        extra_lines.append(f"<b>[•] Retries:</b> <code>{retry_count}</code>")
    if site and site != "Unknown":
        # Show site in a shortened format
        site_display = site[:30] + "..." if len(site) > 30 else site
        extra_lines.append(f"<b>[•] Site:</b> <code>{site_display}</code>")
    
    extra_section = "\n" + "\n".join(extra_lines) if extra_lines else ""
    
    return f"""<b>[#StripeAuth] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>Stripe Auth</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{response_display}</code>
<b>[•] Message:</b> <code>{message_display}</code>{extra_section}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_number}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user_info['profile']} [<code>{user_info['plan']} {user_info['badge']}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code>"""


@Client.on_message(filters.command(["stripeauth", "sauth"]) | filters.regex(r"^\.sauth(\s|$)"))
async def handle_stripeauth_command(client: Client, message: Message):
    """
    Handle /stripeauth command for Stripe Auth checking (alternative command).
    Main /au command is handled in BOT/Auth/Stripe/single.py
    Uses external API with site rotation for real results.
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

<b>Usage:</b> <code>/au cc|mm|yy|cvv</code>
<b>Example:</b> <code>/au 4111111111111111|12|2025|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                """<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Card format is incorrect</code>

<b>Format:</b> <code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>
<b>Example:</b> <code>/au 4111111111111111|12|25|123</code>""",
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
        # Normalize year
        if len(yy) == 2:
            yy = "20" + yy
        fullcc = f"{card_num}|{mm}|{yy}|{cvv}"
        
        # Get user info
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")
        profile = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        
        user_info = {"profile": profile, "plan": plan, "badge": badge}
        
        start_time = time()
        
        # Show processing message
        loading_msg = await message.reply(
            f"""<pre>Processing Request...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Gate:</b> <code>Stripe Auth</code>
<b>• Status:</b> <i>Checking... ◐</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
        
        # Check card with retry
        result, retry_count = await check_stripe_auth_with_retry(fullcc)
        
        time_taken = round(time() - start_time, 2)
        
        # Format response
        final_message = format_response(fullcc, result, user_info, time_taken, retry_count)
        
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
        
        # Deduct credit
        success, msg = deduct_credit(user_id)
        if not success:
            print(f"Credit deduction failed for user {user_id}")
        
    except Exception as e:
        print(f"Error in /au command: {e}")
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
