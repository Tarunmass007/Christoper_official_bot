"""
Stripe Auto Auth - Single Check (/starr)
========================================
Single card check across up to 15 saved Stripe Auth sites in parallel.
First definitive result (APPROVED / CCN LIVE / DECLINED) from any site is shown.
Reply to CC or /starr cc|mm|yy|cvv. Does NOT use /au, /mau gate.
"""

import asyncio
import re
from time import time

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.gc.credit import deduct_credit, has_credits
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
MAX_STARR_SITES = 15  # max parallel site threads for /starr

def extract_card(text: str):
    m = re.search(r"(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})", text)
    return m.groups() if m else None


def format_response(fullcc: str, result: dict, user_info: dict, time_taken: float) -> str:
    resp = result.get("response", "UNKNOWN")
    msg = result.get("message", "Unknown")[:80]
    status = determine_stripe_auto_status(result)
    if status == "APPROVED":
        header, status_text = "APPROVED", "Stripe Auth 0.0$ ✅"
    elif status == "CCN LIVE":
        header, status_text = "CCN LIVE", "CCN Live ⚡"
    elif status == "DECLINED":
        header, status_text = "DECLINED", "Declined ❌"
    else:
        header, status_text = "ERROR", "Error ⚠️"
    bin_data = get_bin_details(fullcc.split("|")[0][:6]) if get_bin_details else None
    if bin_data:
        vendor = bin_data.get("vendor", "N/A")
        card_type = bin_data.get("type", "N/A")
        bank = bin_data.get("bank", "N/A")
        country = bin_data.get("country", "N/A")
        flag = bin_data.get("flag", "🏳️")
    else:
        vendor = card_type = bank = country = "N/A"
        flag = "🏳️"
    return f"""<b>[#StripeAuto] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>Stripe Auth</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{msg}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{fullcc[:6]}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] By:</b> {user_info.get('profile', 'N/A')} [<code>{user_info.get('plan', '')} {user_info.get('badge', '')}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code>"""


@Client.on_message(filters.command(["starr", "stripeauto"]) | filters.regex(r"^\$starr(\s|$)"))
async def handle_starr_command(client: Client, message: Message):
    """Single Stripe Auto Auth check. Uses site from /sturl. Reply to CC or /starr cc|mm|yy|cvv."""
    if not message.from_user:
        return
    user_id = str(message.from_user.id)
    if user_id in user_locks:
        await message.reply(
            "<pre>⚠️ Wait!</pre>\n<b>Previous</b> <code>/starr</code> <b>still processing.</b>",
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
        if not has_credits(user_id):
            user_locks.pop(user_id, None)
            return await message.reply(
                "<pre>Insufficient Credits ❗</pre>\n<b>Use</b> <code>/buy</code>",
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
                "<pre>Card Not Found ❌</pre>\n<b>Usage:</b> <code>/starr cc|mm|yy|cvv</code> or reply to a message with card.",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        extracted = extract_card(target_text)
        if not extracted:
            user_locks.pop(user_id, None)
            return await message.reply(
                "<pre>Invalid Format ❌</pre>\n<b>Format:</b> <code>cc|mm|yy|cvv</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            user_locks.pop(user_id, None)
            return await message.reply(
                f"<pre>Antispam ⚠️</pre>\n<b>Wait</b> <code>{wait_time}s</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        sites = get_stripe_auth_sites(user_id)
        if not sites or not isinstance(sites, list):
            user_locks.pop(user_id, None)
            return await message.reply(
                "<pre>No Stripe Auth Site ❌</pre>\n<b>Add a site first:</b> <code>/sturl https://yoursite.com</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        sites_list = [
            (s.get("url") or str(s)).strip()
            for s in sites
            if (s.get("url") if isinstance(s, dict) else str(s))
        ]
        sites_list = [u for u in sites_list if u][:MAX_STARR_SITES]
        if not sites_list:
            user_locks.pop(user_id, None)
            return await message.reply(
                "<pre>No Stripe Auth Site ❌</pre>\n<b>Add a site first:</b> <code>/sturl https://yoursite.com</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )
        card_num, mm, yy, cvv = extracted
        if len(yy) == 2:
            yy = "20" + yy
        fullcc = f"{card_num}|{mm}|{yy}|{cvv}"
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🧿")
        profile = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        user_info = {"profile": profile, "plan": plan, "badge": badge}
        start_time = time()
        num_sites = len(sites_list)
        loading_msg = await message.reply(
            f"<pre>Stripe Auto Auth...</pre>\n<b>• Card:</b> <code>{fullcc}</code>\n<b>• Status:</b> <i>Checking across {num_sites} site(s)... ◐</i>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )

        async def check_one_site(site_url: str):
            proxy = get_rotating_proxy(int(user_id))
            return await auto_stripe_auth(site_url, fullcc, session=None, proxy=proxy, timeout_seconds=50)

        tasks = [asyncio.create_task(check_one_site(url)) for url in sites_list]
        result = None
        try:
            for done in asyncio.as_completed(tasks):
                res = await done
                status = determine_stripe_auto_status(res)
                if status in ("APPROVED", "CCN LIVE", "DECLINED"):
                    result = res
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    break
            if result is None:
                result = res
        except asyncio.CancelledError:
            pass
        for t in tasks:
            if not t.done():
                t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        time_taken = round(time() - start_time, 2)
        final_message = format_response(fullcc, result, user_info, time_taken)
        await loading_msg.edit(
            final_message,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"), InlineKeyboardButton("Plans", callback_data="plans_info")]
            ]),
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML,
        )
        deduct_credit(user_id)
    except Exception as e:
        try:
            await message.reply(f"<pre>Error ⚠️</pre>\n<code>{str(e)[:100]}</code>", reply_to_message_id=message.id, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    finally:
        user_locks.pop(user_id, None)
