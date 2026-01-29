import re
from pyrogram import Client, filters
from time import time
from BOT.gc.credit import deduct_credit, has_credits
from BOT.Charge.Shopify.sho.sho import create_shopify_charge
from BOT.Charge.Shopify.sho.response import format_shopify_response
from BOT.helper.start import load_users 
from BOT.helper.antispam import can_run_command
from BOT.helper.permissions import check_private_access, load_allowed_groups
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType
from BOT.Charge.Shopify.tls_session import TLSAsyncSession

# ALLOWED_GROUPS = [-1002058346930]

@Client.on_message(filters.command("sho_disabled") | filters.regex(r"^\.sho_disabled(\s|$)"))
async def handle_sho_command(client, message):
    try:

        # Group approval check removed - all groups are now allowed
        # allowed_groups = load_allowed_groups()
        # if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and message.chat.id not in allowed_groups:
        #     return await message.reply(
        #         "<pre>Notification ❗️</pre>\n"
        #         "<b>~ Message :</b> <code>This Group Is Not Approved ⚠️</code>\n"
        #         "<b>~ Contact  →</b> <b>@Chr1shtopher</b>\n"
        #         "━━━━━━━━━━━━━\n"
        #         "<b>Contact Owner For Approving</b>"
        #     )

        users = load_users()
        user_id = str(message.from_user.id)

        if user_id not in users:
            return await message.reply("""<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""", reply_to_message_id=message.id)

        if not await check_private_access(message):
            return

        if not has_credits(user_id):
            return await message.reply(
                """<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
<b>Get Credits To Use</b>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""", reply_to_message_id=message.id
            )

        def extract_card(text):

            match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
            if match:
                return match.groups()
            return None


        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                f"""<pre>CC Not Found ❌</pre>
<b>Error:</b> <code>No CC Found in your input</code>
<b>Usage:</b> <code>/slf cc|mm|yy|cvv</code>""",
                reply_to_message_id=message.id
            )

        extracted = extract_card(target_text)

        if not extracted:
            return await message.reply(
                f"""<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Send CC in Correct Format</code>
<b>Usage:</b> <code>/slf cc|mm|yy|cvv</code>""",
                reply_to_message_id=message.id
            )
        
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
        start_time = time()
        fullccs = f"{card}|{mes}|{ano}|{cvv}"
        gateway = "Shopify Normal | 1.5$"
        
        # proxies = load_proxies()

        loader_msg = await message.reply(
            f"""<pre>Processing Your Request !</pre>""",
            reply_to_message_id=message.id
        )

        await loader_msg.edit(
            f"""<pre>Processing Your Request !</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
• <b>Card</b> - <code>{fullccs}</code>  
• <b>Gate</b> - <code>{gateway}</code>"""
        )

        async with TLSAsyncSession() as session:
          raw_response = await create_shopify_charge(card, mes, ano, cvv, session)

        await loader_msg.edit(
            f"""<pre>Processed ✔</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
• <b>Card</b> - <code>{fullccs}</code>  
• <b>Gate</b> - <code>{gateway}</code>"""
        )
        
        end_time = time()
        timet = round(end_time - start_time, 2)

        user_name = message.from_user.first_name
        profile = f"<a href='tg://user?id={message.from_user.id}'>{user_name}</a>"

        status_flag, formatted = format_shopify_response(card, mes, ano, cvv, raw_response, timet, profile)

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Support", url="https://t.me/SyncUI"),
                InlineKeyboardButton("Plans", callback_data="plans_info")
            ]
        ])

        await loader_msg.edit(
            formatted,
            reply_markup=buttons,
            disable_web_page_preview=True
        )
        
        success, msg = deduct_credit(user_id)
        if not success:
            print("Error in deducting credit")

    except Exception as e:
        print(f"Error occurred: {str(e)}")
