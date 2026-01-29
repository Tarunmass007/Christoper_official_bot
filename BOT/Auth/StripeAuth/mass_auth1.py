"""
Stripe Auth1 Mass Card Checker
==============================
Handles /mau1 command for mass WooCommerce Stripe authentication checks.
Uses booth-box.com style auto-registration flow.
"""

import re
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from time import time
import asyncio
from datetime import datetime

from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.gc.credit import deduct_credit_bulk

# Import the WC Auth1 checker
from BOT.Auth.StripeAuth.wc_auth1 import check_stripe_auth1, determine_status1

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


@Client.on_message(filters.command("mau1") | filters.regex(r"^\$mau1(\s|$)"))
async def handle_mau1_command(client, message):
    """
    Handle /mau1 and $mau1 commands for mass Stripe Auth1 checking.
    Uses WooCommerce auto-registration flow (booth-box style).
    """
    user_id = str(message.from_user.id)
    
    if not message.from_user:
        return await message.reply("❌ Cannot process this message.")
    
    # Check for ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/mau1</code> <b>request is still processing.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    user_locks[user_id] = True
    
    try:
        users = load_users()
        
        # Check registration
        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
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
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🧿")
        
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
            f"""<pre>✦ [#MAU1] | Mass Stripe Auth1 [WC]</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Gateway:</b> <code>Stripe Auth1 [WC]</code>
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
        ccn_live_count = 0
        declined_count = 0
        error_count = 0
        processed_count = 0
        
        # Process cards
        for idx, card in enumerate(all_cards, start=1):
            processed_count = idx
            
            # Normalize year
            parts = card.split("|")
            if len(parts) == 4 and len(parts[2]) == 2:
                parts[2] = "20" + parts[2]
                card = "|".join(parts)
            
            # Check card using WC Stripe Auth1
            result = await check_stripe_auth1(card)
            
            # Get status from result
            status = determine_status1(result)
            response = result.get("response", "UNKNOWN")
            message_text = result.get("message", "Unknown")
            site = result.get("site", "Unknown")
            
            # Determine header and status text
            if status == "APPROVED":
                header = "APPROVED"
                status_text = "Stripe Auth 0.0$ ✅"
                approved_count += 1
                is_hit = True
            elif status == "CCN LIVE":
                header = "CCN LIVE"
                status_text = "CCN Live ⚡"
                ccn_live_count += 1
                is_hit = True
            elif status == "DECLINED":
                header = "DECLINED"
                status_text = "Declined ❌"
                declined_count += 1
                is_hit = False
            else:
                header = "ERROR"
                status_text = "Error ⚠️"
                error_count += 1
                is_hit = False
            
            # Send individual result for hits (approved or CCN live)
            if is_hit:
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
                
                message_display = message_text[:60] if message_text else "N/A"
                site_display = site.replace("https://", "").replace("http://", "")[:25] if site else "WC Stripe"
                
                hit_message = f"""<b>[#StripeAuth1] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card}</code>
<b>[•] Gateway:</b> <code>Stripe Auth1 [{site_display}]</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{message_display}</code>
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
            
            # Update progress every 2 cards or last card
            if idx % 2 == 0 or idx == total_cc:
                try:
                    await loader_msg.edit(
                        f"""<pre>✦ [#MAU1] | Mass Stripe Auth1 [WC]</pre>
━━━━━━━━━━━━━━━
<b>🟢 Total CC:</b> <code>{total_cc}</code>
<b>💬 Progress:</b> <code>{processed_count}/{total_cc}</code>
<b>✅ Approved:</b> <code>{approved_count}</code>
<b>⚡ CCN Live:</b> <code>{ccn_live_count}</code>
<b>❌ Declined:</b> <code>{declined_count}</code>
<b>⚠️ Errors:</b> <code>{error_count}</code>
━━━━━━━━━━━━━━━
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
        
        completion_message = f"""<pre>✦ Stripe Auth1 Check Completed</pre>
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{total_cc}</code>
💬 <b>Progress</b>    : <code>{processed_count}/{total_cc}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
⚡ <b>CCN Live</b>    : <code>{ccn_live_count}</code>
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
