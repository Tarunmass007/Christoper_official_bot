"""
Stripe Auth Single Card Checker
===============================
Handles /au command for Stripe authentication checks.

Uses shop.nomade-studio.be (primary) or grownetics.com (secondary) with auto-registration.
Each check creates a new account for maximum speed and reliability.
"""

import re
import random
from time import time
from datetime import datetime
import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

# Anime character names for gateway display (professional)
ANIME_CHARACTERS = [
    "Naruto Uzumaki", "Sasuke Uchiha", "Goku", "Luffy", "Ichigo Kurosaki",
    "Eren Yeager", "Levi Ackerman", "Tanjiro Kamado", "Zenitsu Agatsuma",
    "Gojo Satoru", "Yuji Itadori", "Megumi Fushiguro", "Kakashi Hatake",
    "Itachi Uchiha", "Monkey D. Luffy", "Roronoa Zoro", "Sanji Vinsmoke",
    "Light Yagami", "L Lawliet", "Edward Elric", "Alphonse Elric",
    "Spike Spiegel", "Vash the Stampede", "Guts", "Griffith",
    "Kenshin Himura", "Saitama", "Genos", "Mob", "Reigen Arataka",
    "Deku", "Katsuki Bakugo", "Shoto Todoroki", "All Might",
    "Levi", "Mikasa Ackerman", "Armin Arlert", "Erwin Smith"
]

from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.helper.antispam import can_run_command
from BOT.gc.credit import deduct_credit, has_credits

# Import the Nomade and Starr checkers
from BOT.Auth.StripeAuth.nomade_checker import check_nomade_stripe, determine_nomade_status
from BOT.Auth.StripeAuth.starr_checker import check_starr_stripe, determine_starr_status
from BOT.Auth.StripeAuth.au_gate import (
    get_au_gate,
    get_au_gate_url,
    toggle_au_gate,
    gate_display_name,
)

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

user_locks = {}


def extract_card(text: str):
    """Extract card details from text in format cc|mm|yy|cvv."""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


def format_response(fullcc: str, result: dict, user_info: dict, time_taken: float) -> str:
    """Format the Stripe Auth response in professional style."""
    parts = fullcc.split("|")
    cc = parts[0] if len(parts) > 0 else "Unknown"
    
    response = result.get("response", "UNKNOWN")
    message = result.get("message", "Unknown")
    # site variable not used - URLs never shown
    
    # Determine status and header (support all checkers)
    gate_key = get_au_gate(str(result.get("user_id", ""))) if "user_id" in result else get_au_gate("")
    if gate_key == "starr":
        status = determine_starr_status(result)
    else:
        status = determine_nomade_status(result)  # Default to nomade (Gate-1)
    
    if status == "APPROVED":
        header = "APPROVED"
        status_text = "Approved ✅"
    elif status == "3DS_REQUIRED":
        header = "CCN LIVE"
        status_text = "3DS Required ✅"
    elif status == "CCN LIVE":
        header = "CCN LIVE"
        status_text = "CCN Live ⚡"
    elif status == "DECLINED":
        header = "DECLINED"
        status_text = "Declined ❌"
    else:
        header = "ERROR"
        status_text = "Error ⚠️"
    
    # Clean up response for display
    response_display = response.replace("_", " ").title() if response else "Unknown"
    message_display = message[:80] if message else "Unknown"
    
    # BIN lookup
    bin_data = get_bin_details(cc[:6]) if get_bin_details else None
    
    if bin_data:
        bin_number = bin_data.get('bin', cc[:6])
        vendor = bin_data.get('vendor', 'N/A')
        card_type = bin_data.get('type', 'N/A')
        level = bin_data.get('level', 'N/A')
        bank = bin_data.get('bank', 'N/A')
        country = bin_data.get('country', 'N/A')
        country_flag = bin_data.get('flag', '🏳️')
    else:
        bin_number = cc[:6]
        vendor = "N/A"
        card_type = "N/A"
        level = "N/A"
        bank = "N/A"
        country = "N/A"
        country_flag = "🏳️"
    
    # Use random anime character name instead of site name (professional)
    anime_name = random.choice(ANIME_CHARACTERS)
    
    return f"""<b>[#StripeAuth] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>Stripe Auth [{anime_name}]</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{message_display}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_number}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user_info['profile']} [<code>{user_info['plan']} {user_info['badge']}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code> | Proxy: <code>Live ⚡️</code>"""


