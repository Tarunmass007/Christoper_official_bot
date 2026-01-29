import re
import time
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType
from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.helper.permissions import check_private_access
from BOT.Charge.Shopify.ash.api import check_autoshopify
from BOT.Charge.Shopify.ash.response import format_response
from BOT.gc.credit import has_credits, deduct_credit

def extract_card(text):
    """Extract card details from text in format cc|mm|yy|cvv"""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None

def extract_site(text):
    """Extract optional site URL from text in format site=https://..."""
    match = re.search(r'site=([^\s]+)', text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

@Client.on_message(filters.command(["autosh_disabled", "ash_disabled"]))
async def handle_autosh(client, message):
    """
    Handle /autosh command for AutoShopify card checking

    Usage: /autosh cc|mm|yy|cvv [site=https://store.myshopify.com/products/item]
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
<b>Usage:</b> <code>/autosh cc|mm|yy|cvv [site=URL]</code>
<b>Example:</b> <code>/autosh 4405639706340195|03|2029|734</code>
<b>With custom site:</b> <code>/autosh 4405639706340195|03|2029|734 site=https://store.myshopify.com/products/item</code>""",
                reply_to_message_id=message.id
            )

        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                f"""<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Send CC in Correct Format</code>
<b>Usage:</b> <code>/autosh cc|mm|yy|cvv [site=URL]</code>
<b>Example:</b> <code>/autosh 4405639706340195|03|2029|734</code>
<b>With custom site:</b> <code>/autosh 4405639706340195|03|2029|734 site=https://store.myshopify.com/products/item</code>""",
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

        # Extract optional site parameter
        site = extract_site(target_text)

        start_time = time.time()

        # Show processing message
        loading_msg = await message.reply(
            "<pre>Processing Your Request..!</pre>",
            reply_to_message_id=message.id
        )

        await loading_msg.edit(
            f"<pre>Processing AutoShopify Check..!</pre>\n"
            f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
            f"• <b>Card -</b> <code>{fullcc}</code>\n"
            f"• <b>Gate -</b> <code>AutoShopify</code>"
        )

        # Check card using autoshopify
        result = await check_autoshopify(fullcc, site=site)

        await loading_msg.edit(
            f"<pre>Processed ✔️</pre>\n"
            f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
            f"• <b>Card -</b> <code>{fullcc}</code>\n"
            f"• <b>Gate -</b> <code>AutoShopify</code>"
        )

        # Format response
        user_info = {
            "name": message.from_user.first_name,
            "id": user_id
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
        print(f"Error in /autosh: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(
            "<code>Internal Error Occurred. Try again later.</code>",
            reply_to_message_id=message.id
        )
