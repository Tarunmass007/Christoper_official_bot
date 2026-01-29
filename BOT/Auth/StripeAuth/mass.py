"""
Stripe Auth Mass Card Checker
=============================
Handles /mau command for mass Stripe authentication checks.

Uses ONLY the external API: https://dclub.site/apis/stripe/auth/st7.php
All checks are done via this API with site rotation on errors.
"""

import re
import asyncio
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode, ChatType

from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access
from BOT.gc.credit import deduct_credit_bulk

# Import ONLY the external API functions - no other checking logic is used
from BOT.Auth.StripeAuth.api import check_stripe_auth_with_retry, determine_status

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

user_locks = {}


def extract_cards(text: str):
    """Extract all cards from text."""
    return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)


@Client.on_message(filters.command(["mstripeauth", "msauth"]) | filters.regex(r"^\.msauth(\s|$)"))
async def handle_mstripeauth_command(client: Client, message: Message):
    """
    Handle /mau command for mass Stripe Auth checking.
    """
    user_id = str(message.from_user.id)
    
    if not message.from_user:
        return await message.reply("❌ Cannot process this message.")
    
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/mau</code> <b>request is still processing.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    user_locks[user_id] = True
    
    try:
        users = load_users()
        
        if user_id not in users:
            return await message.reply(
                "<pre>Access Denied 🚫</pre>\n"
                "<b>You must register first using</b> <code>/register</code> <b>command.</b>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        if not await check_private_access(message):
            return
        
        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        mlimit = plan_info.get("mlimit")
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")
        
        if mlimit is None or str(mlimit).lower() in ["null", "none"]:
            mlimit = 10_000
        else:
            mlimit = int(mlimit)
        
        # Get cards
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
        
        if not target_text:
            return await message.reply(
                "❌ Send cards! Reply to a message with cards or provide them after the command.",
                reply_to_message_id=message.id
            )
        
        all_cards = extract_cards(target_text)
        if not all_cards:
            return await message.reply("❌ No valid cards found!", reply_to_message_id=message.id)
        
        if len(all_cards) > mlimit:
            return await message.reply(
                f"❌ You can check max {mlimit} cards as per your plan!",
                reply_to_message_id=message.id
            )
        
        # Check credits
        available_credits = user_data.get("plan", {}).get("credits", 0)
        card_count = len(all_cards)
        
        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if card_count > available_credits:
                    return await message.reply(
                        "<pre>Notification ❗️</pre>\n"
                        "<b>Message:</b> <code>You Have Insufficient Credits</code>\n"
                        "<b>Type <code>/buy</code> to get Credits.</b>",
                        reply_to_message_id=message.id,
                        parse_mode=ParseMode.HTML
                    )
            except:
                pass
        
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"
        
        # Send initial message
        loader_msg = await message.reply(
            f"""<pre>✦ [#MAU] | Mass Stripe Auth</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Gateway:</b> <code>Stripe Auth</code>
<b>[⚬] Cards:</b> <code>{card_count}</code>
<b>[⚬] Status:</b> <code>Processing...</code>
━━━━━━━━━━━━━━━
<b>[⚬] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
        
        start_time = time()
        
        # Statistics
        total_cc = len(all_cards)
        approved_count = 0
        declined_count = 0
        charged_count = 0
        error_count = 0
        processed_count = 0
        total_retries = 0
        
        # Process cards
        for idx, card in enumerate(all_cards, start=1):
            processed_count = idx
            
            # Normalize year
            parts = card.split("|")
            if len(parts) == 4 and len(parts[2]) == 2:
                parts[2] = "20" + parts[2]
                card = "|".join(parts)
            
            # Check card
            result, retries = await check_stripe_auth_with_retry(card)
            total_retries += retries
            
            # Get status - prefer pre-computed if available
            status_text = result.get("status_text")
            header = result.get("header")
            is_live = result.get("success", False)
            
            if not status_text or not header:
                status_text, header, is_live = determine_status(result)
            
            # Count stats based on header for accuracy
            if header == "CHARGED":
                charged_count += 1
            elif header == "CCN LIVE":
                approved_count += 1
            elif header == "ERROR":
                error_count += 1
            else:
                declined_count += 1
            
            # Send individual result for charged/approved
            if is_live:
                cc_num = card.split("|")[0] if "|" in card else card
                try:
                    bin_data = get_bin_details(cc_num[:6])
                    if bin_data:
                        bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')} - {bin_data.get('level', 'N/A')}"
                        bank = bin_data.get('bank', 'N/A')
                        country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                    else:
                        bin_info = "N/A"
                        bank = "N/A"
                        country = "N/A"
                except:
                    bin_info = "N/A"
                    bank = "N/A"
                    country = "N/A"
                
                # Clean up response for display
                response_display = result.get('response', 'N/A').replace('_', ' ').title()[:50]
                message_display = result.get('message', 'N/A')[:80]
                
                hit_message = f"""<b>[#StripeAuth] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card}</code>
<b>[•] Gateway:</b> <code>Stripe Auth</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{response_display}</code>
<b>[•] Message:</b> <code>{message_display}</code>
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
                except:
                    pass
            
            # Update progress every 3 cards
            if idx % 3 == 0 or idx == total_cc:
                try:
                    await loader_msg.edit(
                        f"""<pre>✦ [#MAU] | Mass Stripe Auth</pre>
━━━━━━━━━━━━━━━
<b>🟢 Total CC:</b> <code>{total_cc}</code>
<b>💬 Progress:</b> <code>{processed_count}/{total_cc}</code>
<b>✅ Approved:</b> <code>{approved_count}</code>
<b>💎 Charged:</b> <code>{charged_count}</code>
<b>❌ Declined:</b> <code>{declined_count}</code>
<b>⚠️ Errors:</b> <code>{error_count}</code>
━━━━━━━━━━━━━━━
<b>🔄 Retries:</b> <code>{total_retries}</code>
<b>👤 Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]""",
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                except:
                    pass
        
        end_time = time()
        timetaken = round(end_time - start_time, 2)
        
        # Deduct credits
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit_bulk, user_id, len(all_cards))
        
        # Final message
        current_time = datetime.now().strftime("%I:%M %p")
        
        completion_message = f"""<pre>✦ CC Check Completed</pre>
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{total_cc}</code>
💬 <b>Progress</b>    : <code>{processed_count}/{total_cc}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
💎 <b>Charged</b>     : <code>{charged_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
━━━━━━━━━━━━━━━
⏱️ <b>Time Elapsed</b> : <code>{timetaken}s</code>
👤 <b>Checked By</b> : {checked_by} [<code>{plan} {badge}</code>]
🔧 <b>Dev</b>: <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>
━━━━━━━━━━━━━━━"""
        
        await loader_msg.edit(completion_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        
    except Exception as e:
        await message.reply(f"⚠️ Error: {e}", reply_to_message_id=message.id)
    
    finally:
        user_locks.pop(user_id, None)
