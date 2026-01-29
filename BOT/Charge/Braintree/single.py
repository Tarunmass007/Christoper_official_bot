import re
import time
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType
from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.helper.permissions import check_private_access
from BOT.Charge.Braintree.api import check_braintree
from BOT.Charge.Braintree.response import format_response
from BOT.gc.credit import has_credits, deduct_credit


def extract_card(text):
    """Extract card details from text in format cc|mm|yy|cvv"""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


@Client.on_message(filters.command(["br", "braintree", "b3"]) | filters.regex(r"^\.br(\s|$)") | filters.regex(r"^\.b3(\s|$)"))
async def handle_braintree(client, message):
    """
    Handle /br or /b3 command for Braintree card checking via Pixorize

    Usage: /b3 cc|mm|yy|cvv
    Example: /b3 4405639706340195|03|2029|734
    """
    try:
        # Load users and check registration
        users = load_users()
        user_id = str(message.from_user.id)

        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id
            )

        # Check private access
        if not await check_private_access(message):
            return

        # Check credits
        if not has_credits(user_id):
            return await message.reply(
                """<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
<b>Get Credits To Use</b>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                reply_to_message_id=message.id
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
<b>Usage:</b> <code>/br cc|mm|yy|cvv</code>
<b>Example:</b> <code>/br 4405639706340195|03|2029|734</code>""",
                reply_to_message_id=message.id
            )

        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                f"""<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Send CC in Correct Format</code>
<b>Usage:</b> <code>/br cc|mm|yy|cvv</code>
<b>Example:</b> <code>/br 4405639706340195|03|2029|734</code>""",
                reply_to_message_id=message.id
            )

        # Check antispam
        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            return await message.reply(
                f"""<pre>Antispam Detected ⚠️</pre>
<b>Message:</b> <code>You are detected as spamming</code>
<code>Try after {wait_time}s to use me again</code> <b>OR</b>
<code>Reduce Antispam Time /buy Using Paid Plan</code>""",
                reply_to_message_id=message.id
            )

        card, mes, ano, cvv = extracted
        fullcc = f"{card}|{mes}|{ano}|{cvv}"

        start_time = time.time()

        # Show processing message
        loading_msg = await message.reply(
            "<pre>Processing Your Request..!</pre>",
            reply_to_message_id=message.id
        )

        await loading_msg.edit(
            f"<pre>Processing Braintree Check..!</pre>\n"
            f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
            f"• <b>Card -</b> <code>{fullcc}</code>\n"
            f"• <b>Gate -</b> <code>Braintree [Pixorize]</code>"
        )

        # Check card using braintree
        result = await check_braintree(card, mes, ano, cvv)

        await loading_msg.edit(
            f"<pre>Processed ✔️</pre>\n"
            f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
            f"• <b>Card -</b> <code>{fullcc}</code>\n"
            f"• <b>Gate -</b> <code>Braintree [Pixorize]</code>"
        )

        # Format response
        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        user_info = {
            "plan": plan,
            "badge": badge,
            "checked_by": checked_by
        }

        final_msg = format_response(fullcc, result, start_time, user_info)

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
            disable_web_page_preview=True
        )

        # Deduct credit
        success, msg = deduct_credit(user_id)
        if not success:
            print(f"Credit deduction failed for user {user_id}")

    except Exception as e:
        print(f"Error in /br: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(
            "<code>Internal Error Occurred. Try again later.</code>",
            reply_to_message_id=message.id
        )
