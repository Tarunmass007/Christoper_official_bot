import re
from pyrogram import Client, filters
from time import time
import asyncio
from BOT.tools.vbv.api import async_check_vbv
from BOT.tools.vbv.response import format_vbv_response
from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.gc.credit import deduct_credit
from pyrogram.enums import ChatType

user_locks = {}

@Client.on_message(filters.command("vbv") | filters.regex(r"^\$vbv(\s|$)"))
async def handle_vbv_command(client, message):
    """Handle single VBV check command: $vbv cc|mes|ano|cvv"""

    user_id = str(message.from_user.id)

    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>$vbv</code> <b>request is still processing.</b>\n"
            "<b>Please wait until it finishes.</b>",
            reply_to_message_id=message.id
        )

    user_locks[user_id] = True

    try:
        # Load users
        users = load_users()

        # Check if user is registered
        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id
            )

        # Premium check
        if not await is_premium_user(message):
            return

        # Private access check
        if not await check_private_access(message):
            return

        user_data = users[user_id]
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")

        # Extract card from command
        def extract_card(text):
            match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
            return match.groups() if match else None

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ <b>Send card in format:</b>\n<code>$vbv cc|mes|ano|cvv</code>\n\n"
                "<b>Example:</b> <code>$vbv 4147768578745265|04|2026|168</code>",
                reply_to_message_id=message.id
            )

        card_data = extract_card(target_text)
        if not card_data:
            return await message.reply(
                "❌ <b>Invalid card format!</b>\n"
                "<b>Use:</b> <code>$vbv cc|mes|ano|cvv</code>",
                reply_to_message_id=message.id
            )

        card, mes, ano, cvv = card_data

        # Check credits
        available_credits = user_data["plan"].get("credits", 0)
        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if available_credits < 1:
                    return await message.reply(
                        """<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
<b>Get Credits To Use</b>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                        reply_to_message_id=message.id
                    )
            except:
                return await message.reply(
                    "⚠️ Error reading your credit balance.",
                    reply_to_message_id=message.id
                )

        gateway = "VBV Checker [VoidAPI]"
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        # Send loading message
        fullcc = f"{card}|{mes}|{ano}|{cvv}"
        loader_msg = await message.reply(
            f"""<pre>━━━ VBV Checker ━━━</pre>
<b>Card:</b> <code>{fullcc}</code>
<b>Status:</b> <code>Processing...</code>
<b>Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
━━━━━━━━━━━━━━━""",
            reply_to_message_id=message.id
        )

        # Process VBV check
        start_time = time()
        result = await async_check_vbv(card, mes, ano, cvv)
        end_time = time()
        timetaken = round(end_time - start_time, 2)

        # Deduct credit
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit, user_id)

        # Format and send response
        status = result.get("status", "error")
        response = result.get("response", "Unknown error")

        # Status emoji
        if status == "approved":
            status_emoji = "✅"
            status_text = "VBV Passed"
        elif status == "declined":
            status_emoji = "❌"
            status_text = "VBV Failed"
        else:
            status_emoji = "⚠️"
            status_text = "Error"

        from datetime import datetime
        current_time = datetime.now().strftime("%I:%M %p")

        final_message = f"""<pre>━━━ VBV Checker ━━━</pre>
<b>Card:</b> <code>{fullcc}</code>
<b>Status:</b> <code>{status_text} {status_emoji}</code>
<b>Response:</b> <code>{response}</code>
━━━━━━━━━━━━━━━
<b>⏱️ Time:</b> <code>{timetaken}s</code>
<b>Gateway:</b> <code>{gateway}</code>
<b>Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>"""

        await loader_msg.edit(final_message, disable_web_page_preview=True)

    except Exception as e:
        print(f"Error in $vbv command: {str(e)}")
        await message.reply(
            f"<b>⚠️ An error occurred:</b>\n<code>{str(e)}</code>",
            reply_to_message_id=message.id
        )

    finally:
        user_locks.pop(user_id, None)
