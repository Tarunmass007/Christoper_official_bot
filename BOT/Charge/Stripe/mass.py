"""
Mass Stripe $20 Charge Handler
Handles /mst command for mass Stripe checking.
"""

import re
import time
import asyncio
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.Charge.Stripe.api import async_stripe_charge
from BOT.gc.credit import deduct_credit_bulk

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

user_locks = {}


def extract_cards(text):
    """Extract all cards from text."""
    return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)


def get_status_flag(status, response):
    """Determine status flag from result."""
    if status == "charged":
        return "Charged 💎"
    elif status == "approved":
        return "Approved ✅"
    elif status == "declined":
        return "Declined ❌"
    else:
        return "Error ⚠️"


@Client.on_message(filters.command(["mst", "mstripe"]) | filters.regex(r"^\$mst(\s|$)"))
async def handle_mass_stripe(client, message):
    """
    Handle /mst command for mass Stripe $20 Charge checking.
    
    Usage: /mst (reply to list of cards)
    """
    if not message.from_user:
        return
    
    user_id = str(message.from_user.id)
    
    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/mst</code> <b>request is still processing.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    user_locks[user_id] = True
    
    try:
        users = load_users()
        
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
        
        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        mlimit = plan_info.get("mlimit")
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")
        
        # Default limit if None
        if mlimit is None or str(mlimit).lower() in ["null", "none"]:
            mlimit = 10_000
        else:
            mlimit = int(mlimit)
        
        # Extract cards
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
        
        if not target_text:
            return await message.reply(
                "❌ <b>Send cards!</b>\n1 per line:\n<code>4242424242424242|08|28|690</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        all_cards = extract_cards(target_text)
        if not all_cards:
            return await message.reply(
                "❌ No valid cards found!",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        if len(all_cards) > mlimit:
            return await message.reply(
                f"❌ You can check max {mlimit} cards as per your plan!",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
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
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                        reply_to_message_id=message.id,
                        parse_mode=ParseMode.HTML
                    )
            except:
                pass
        
        gateway = "Stripe $20 Balliante"
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"
        
        # Send loading message
        loader_msg = await message.reply(
            f"""<pre>✦ Mass Stripe $20 Check</pre>
<b>[⚬] Gateway:</b> <code>{gateway}</code>
<b>[⚬] CC Amount:</b> <code>{card_count}</code>
<b>[⚬] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[⚬] Status:</b> <code>Processing...</code>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
        
        start_time = time.time()
        final_results = []
        
        # Statistics
        total_cc = len(all_cards)
        charged_count = 0
        approved_count = 0
        declined_count = 0
        error_count = 0
        processed_count = 0
        
        for fullcc in all_cards:
            card, mes, ano, cvv = fullcc.split("|")
            
            # Check card
            result = await async_stripe_charge(card, mes, ano, cvv)
            
            status = result.get("status", "error")
            response = result.get("response", "Unknown error")
            
            status_flag = get_status_flag(status, response)
            
            # Count statistics
            if status == "charged":
                charged_count += 1
            elif status == "approved":
                approved_count += 1
            elif status == "declined":
                declined_count += 1
            else:
                error_count += 1
            
            processed_count += 1
            
            # Get BIN info
            try:
                bin_data = get_bin_details(card[:6])
                if bin_data:
                    bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')}"
                    country_info = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                else:
                    bin_info = "N/A"
                    country_info = "N/A"
            except:
                bin_info = "N/A"
                country_info = "N/A"
            
            final_results.append(
                f"<b>[•] Card:</b> <code>{fullcc}</code>\n"
                f"<b>[•] Status:</b> <code>{status_flag}</code>\n"
                f"<b>[•] Response:</b> <code>{response[:50]}</code>\n"
                f"<b>[+] BIN:</b> <code>{card[:6]}</code> | <code>{bin_info}</code> | <code>{country_info}</code>\n"
                "━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━"
            )
            
            # Update progress (show last 5 cards)
            ongoing_result = "\n".join(final_results[-5:])
            try:
                await loader_msg.edit(
                    f"<pre>✦ Mass Stripe $20 Check</pre>\n"
                    f"{ongoing_result}\n"
                    f"<b>💬 Progress:</b> <code>{processed_count}/{total_cc}</code>\n"
                    f"<b>[⚬] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]",
                    disable_web_page_preview=True,
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        
        end_time = time.time()
        timetaken = round(end_time - start_time, 2)
        
        # Deduct credits
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit_bulk, user_id, card_count)
        
        # Final completion message
        from datetime import datetime
        current_time = datetime.now().strftime("%I:%M %p")
        
        completion_message = f"""<b>[#Stripe] | MASS CHECK ✦</b>
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{total_cc}</code>
💬 <b>Progress</b>    : <code>{processed_count}/{total_cc}</code>
💎 <b>Charged</b>     : <code>{charged_count}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{timetaken}s</code> | <code>{current_time}</code>"""
        
        await loader_msg.edit(
            completion_message,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML
        )
    
    except Exception as e:
        print(f"Error in /mst: {e}")
        import traceback
        traceback.print_exc()
        try:
            await message.reply(
                f"<b>⚠️ An error occurred:</b>\n<code>{str(e)}</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        except:
            pass
    
    finally:
        user_locks.pop(user_id, None)
