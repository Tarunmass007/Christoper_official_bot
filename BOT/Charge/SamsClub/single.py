"""
Sam's Club Plus Membership Gate Handler
/yo cc|mm|yyyy|cvv - 8 concurrent runners, professional terminal-style output
"""

import re
import time
import json
from io import BytesIO
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode

from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.Charge.SamsClub.api import async_samsclub_check
from BOT.gc.credit import has_credits, deduct_credit

try:
    from TOOLS.getbin import get_bin_details
except ImportError:

    def get_bin_details(_):
        return None

# Store raw responses for /yo check complete result button
_yo_raw_store = {}


def _build_yo_result_txt(check_id: str) -> str:
    """Build full debug .txt content from stored raw responses."""
    data = _yo_raw_store.get(check_id)
    if not data:
        return "Result expired or not found. Run /yo again."
    card = data.get("card", "")
    raw_list = data.get("raw_responses", [])
    lines = [
        "=" * 80,
        "SAM'S CLUB PLUS - FULL CHECK RESULT (DEBUG)",
        "=" * 80,
        f"Card: {card}",
        f"Timestamp: {data.get('timestamp', 'N/A')}",
        "=" * 80,
        "",
    ]
    for i, raw in enumerate(raw_list, 1):
        lines.append(f"--- PROCESS {i} ---")
        if isinstance(raw, dict):
            if "error" in raw:
                lines.append(f"Error: {raw['error']}")
            else:
                lines.append(f"Status Code: {raw.get('status_code', 'N/A')}")
                lines.append(f"Success: {raw.get('success', False)}")
                resp = raw.get("response_raw", "")
                if resp:
                    lines.append("Raw Response:")
                    lines.append(resp)
                rj = raw.get("response_json")
                if rj is not None:
                    lines.append("")
                    lines.append("Parsed JSON:")
                    try:
                        lines.append(json.dumps(rj, indent=2))
                    except Exception:
                        lines.append(str(rj))
        else:
            lines.append(str(raw))
        lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)


def extract_card(text: str):
    """Extract card in format cc|mm|yy|cvv or cc|mm|yyyy|cvv"""
    match = re.search(r"(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})", text)
    if match:
        cc, mes, ano, cvv = match.groups()
        if len(ano) == 2:
            ano = f"20{ano}"
        return cc, mes, ano, cvv
    return None


@Client.on_message(filters.command(["yo"]) | filters.regex(r"^\$yo(\s|$)"))
async def handle_yo_command(client: Client, message: Message):
    """
    Handle /yo command - Sam's Club Plus Membership gate.
    Usage: /yo cc|mm|yyyy|cvv
    Runs 8 concurrent checks, terminal-style output.
    """
    try:
        if not message.from_user:
            return

        users = load_users()
        user_id = str(message.from_user.id)

        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )

        if not await check_private_access(message):
            return

        if not await is_premium_user(message):
            return

        if not has_credits(user_id):
            return await message.reply(
                """<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
<b>Get Credits To Use</b>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif message.text and len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                """<pre>CC Not Found ❌</pre>
<b>Error:</b> <code>No CC Found in your input</code>
<b>Usage:</b> <code>/yo cc|mm|yyyy|cvv</code>
<b>Example:</b> <code>/yo 4833169815987902|06|2028|936</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )

        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                """<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Send CC in Correct Format</code>
<b>Usage:</b> <code>/yo cc|mm|yyyy|cvv</code>
<b>Example:</b> <code>/yo 4833169815987902|06|2028|936</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )

        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            return await message.reply(
                f"""<pre>Antispam Detected ⚠️</pre>
<b>Message:</b> <code>You are detected as spamming</code>
<code>Try after {wait_time}s to use me again</code> <b>OR</b>
<code>Reduce Antispam Time /buy Using Paid Plan</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
            )

        cc, mes, ano, cvv = extracted
        fullcc = f"{cc}|{mes}|{ano}|{cvv}"

        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        loading_msg = await message.reply(
            f"""<pre>✦ Sam's Club Plus Membership Check</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[⚬] Card:</b> <code>{fullcc}</code>
<b>[⚬] Gate:</b> <code>Sam's Club Plus $110</code>
<b>[⚬] Runners:</b> <code>8 concurrent</code>
<b>[⚬] Status:</b> <code>Fetching PIE keys...</code>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )

        start_time = time.time()

        try:
            await loading_msg.edit(
                f"""<pre>✦ Sam's Club Plus Membership Check</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[⚬] Card:</b> <code>{fullcc}</code>
<b>[⚬] Gate:</b> <code>Sam's Club Plus $110</code>
<b>[⚬] Status:</b> <code>Running 8 concurrent checks...</code>""",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        result = await async_samsclub_check(fullcc)

        time_taken = round(time.time() - start_time, 2)
        results = result.get("results", [])
        raw_responses = result.get("raw_responses", [])

        check_id = f"yo_{user_id}_{int(time.time() * 1000)}"
        _yo_raw_store[check_id] = {
            "card": fullcc,
            "raw_responses": raw_responses,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
        approved_count = result.get("approved_count", 0)
        declined_count = result.get("declined_count", 0)
        error_count = result.get("error_count", 0)

        if approved_count > 0:
            header = "APPROVED"
            status_icon = "✓✓✓"
        elif declined_count >= 4:
            header = "DECLINED"
            status_icon = "✗"
        else:
            header = "MIXED"
            status_icon = "?"

        bin_data = get_bin_details(cc[:6]) if get_bin_details else None
        if bin_data:
            vendor = bin_data.get("vendor", "N/A")
            card_type = bin_data.get("type", "N/A")
            bank = bin_data.get("bank", "N/A")
            country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '🏳️')}"
        else:
            vendor = card_type = bank = "N/A"
            country = "N/A 🏳️"

        results_block = "\n".join(f"<code>• {r}</code>" for r in results[:12])

        final_msg = f"""<b>[#Sam's Club] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>Sam's Club Plus $110</code>
<b>[•] Status:</b> <code>{status_icon} {approved_count}/8 Approved | {declined_count} Declined | {error_count} Errors</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>RESULTS (8 concurrent):</b>
{results_block}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{cc[:6]}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code> | <b>Runners:</b> <code>8</code>"""

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Check Complete Result (.txt)", callback_data=f"yo_full_{check_id}"),
            ],
            [
                InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                InlineKeyboardButton("Plans", callback_data="plans_info"),
            ],
        ])

        await loading_msg.edit(
            final_msg,
            reply_markup=buttons,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML,
        )

        success, _ = deduct_credit(user_id)
        if not success:
            print(f"Credit deduction failed for user {user_id}")

    except Exception as e:
        print(f"Error in /yo: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(
            "<code>Internal Error Occurred. Try again later.</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )


@Client.on_callback_query(filters.regex(r"^yo_full_"))
async def yo_full_result_callback(client: Client, callback: CallbackQuery):
    """Send full raw response as .txt for debugging when user clicks Check Complete Result."""
    try:
        check_id = callback.data.replace("yo_full_", "", 1)
        if not check_id:
            await callback.answer("Invalid request", show_alert=True)
            return
        txt = _build_yo_result_txt(check_id)
        filename = f"samsclub_yo_result_{check_id}.txt"
        bio = BytesIO(txt.encode("utf-8"))
        bio.name = filename
        await callback.message.reply_document(
            document=bio,
            caption="<code>/yo</code> check complete result – raw API response for debugging",
            parse_mode=ParseMode.HTML,
        )
        await callback.answer("Result sent as .txt")
    except Exception as e:
        await callback.answer(f"Error: {str(e)[:50]}", show_alert=True)
