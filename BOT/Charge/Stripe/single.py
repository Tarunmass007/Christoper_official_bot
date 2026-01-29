"""
Professional Stripe $20 Charge Handler
Handles /st and $st commands for Stripe charge checking.
"""

import re
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode, ChatType

from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.Charge.Stripe.api import async_stripe_charge
from BOT.gc.credit import has_credits, deduct_credit

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None


def extract_card(text):
    """Extract card details from text in format cc|mm|yy|cvv"""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


@Client.on_message(filters.command(["st", "stripe"]) | filters.regex(r"^\$st(\s|$)"))
async def handle_stripe_charge(client, message):
    """
    Handle /st command for Stripe $20 Charge

    Usage: /st cc|mm|yy|cvv
    Example: /st 4405639706340195|03|2029|734
    """
    try:
        if not message.from_user:
            return
        
        # Load users and check registration
        users = load_users()
        user_id = str(message.from_user.id)

        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        # Check private access
        if not await check_private_access(message):
            return

        # Check premium user
        if not await is_premium_user(message):
            return

        # Check credits
        if not has_credits(user_id):
            return await message.reply(
                """<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
<b>Get Credits To Use</b>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        # Extract card from command or replied message
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                f"""<pre>CC Not Found ❌</pre>
<b>Error:</b> <code>No CC Found in your input</code>
<b>Usage:</b> <code>/st cc|mm|yy|cvv</code>
<b>Example:</b> <code>/st 4405639706340195|03|2029|734</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                f"""<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Send CC in Correct Format</code>
<b>Usage:</b> <code>/st cc|mm|yy|cvv</code>
<b>Example:</b> <code>/st 4405639706340195|03|2029|734</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        # Check antispam
        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            return await message.reply(
                f"""<pre>Antispam Detected ⚠️</pre>
<b>Message:</b> <code>You are detected as spamming</code>
<code>Try after {wait_time}s to use me again</code> <b>OR</b>
<code>Reduce Antispam Time /buy Using Paid Plan</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        card, mes, ano, cvv = extracted
        fullcc = f"{card}|{mes}|{ano}|{cvv}"

        start_time = time()

        # Get user info
        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        # Show processing message
        loading_msg = await message.reply(
            f"""<pre>Processing Stripe $20 Charge..!</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card -</b> <code>{fullcc}</code>
<b>• Gate -</b> <code>Stripe Balliante $20</code>
<b>• Status -</b> <code>Charging...</code>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

        # Check card using Stripe charge
        result = await async_stripe_charge(card, mes, ano, cvv)
        
        time_taken = round(time() - start_time, 2)

        # Determine status
        status = result.get("status", "error")
        response_msg = result.get("response", "UNKNOWN_ERROR")

        if status == "charged":
            status_text = "Charged 💎"
            header = "CHARGED"
        elif status == "approved":
            status_text = "Approved ✅"
            header = "CCN LIVE"
        elif status == "declined":
            status_text = "Declined ❌"
            header = "DECLINED"
        else:
            status_text = "Error ⚠️"
            header = "ERROR"

        # BIN lookup
        bin_data = get_bin_details(card[:6]) if get_bin_details else None
        if bin_data:
            vendor = bin_data.get('vendor', 'N/A')
            card_type = bin_data.get('type', 'N/A')
            level = bin_data.get('level', 'N/A')
            bank = bin_data.get('bank', 'N/A')
            country = bin_data.get('country', 'N/A')
            country_flag = bin_data.get('flag', '🏳️')
        else:
            vendor = "N/A"
            card_type = "N/A"
            level = "N/A"
            bank = "N/A"
            country = "N/A"
            country_flag = "🏳️"

        # Format final message
        final_msg = f"""<b>[#Stripe] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>Stripe Balliante $20</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{response_msg}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{card[:6]}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code> | <b>Proxy:</b> <code>Live ⚡️</code>"""

        # Add buttons
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                InlineKeyboardButton("Plans", callback_data="plans_info")
            ]
        ])

        # Send final response
        await loading_msg.edit(
            final_msg,
            reply_markup=buttons,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML
        )

        # Deduct credit
        success, msg = deduct_credit(user_id)
        if not success:
            print(f"Credit deduction failed for user {user_id}")

    except Exception as e:
        print(f"Error in /st: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(
            "<code>Internal Error Occurred. Try again later.</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
