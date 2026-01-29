import re
from pyrogram import Client, filters
from time import time
import asyncio
from BOT.tools.braintree_cvv.api import async_check_braintree_cvv
from BOT.tools.proxy import get_proxy
from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.gc.credit import deduct_credit
from pyrogram.enums import ChatType

user_locks = {}

@Client.on_message(filters.command("bt") | filters.regex(r"^\$bt(\s|$)"))
async def handle_bt_command(client, message):
    """Handle single Braintree CVV check command: /bt cc|mes|ano|cvv or $bt cc|mes|ano|cvv proxy"""

    user_id = str(message.from_user.id)

    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/bt</code> <b>request is still processing.</b>\n"
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

        # Extract card and proxy from command
        def extract_card_and_proxy(text):
            # Pattern: card|month|year|cvv [optional proxy]
            match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})(?:\s+(.+))?', text)
            if match:
                card, mes, ano, cvv, proxy = match.groups()
                return card, mes, ano, cvv, proxy
            return None

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ <b>Send card in format:</b>\n<code>/bt cc|mes|ano|cvv</code>\n"
                "<code>/bt cc|mes|ano|cvv user:pass@ip:port</code>\n\n"
                "<b>Example:</b> <code>/bt 4242424242424242|08|28|690</code>",
                reply_to_message_id=message.id
            )

        card_data = extract_card_and_proxy(target_text)
        if not card_data:
            return await message.reply(
                "❌ <b>Invalid card format!</b>\n"
                "<b>Use:</b> <code>/bt cc|mes|ano|cvv</code>",
                reply_to_message_id=message.id
            )

        card, mes, ano, cvv, proxy = card_data
        if not proxy:
            try:
                proxy = get_proxy(int(user_id))
            except Exception:
                pass

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

        gateway = "Braintree CVV Auth [Iditarod]"
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        # Send loading message
        fullcc = f"{card}|{mes}|{ano}|{cvv}"
        proxy_text = f"\n<b>Proxy:</b> <code>{proxy}</code>" if proxy else ""
        loader_msg = await message.reply(
            f"""<pre>━━━ Braintree CVV Auth ━━━</pre>
<b>Card:</b> <code>{fullcc}</code>
<b>Status:</b> <code>Processing...</code>{proxy_text}
<b>Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
━━━━━━━━━━━━━━━""",
            reply_to_message_id=message.id
        )

        # Process Braintree CVV check
        start_time = time()
        result = await async_check_braintree_cvv(card, mes, ano, cvv, proxy)
        end_time = time()
        timetaken = round(end_time - start_time, 2)

        # Deduct credit
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit, user_id)

        # Format and send response
        status = result.get("status", "error")
        response = result.get("response", "Unknown error")

        # Status emoji and text based on status
        if status == "approved":
            status_emoji = "✅"
            status_text = "CVV VALID"
            header = "CVV MATCHED"
        elif status == "ccn":
            status_emoji = "⚡"
            status_text = "CCN LIVE"
            header = "WRONG CVV"
        elif status == "declined":
            status_emoji = "❌"
            status_text = "DECLINED"
            header = "DEAD CARD"
        else:
            status_emoji = "⚠️"
            status_text = "ERROR"
            header = "ERROR"

        from datetime import datetime
        current_time = datetime.now().strftime("%I:%M %p")
        
        # Get BIN info
        try:
            from TOOLS.getbin import get_bin_details
            bin_data = get_bin_details(card[:6])
            if bin_data:
                bin_number = bin_data.get('bin', card[:6])
                vendor = bin_data.get('vendor', 'N/A')
                card_type = bin_data.get('type', 'N/A')
                level = bin_data.get('level', 'N/A')
                bank = bin_data.get('bank', 'N/A')
                country = bin_data.get('country', 'N/A')
                country_flag = bin_data.get('flag', '🏳️')
            else:
                bin_number = card[:6]
                vendor, card_type, level = "N/A", "N/A", "N/A"
                bank, country, country_flag = "N/A", "N/A", "🏳️"
        except:
            bin_number = card[:6]
            vendor, card_type, level = "N/A", "N/A", "N/A"
            bank, country, country_flag = "N/A", "N/A", "🏳️"

        final_message = f"""<b>[#BraintreeCVV] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>Braintree CVV Auth</code>
<b>[•] Status:</b> <code>{status_text} {status_emoji}</code>
<b>[•] Response:</b> <code>{response}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_number}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{timetaken}s</code> | <b>Proxy:</b> <code>{'Live ⚡️' if proxy else 'None'}</code>"""

        await loader_msg.edit(final_message, disable_web_page_preview=True)

    except Exception as e:
        print(f"Error in /bt command: {str(e)}")
        await message.reply(
            f"<b>⚠️ An error occurred:</b>\n<code>{str(e)}</code>",
            reply_to_message_id=message.id
        )

    finally:
        user_locks.pop(user_id, None)
