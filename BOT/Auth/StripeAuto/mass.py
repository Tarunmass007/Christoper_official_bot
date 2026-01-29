"""
Stripe Auto Auth - Mass Check (/mstarr)
=======================================
Mass card check with asyncio concurrency. Threads = sites * 15, capped by card count.
Uses random saved site per card. Approved/CCN live sent as separate messages (same as /msh and /mau).
"""

import re
import random
import asyncio
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.gc.credit import deduct_credit_bulk, has_credits
from BOT.db.store import get_stripe_auth_sites
from BOT.tools.proxy import get_rotating_proxy
from BOT.Auth.StripeAuto.api import auto_stripe_auth
from BOT.Auth.StripeAuto.response import determine_stripe_auto_status

try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(_):
        return None

user_locks = {}
CONCURRENCY_PER_SITE = 15  # max concurrent tasks per saved site

def extract_cards(text: str):
    return re.findall(r"(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})", text)


@Client.on_message(filters.command(["mstarr", "mstripeauto"]) | filters.regex(r"^\$mstarr(\s|$)"))
async def handle_mstarr_command(client: Client, message):
    """Mass Stripe Auto Auth. Uses site from /sturl. Reply to message with cards or paste after command."""
    if not message.from_user:
        return
    user_id = str(message.from_user.id)
    if user_id in user_locks:
        await message.reply(
            "<pre>⚠️ Wait!</pre>\n<b>Previous</b> <code>/mstarr</code> <b>still processing.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
        return
    user_locks[user_id] = True
    try:
        users = load_users()
        if user_id not in users:
            user_locks.pop(user_id, None)
            return await message.reply(
                "<pre>Access Denied 🚫</pre>\n<b>Register first:</b> <code>/register</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        if not await is_premium_user(message):
            user_locks.pop(user_id, None)
            return
        if not await check_private_access(message):
            user_locks.pop(user_id, None)
            return
        sites = get_stripe_auth_sites(user_id)
        if not sites or not isinstance(sites, list):
            user_locks.pop(user_id, None)
            return await message.reply(
                "<pre>No Stripe Auth Site ❌</pre>\n<b>Add first:</b> <code>/sturl https://yoursite.com</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len((message.text or "").split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
        if not target_text:
            user_locks.pop(user_id, None)
            return await message.reply(
                "<pre>No cards ❌</pre>\nReply to a message with cards or paste after <code>/mstarr</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        all_cards = extract_cards(target_text)
        if not all_cards:
            user_locks.pop(user_id, None)
            return await message.reply("❌ No valid cards (cc|mm|yy|cvv).", reply_to_message_id=message.id)
        mlimit = int(users.get(user_id, {}).get("plan", {}).get("mlimit", 50) or 50)
        if len(all_cards) > mlimit:
            user_locks.pop(user_id, None)
            return await message.reply(
                f"❌ Max <code>{mlimit}</code> cards per run (plan limit).",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        proxy = get_rotating_proxy(int(user_id))
        total = len(all_cards)
        sites_list = [
            s.get("url", "") if isinstance(s, dict) else str(s)
            for s in sites
            if (s.get("url") if isinstance(s, dict) else str(s))
        ]
        if not sites_list:
            user_locks.pop(user_id, None)
            return await message.reply(
                "<pre>No valid site URL ❌</pre>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        # Concurrency: sites * 15 threads, capped by card count — no blank requests
        max_concurrent = min(len(sites_list) * CONCURRENCY_PER_SITE, total)
        semaphore = asyncio.Semaphore(max_concurrent)
        site_label = f"{len(sites_list)} site(s)" if len(sites_list) > 1 else (sites_list[0][:35] if sites_list else "")
        status_msg = await message.reply(
            f"<pre>Stripe Auto Mass ◐</pre>\n<b>Cards:</b> <code>{total}</code>\n<b>Sites:</b> <code>{site_label}...</code>\n<b>Threads:</b> <code>{max_concurrent}</code>\n<b>Status:</b> <i>Processing...</i>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🧿")
        checked_by = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name or 'User'}</a>" if message.from_user else "User"

        async def process_one(card: str, site_url: str, index: int):
            async with semaphore:
                try:
                    res = await auto_stripe_auth(site_url, card, session=None, proxy=proxy, timeout_seconds=45)
                    status = determine_stripe_auto_status(res)
                    return (index, card, status, res)
                except Exception as e:
                    return (index, card, "ERROR", {"message": str(e)[:80]})

        def build_hit_message(card: str, status: str, res: dict) -> str:
            header = "APPROVED" if status == "APPROVED" else "CCN LIVE"
            status_text = "Stripe Auth 0.0$ ✅" if status == "APPROVED" else "CCN Live ⚡"
            cc_num = card.split("|")[0] if "|" in card else card
            try:
                bin_data = get_bin_details(cc_num[:6]) if get_bin_details else None
                if bin_data:
                    vendor = bin_data.get("vendor", "N/A")
                    card_type = bin_data.get("type", "N/A")
                    bank = bin_data.get("bank", "N/A")
                    country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                else:
                    vendor = card_type = bank = country = "N/A"
            except Exception:
                vendor = card_type = bank = country = "N/A"
            msg_display = (res.get("message") or "")[:80] if isinstance(res.get("message"), str) else "N/A"
            return f"""<b>[#StripeAuto] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card}</code>
<b>[•] Gateway:</b> <code>Stripe Auth</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{msg_display}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{cc_num[:6]}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━"""

        start_time = time()
        # One task per card; each card gets a random saved site — no blank requests
        tasks = [
            process_one(card, random.choice(sites_list), i)
            for i, card in enumerate(all_cards)
        ]
        done_count = 0
        approved_count = 0
        ccn_count = 0
        declined_count = 0
        for coro in asyncio.as_completed(tasks):
            try:
                index, card, status, res = await coro
            except Exception:
                done_count += 1
                if done_count % 5 == 0 or done_count == total:
                    try:
                        await status_msg.edit_text(
                            f"<pre>Stripe Auto Mass ◐</pre>\n<b>Cards:</b> <code>{total}</code>\n<b>Done:</b> <code>{done_count}/{total}</code>\n<b>✅ Approved:</b> <code>{approved_count}</code> <b>⚡ CCN:</b> <code>{ccn_count}</code>\n<b>Status:</b> <i>Processing...</i>",
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception:
                        pass
                continue
            done_count += 1
            if status == "APPROVED":
                approved_count += 1
            elif status == "CCN LIVE":
                ccn_count += 1
            elif status == "DECLINED":
                declined_count += 1
            if status in ("APPROVED", "CCN LIVE"):
                try:
                    hit_message = build_hit_message(card, status, res)
                    await message.reply(hit_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    pass
            if done_count % 5 == 0 or done_count == total:
                try:
                    await status_msg.edit_text(
                        f"<pre>Stripe Auto Mass ◐</pre>\n<b>Cards:</b> <code>{total}</code>\n<b>Done:</b> <code>{done_count}/{total}</code>\n<b>✅ Approved:</b> <code>{approved_count}</code> <b>⚡ CCN:</b> <code>{ccn_count}</code>\n<b>Status:</b> <i>Processing...</i>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass

        time_taken = round(time() - start_time, 2)
        err_count = total - approved_count - ccn_count - declined_count
        current_time = datetime.now().strftime("%I:%M %p")

        completion_message = f"""<pre>✦ Stripe Auto Check Completed</pre>
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{total}</code>
💬 <b>Progress</b>    : <code>{done_count}/{total}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
⚡ <b>CCN Live</b>    : <code>{ccn_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{err_count}</code>
━━━━━━━━━━━━━
⏱️ <b>Time Elapsed</b> : <code>{time_taken}s</code>
👤 <b>Checked By</b> : {checked_by} [<code>{plan} {badge}</code>]
🔧 <b>Dev</b>: <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>
━━━━━━━━━━━━━"""

        await status_msg.edit_text(
            completion_message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        deduct_credit_bulk(user_id, total)
    except Exception as e:
        try:
            await message.reply(f"<pre>Error ⚠️</pre>\n<code>{str(e)[:100]}</code>", reply_to_message_id=message.id, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    finally:
        user_locks.pop(user_id, None)
