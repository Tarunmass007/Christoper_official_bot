import re
from pyrogram import Client, filters
from time import time
import asyncio
from BOT.tools.braintree_cvv.api import async_check_braintree_cvv
from BOT.tools.braintree_cvv.iditarod_gate import IDITAROD_ACCOUNTS
from BOT.tools.proxy import get_proxy
from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.gc.credit import deduct_credit_bulk
from pyrogram.enums import ChatType

user_locks = {}

@Client.on_message(filters.command("mbt") | filters.regex(r"^\$mbt(\s|$)"))
async def handle_mbt_command(client, message):
    """Handle mass Braintree CVV check command: /mbt with multiple cards"""

    user_id = str(message.from_user.id)

    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/mbt</code> <b>request is still processing.</b>\n"
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
        plan_info = user_data.get("plan", {})
        mlimit = plan_info.get("mlimit")
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")

        # Default fallback if mlimit is None
        if mlimit is None or str(mlimit).lower() in ["null", "none"]:
            mlimit = 10_000  # effectively unlimited
        else:
            mlimit = int(mlimit)

        # Extract cards
        def extract_cards(text):
            return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ <b>Send cards!</b>\n1 per line:\n<code>4242424242424242|08|28|690</code>",
                reply_to_message_id=message.id
            )

        all_cards = extract_cards(target_text)
        if not all_cards:
            return await message.reply(
                "❌ No valid cards found!",
                reply_to_message_id=message.id
            )

        if len(all_cards) > mlimit:
            return await message.reply(
                f"❌ You can check max {mlimit} cards as per your plan!",
                reply_to_message_id=message.id
            )

        # Check credits
        available_credits = user_data["plan"].get("credits", 0)
        card_count = len(all_cards)

        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if card_count > available_credits:
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

        gateway = "M-Braintree CVV Auth [Iditarod]"
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"
        total_cc = len(all_cards)
        mbt_threads = min(len(IDITAROD_ACCOUNTS), max(1, total_cc))

        # Send loading message
        loader_msg = await message.reply(
            f"""<pre>✦ Parallel | {gateway}</pre>
<b>[⚬] Gateway -</b> <b>{gateway}</b>
<b>[⚬] CC Amount :</b> <code>{total_cc}</code>
<b>[⚬] Threads :</b> <code>{mbt_threads}</code>
<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[⚬] Status :</b> <code>Processing Request..!</code>
""",
            reply_to_message_id=message.id
        )

        start_time = time()
        final_results = []
        try:
            user_proxy = get_proxy(int(user_id))
        except Exception:
            user_proxy = None

        approved_count = 0
        declined_count = 0
        error_count = 0
        processed_count = 0

        for idx, fullcc in enumerate(all_cards, start=1):
            parts = fullcc.split("|")
            card, mes, ano, cvv = parts[0], parts[1], parts[2], parts[3]
            try:
                result = await async_check_braintree_cvv(card, mes, ano, cvv, user_proxy)
            except Exception as e:
                result = {"status": "error", "response": str(e)[:50]}
            status = result.get("status", "error")
            response = result.get("response", "Unknown error")

            if status == "approved":
                status_flag = "CVV VALID ✅"
                approved_count += 1
            elif status == "ccn":
                status_flag = "CCN LIVE ⚡"
                approved_count += 1
            elif status == "declined":
                status_flag = "DECLINED ❌"
                declined_count += 1
            else:
                status_flag = "ERROR ⚠️"
                error_count += 1
            processed_count = idx

            card = fullcc.split("|")[0] if "|" in fullcc else fullcc
            try:
                from TOOLS.getbin import get_bin_details
                bin_data = get_bin_details(card[:6])
                if bin_data:
                    bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')}"
                    country_info = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                else:
                    bin_info = "N/A"
                    country_info = "N/A"
            except Exception:
                bin_info = "N/A"
                country_info = "N/A"

            final_results.append(f"""<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Status:</b> <code>{status_flag}</code>
<b>[•] Response:</b> <code>{response or "-"}</code>
<b>[+] BIN:</b> <code>{card[:6]}</code> | <code>{bin_info}</code> | <code>{country_info}</code>
━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━""")

            if processed_count % 3 == 0 or processed_count == total_cc:
                ongoing_result = "\n".join(final_results[-10:])
                try:
                    await loader_msg.edit(
                        f"""<pre>✦ Parallel | {gateway}</pre>
{ongoing_result}
<b>💬 Progress :</b> <code>{processed_count}/{total_cc}</code>
<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[⚬] Dev :</b> <a href="https://t.me/Chr1shtopher">Christopher</a>
""",
                        disable_web_page_preview=True
                    )
                except Exception:
                    pass

        end_time = time()
        timetaken = round(end_time - start_time, 2)

        # Deduct credits
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit_bulk, user_id, card_count)

        # Final completion response with statistics
        from datetime import datetime
        current_time = datetime.now().strftime("%I:%M %p")

        completion_message = f"""<b>[#BraintreeCVV] | MASS CHECK ✦</b>
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{total_cc}</code>
💬 <b>Progress</b>    : <code>{processed_count}/{total_cc}</code>
✅ <b>CVV Valid/CCN</b>  : <code>{approved_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{timetaken}s</code> | <code>{current_time}</code>"""

        await loader_msg.edit(completion_message, disable_web_page_preview=True)

    except Exception as e:
        print(f"Error in /mbt command: {str(e)}")
        try:
            await message.reply(
                f"<b>⚠️ An error occurred:</b>\n<code>{str(e)}</code>",
                reply_to_message_id=message.id
            )
        except:
            pass

    finally:
        user_locks.pop(user_id, None)