@Client.on_message(filters.command("au") | filters.regex(r"^\$au(\s|$)"))
async def handle_au_command(client: Client, message: Message):
    """
    Handle /au and $au commands for Stripe Auth checking.
    
    Uses WooCommerce Stripe auth with auto-registration.
    """
    if not message.from_user:
        return
    
    user_id = str(message.from_user.id)
    
    # Check for ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/au</code> <b>request is still processing.</b>",
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
        
        # Check credits
        if not has_credits(user_id):
            return await message.reply(
                """<pre>Notification ❗️</pre>
<b>Message:</b> <code>You Have Insufficient Credits</code>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Extract card
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
        
        if not target_text:
            return await message.reply(
                """<pre>Card Not Found ❌</pre>
<b>Error:</b> <code>No card found in your input</code>

<b>Usage:</b> <code>/au cc|mm|yy|cvv</code>
<b>Example:</b> <code>/au 4111111111111111|12|2025|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                """<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Card format is incorrect</code>

<b>Format:</b> <code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>
<b>Example:</b> <code>/au 4111111111111111|12|25|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Antispam check
        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            return await message.reply(
                f"""<pre>Antispam Detected ⚠️</pre>
<b>Message:</b> <code>Please wait before checking again</code>
<b>Try again in:</b> <code>{wait_time}s</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Prepare card
        card_num, mm, yy, cvv = extracted
        if len(yy) == 2:
            yy = "20" + yy
        fullcc = f"{card_num}|{mm}|{yy}|{cvv}"
        
        # Get user info
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🧿")
        profile = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        
        user_info = {"profile": profile, "plan": plan, "badge": badge}
        
        start_time = time()
        gate_key = get_au_gate(user_id)
        gate_label = gate_display_name(gate_key)  # Gate-1 or Gate-2 (NO URLs)

        # Show processing message (NO URLs shown)
        loading_msg = await message.reply(
            f"""<pre>Processing Request...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Gate:</b> <code>{gate_label}</code>
<b>• Status:</b> <i>Registering and checking... ◐</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

        # Check card using appropriate checker based on gate
        if gate_key == "nomade":
            # Use fast Nomade checker
            result = await check_nomade_stripe(fullcc)
                    # Convert nomade result format to match expected format
            if result.get("response") == "APPROVED":
                result["response"] = "APPROVED"
            elif result.get("response") == "3DS_REQUIRED":
                result["response"] = "3DS_REQUIRED"
            elif result.get("response") == "CCN LIVE" or result.get("response") == "CCN_LIVE":
                result["response"] = "CCN LIVE"
            else:
                result["response"] = result.get("response", "DECLINED")
        elif gate_key == "starr":
            # Use fast Starr checker
            result = await check_starr_stripe(fullcc)
                    # Convert starr result format to match expected format
            if result.get("response") == "APPROVED":
                result["response"] = "APPROVED"
            elif result.get("response") == "3DS_REQUIRED":
                result["response"] = "3DS_REQUIRED"
            elif result.get("response") == "CCN LIVE" or result.get("response") == "CCN_LIVE":
                result["response"] = "CCN LIVE"
            else:
                result["response"] = result.get("response", "DECLINED")
        else:
            # Fallback to nomade if unknown gate
            result = await check_nomade_stripe(fullcc)

        time_taken = round(time() - start_time, 2)

        # Format response
        final_message = format_response(fullcc, result, user_info, time_taken)

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Change gate", callback_data="au_change_gate"),
                InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                InlineKeyboardButton("Plans", callback_data="plans_info")
            ]
        ])
        
        await loading_msg.edit(
            final_message,
            reply_markup=buttons,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML
        )
        
        # Deduct credit
        success, msg = deduct_credit(user_id)
        if not success:
            print(f"Credit deduction failed for user {user_id}")
        
    except Exception as e:
        print(f"Error in /au command: {e}")
        import traceback
        traceback.print_exc()
        try:
            await message.reply(
                f"<pre>Error Occurred ⚠️</pre>\n<code>{str(e)[:100]}</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        except:
            pass
    
    finally:
        user_locks.pop(user_id, None)


@Client.on_callback_query(filters.regex("^au_change_gate$"))
async def au_change_gate_callback(client: Client, cq: CallbackQuery):
    """Toggle Stripe Auth gate (Gate-1 <-> Gate-2) for /au and /mau. NO URLs shown."""
    if not cq.from_user:
        return
    user_id = str(cq.from_user.id)
    new_gate = toggle_au_gate(user_id)
    label = gate_display_name(new_gate)  # Gate-1 or Gate-2
    try:
        await cq.answer(f"Gate switched to {label}", show_alert=False)
        await cq.edit_message_text(
            f"""<pre>Stripe Auth Gate Changed</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Current gate:</b> <code>{label}</code>
<b>• Primary:</b> <code>Gate-1</code> (Fast ⚡)
<b>• Secondary:</b> <code>Gate-2</code>
<b>• Use</b> <code>/au</code> <b>or</b> <code>/mau</code> <b>to check.</b>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━""",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Change gate", callback_data="au_change_gate"),
                    InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                    InlineKeyboardButton("Plans", callback_data="plans_info")
                ]
            ]),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


@Client.on_message(filters.command("changegate") & filters.private)
async def change_gate_command(client: Client, message: Message):
    """Direct command to change Stripe Auth gate."""
    if not message.from_user:
        return
    
    user_id = str(message.from_user.id)
    current_gate = get_au_gate(user_id)
    current_label = gate_display_name(current_gate)
    
    # Toggle to the other gate
    new_gate = toggle_au_gate(user_id)
    new_label = gate_display_name(new_gate)
    
    await message.reply(
        f"""<pre>Stripe Auth Gate Changed</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Previous gate:</b> <code>{current_label}</code>
<b>• Current gate:</b> <code>{new_label}</code>
<b>• Primary:</b> <code>Gate-1</code> (Fast ⚡)
<b>• Secondary:</b> <code>Gate-2</code>
<b>• Use</b> <code>/au</code> <b>or</b> <code>/mau</code> <b>to check.</b>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━""",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Change gate", callback_data="au_change_gate"),
                InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher")
            ]
        ])
    )
