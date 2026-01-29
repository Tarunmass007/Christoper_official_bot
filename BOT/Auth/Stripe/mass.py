"""
Stripe Auth Mass Card Checker
=============================
Handles /mau command for mass Stripe authentication checks.

Uses Gate-1 (default) or Gate-2 with 33-thread parallel processing.
Each thread creates a new account for maximum speed and reliability.
NO URLs are displayed to users - only gate numbers.
"""

import re
import time
import os
import random
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
import asyncio
from datetime import datetime
from collections import deque

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
from BOT.gc.credit import deduct_credit_bulk

# Import the Nomade and Starr checkers
from BOT.Auth.StripeAuth.nomade_checker import check_nomade_stripe, determine_nomade_status
from BOT.Auth.StripeAuth.starr_checker import check_starr_stripe, determine_starr_status
from BOT.Auth.StripeAuth.au_gate import get_au_gate, gate_display_name

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

user_locks = {}
mau_stop_requested: dict[str, bool] = {}

# --- Parallel Processing Rate Limiter for /mau ---
class MassRateLimiter:
    """Rate limiter for 33-thread parallel processing - silver bullet performance."""
    def __init__(self, concurrency=33, requests_per_second=25):
        self.sem = asyncio.Semaphore(concurrency)
        self.requests_per_second = requests_per_second
        self.request_times = deque()
        self.lock = asyncio.Lock()
        self.current_delay = 0.01  # Ultra-fast for maximum speed
    
    async def wait_for_rate_limit(self):
        """Token bucket enforcement - optimized for speed"""
        import time as time_module
        async with self.lock:
            now = time_module.monotonic()
            while self.request_times and now - self.request_times[0] > 1.0:
                self.request_times.popleft()
            if len(self.request_times) >= self.requests_per_second:
                sleep_time = 1.0 - (now - self.request_times[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            self.request_times.append(time_module.monotonic())
    
    async def adaptive_delay(self):
        """Minimal delay for silver bullet speed"""
        await asyncio.sleep(self.current_delay)


def extract_cards(text: str):
    """Extract all cards from text."""
    return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)


@Client.on_message(filters.command("mau") | filters.regex(r"^\$mau(\s|$)"))
async def handle_mau_command(client, message):
    """
    Handle /mau and $mau commands for mass Stripe Auth checking.
    
    Uses WooCommerce Stripe auth with auto-registration.
    """
    user_id = str(message.from_user.id)
    
    if not message.from_user:
        return await message.reply("❌ Cannot process this message.")
    
    # Check for ongoing request
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
        
        # VIP plan has unlimited mass limit
        is_vip = plan == "VIP"
        
        if is_vip:
            mlimit = None  # Unlimited for VIP
        elif mlimit is None or str(mlimit).lower() in ["null", "none"]:
            mlimit = 10_000
        else:
            mlimit = int(mlimit)
        
        # Get cards from reply (file or text) or command argument
        all_cards = []
        
        # Check if replying to a message
        if message.reply_to_message:
            # Check if it's a file/document
            if message.reply_to_message.document:
                file_path = await message.reply_to_message.download()
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    all_cards = extract_cards(text)
                finally:
                    try:
                        if file_path and os.path.isfile(file_path):
                            os.remove(file_path)
                    except Exception:
                        pass
            # Check if it's text
            elif message.reply_to_message.text:
                all_cards = extract_cards(message.reply_to_message.text)
        
        # Check command argument
        if not all_cards and len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
            all_cards = extract_cards(target_text)
        
        if not all_cards:
            return await message.reply(
                """<pre>No Cards Found ❌</pre>
━━━━━━━━━━━━━━━
<b>Usage:</b>
• Reply to a message with cards
• Reply to a file (.txt) containing cards
• Or send cards after command: <code>/mau cards...</code>

<b>Format:</b> <code>cc|mm|yy|cvv</code>
<b>Example:</b> <code>4111111111111111|12|2025|123</code>
━━━━━━━━━━━━━━━""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # VIP has unlimited, other plans check limit
        if not is_vip and mlimit and len(all_cards) > mlimit:
            return await message.reply(
                f"❌ You can check max {mlimit} cards as per your plan!",
                reply_to_message_id=message.id
            )
        
        # Check credits (use final card count after limit)
        available_credits = user_data.get("plan", {}).get("credits", 0)
        card_count = len(all_cards)  # This is already limited to 50
        
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
        gate_key = get_au_gate(user_id)
        gate_label = gate_display_name(gate_key)  # Gate-1 or Gate-2 (NO URLs)
        
        # Ensure gate is valid (nomade or starr)
        if gate_key not in ["nomade", "starr"]:
            gate_key = "nomade"
            gate_label = "Gate-1"
        
        change_gate_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("Change gate", callback_data="au_change_gate")],
        ])
        
        stop_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹ Stop Checking", callback_data=f"mau_stop_{user_id}")],
        ])

        # Get final card count after limit
        final_card_count = len(all_cards)
        
        # Send initial message (NO URLs shown)
        loader_msg = await message.reply(
            f"""<pre>◐ [#MAU] | Mass Stripe Auth</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Gate:</b> <code>{gate_label}</code>
<b>[⚬] Cards:</b> <code>{final_card_count}</code> <i>(Max: 50)</i>
<b>[⚬] Mode:</b> <code>Parallel (33 threads)</code>
<b>[⚬] Status:</b> <code>◐ Processing...</code>
━━━━━━━━━━━━━━━
<b>[⚬] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
            reply_markup=stop_kb,
        )

        start_time = time.time()
        last_progress_edit = 0.0
        PROGRESS_THROTTLE = 0.4

        # Statistics
        total_cc = len(all_cards)
        approved_count = 0
        ccn_live_count = 0
        declined_count = 0
        error_count = 0
        processed_count = 0
        stopped = False
        
        # Normalize all cards first
        normalized_cards = []
        for card in all_cards:
            parts = card.split("|")
            if len(parts) == 4 and len(parts[2]) == 2:
                parts[2] = "20" + parts[2]
                card = "|".join(parts)
            normalized_cards.append(card)
        
        async def _edit_progress(force: bool = False):
            nonlocal last_progress_edit
            now = time.time()
            if not force and (now - last_progress_edit) < PROGRESS_THROTTLE:
                return
            elapsed = now - start_time
            rate = (processed_count / elapsed) if elapsed > 0 else 0
            try:
                await loader_msg.edit(
                    f"""<pre>◐ [#MAU] | Mass Stripe Auth</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Gate:</b> <code>{gate_label}</code>
<b>🟢 Total CC:</b> <code>{total_cc}</code>
<b>💬 Progress:</b> <code>{processed_count}/{total_cc}</code>
<b>✅ Approved:</b> <code>{approved_count}</code>
<b>⚡ CCN Live:</b> <code>{ccn_live_count}</code>
<b>❌ Declined:</b> <code>{declined_count}</code>
<b>⚠️ Errors:</b> <code>{error_count}</code>
<b>⏱️ Time:</b> <code>{elapsed:.1f}s</code> · <code>{rate:.1f} cc/s</code>
━━━━━━━━━━━━━━━
<b>👤 Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]""",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=stop_kb,
                )
                last_progress_edit = now
            except:
                pass
        
        # Initialize rate limiter for 33 threads
        limiter = MassRateLimiter(concurrency=33, requests_per_second=25)
        
        async def check_one_card(card: str):
            """Check a single card with new account creation (parallel safe)."""
            async with limiter.sem:
                try:
                    await limiter.wait_for_rate_limit()
                    await limiter.adaptive_delay()
                    
                    # Use appropriate checker based on gate
                    if gate_key == "nomade":
                        result = await check_nomade_stripe(card)
                    elif gate_key == "starr":
                        result = await check_starr_stripe(card)
                    else:
                        result = await check_nomade_stripe(card)
                    
                    # Convert to standard format
                    if result.get("response") == "APPROVED":
                        result["response"] = "APPROVED"
                    elif result.get("response") == "3DS_REQUIRED":
                        result["response"] = "3DS_REQUIRED"
                    elif result.get("response") == "CCN LIVE" or result.get("response") == "CCN_LIVE":
                        result["response"] = "CCN LIVE"
                    else:
                        result["response"] = result.get("response", "DECLINED")
                    
                    return card, result
                    
                except Exception as e:
                    return card, {
                        "response": "ERROR",
                        "message": f"Error: {str(e)[:50]}",
                        "site": "Stripe Auth"  # Generic, site name never shown to users
                    }
        
        # Create tasks for parallel processing (33 threads)
        mau_stop_requested[user_id] = False
        tasks = [check_one_card(card) for card in normalized_cards]
        
        # Process results as they complete
        for task_coro in asyncio.as_completed(tasks):
            if mau_stop_requested.get(user_id):
                stopped = True
                break
            
            try:
                card_used, result = await task_coro
            except Exception as e:
                card_used = "UNKNOWN"
                result = {"response": "ERROR", "message": str(e)[:50], "site": "Stripe Auth"}  # Generic, site name never shown
            
            processed_count += 1
            
            # Determine status based on gate
            if gate_key == "nomade":
                status = determine_nomade_status(result)
            elif gate_key == "starr":
                status = determine_starr_status(result)
            else:
                status = determine_nomade_status(result)
            
            response = result.get("response", "UNKNOWN")
            message_text = result.get("message", "Unknown")
            # site variable not used - URLs never shown (anime character used)
            
            # Update statistics - handle 3DS_REQUIRED as CCN Live
            if status == "APPROVED":
                header = "APPROVED"
                status_text = "Approved ✅"
                approved_count += 1
                is_hit = True
            elif status == "3DS_REQUIRED":
                header = "CCN LIVE"
                status_text = "3DS Required ✅"
                ccn_live_count += 1
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
                cc_num = card_used.split("|")[0] if "|" in card_used else card_used
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
                # Use random anime character name instead of site name
                anime_name = random.choice(ANIME_CHARACTERS)
                
                hit_message = f"""<b>[#StripeAuth] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card_used}</code>
<b>[•] Gateway:</b> <code>Stripe Auth [{anime_name}]</code>
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
                await _edit_progress(force=True)
            
            # Update progress
            is_last = processed_count == total_cc
            await _edit_progress(force=is_last)

        end_time = time.time()
        timetaken = round(end_time - start_time, 2)
        
        # Deduct credits
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit_bulk, user_id, len(all_cards))
        
        # Final message
        current_time = datetime.now().strftime("%I:%M %p")
        rate_final = (processed_count / timetaken) if timetaken > 0 else 0
        header = "<pre>⏹ Stopped by user</pre>" if stopped else "<pre>✦ Stripe Auth Check Completed</pre>"
        
        completion_message = f"""{header}
━━━━━━━━━━━━━━━
<b>[⚬] Gate:</b> <code>{gate_label}</code>
<b>[⚬] Mode:</b> <code>Parallel (33 threads)</code>
🟢 <b>Total CC</b>     : <code>{total_cc}</code>
💬 <b>Progress</b>    : <code>{processed_count}/{total_cc}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
⚡ <b>CCN Live</b>    : <code>{ccn_live_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
━━━━━━━━━━━━━━━
⏱️ <b>Time</b> : <code>{timetaken:.1f}s</code> · <code>{rate_final:.1f} cc/s</code>
👤 <b>Checked By</b> : {checked_by} [<code>{plan} {badge}</code>]
🔧 <b>Dev</b>: <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>
━━━━━━━━━━━━━━━"""
        
        try:
            await loader_msg.edit(
                completion_message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=None,
            )
        except:
            pass

    except Exception as e:
        await message.reply(f"⚠️ Error: {e}", reply_to_message_id=message.id)
    
    finally:
        user_locks.pop(user_id, None)
        mau_stop_requested.pop(user_id, None)


@Client.on_callback_query(filters.regex(r"^mau_stop_(\d+)$"))
async def mau_stop_callback(client: Client, cq):
    """Stop a running /mau check. Only the user who started it can stop."""
    try:
        if not cq.from_user:
            await cq.answer("Invalid request.", show_alert=True)
            return
        uid = cq.matches[0].group(1) if cq.matches else None
        if not uid or str(cq.from_user.id) != uid:
            await cq.answer("You can only stop your own check.", show_alert=True)
            return
        mau_stop_requested[uid] = True
        try:
            await cq.message.edit_text(
                "<pre>⏹ Stopping... Please wait.</pre>\n\n"
                "━━━━━━━━━━━━━━━\n"
                "The check will stop after the current cards finish.",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except Exception:
            pass
        await cq.answer("Stop requested. Stopping after current cards…")
    except Exception:
        await cq.answer("Could not process.", show_alert=True)
