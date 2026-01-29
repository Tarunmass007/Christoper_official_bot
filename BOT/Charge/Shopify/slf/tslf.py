# from pyrogram import Client, filters
# from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
# import os
# import json
# import time
# import asyncio
# import re
# from BOT.Charge.Shopify.slf.slf import check_card  # your check logic

# # Helper to load txtsite config
# def get_sites(user_id):
#     try:
#         with open("DATA/txtsite.json", "r") as f:
#             data = json.load(f)
#         site_list = data.get(str(user_id), [])
#         return [site["site"] for site in site_list if "site" in site]
#     except Exception:
#         return []

# # Card normalizer
# def extract_cards(text):
#     pattern = r'\b(?:\d{13,16})[|:/\\](\d{1,2})[|:/\\](\d{2,4})[|:/\\](\d{3,4})\b'
#     matches = re.findall(pattern, text)
#     normalized = []
#     for match in re.finditer(pattern, text):
#         raw = match.group()
#         parts = re.split(r"[|:/\\]", raw)
#         if len(parts) == 4:
#             cc, mm, yy, cvv = parts
#             yy = f"20{yy}" if len(yy) == 2 else yy
#             normalized.append(f"{cc}|{mm.zfill(2)}|{yy}|{cvv}")
#     return list(dict.fromkeys(normalized))

# # Global dict to track state
# user_state = {}

# @Client.on_message(filters.command("tslf") & filters.reply)
# async def tslf_handler(c: Client, m: Message):
#     user_id = str(m.from_user.id)
#     sites = get_sites(user_id)
#     if len(sites) < 2:
#         return await m.reply("<b>You need to add at least 2 sites using /txturl before using /tslf</b>")

#     if not m.reply_to_message.document:
#         return await m.reply("<b>Please reply to a text file (.txt) containing CCs.</b>")

#     file_path = await m.reply_to_message.download()
#     with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
#         content = f.read()
#     os.remove(file_path)

#     cards = extract_cards(content)
#     if not cards:
#         return await m.reply("<b>Invalid CC format detected in file.</b>")

#     state = {
#         "cards": cards,
#         "index": 0,
#         "charged": 0,
#         "live": 0,
#         "dead": 0,
#         "error": 0,
#         "start_time": time.time(),
#         "checked": 0,
#         "total": len(cards),
#         "site_index": 0,
#         "running": True,
#         "gate": sites[0]
#     }
#     user_state[user_id] = state

#     buttons = InlineKeyboardMarkup([
#         [InlineKeyboardButton("Confirm 🟢", callback_data=f"tslf_confirm:{user_id}"),
#          InlineKeyboardButton("End 🔴", callback_data=f"tslf_end:{user_id}")]
#     ])
#     msg = await m.reply(
#         f"<pre>Preparing For Check</pre>\n"
#         f"━━━━━━━━━━━━━\n"
#         f"⊙ <b>Total CC :</b> <code>{len(cards)}</code>\n"
#         f"⊙ <b>Gateway :</b> <code>{sites[0]}</code>\n"
#         f"━━━━━━━━━━━━━\n"
#         f"[ﾒ] <b>Checked By:</b> {m.from_user.mention}\n"
#         f"⌥ <b>Dev :</b> <code>private</code>",
#         reply_to_message_id=m.id,
#         reply_markup=buttons
#     )
#     user_state[user_id]["msg"] = msg


# @Client.on_callback_query(filters.regex(r"tslf_(confirm|end):(\d+)"))
# async def tslf_buttons(c: Client, cb: CallbackQuery):
#     action, uid = cb.data.split(":")
#     if cb.from_user.id != int(uid):
#         return await cb.answer("You are not authorized!", show_alert=True)

#     state = user_state.get(uid)
#     if not state:
#         return await cb.answer("Session expired.")

#     if action == "end":
#         state["running"] = False
#         await state["msg"].edit("<pre>Process Was End By User ⛔️</pre>")
#         return await cb.answer("Process Ended ⛔️", show_alert=True)

#     await cb.answer("Started Checking...", show_alert=True)
#     await start_check(c, cb.message, cb.from_user, state)


# async def start_check(c, msg, user, state):
#     start = time.time()

#     buttons = InlineKeyboardMarkup([
#         [InlineKeyboardButton("Shift Site", callback_data=f"tslf_shift:{user.id}"),
#          InlineKeyboardButton("3DS 🟢", callback_data="noop")],
#         [InlineKeyboardButton("Close", callback_data=f"tslf_end:{user.id}")]
#     ])

#     while state["index"] < state["total"] and state["running"]:
#         cc = state["cards"][state["index"]]
#         elapsed = time.time() - state["start_time"]

#         await msg.edit(
#             f"<pre>Started Checking</pre>\n"
#             f"━━━━━━━━━━━━━\n"
#             f"• <b>Card:</b> <code>{cc}</code>\n"
#             f"• <b>Response:</b> <code>Processing..!</code>\n"
#             f"⛶ <b>Charged:</b> <code>{state['charged']}</code>\n"
#             f"⎔ <b>Live:</b> <code>{state['live']}</code>\n"
#             f"⌀ <b>Dead:</b> <code>{state['dead']}</code>\n"
#             f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
#             f"<b>[⌁] Error:</b> <code>{state['error']}</code>\n"
#             f"<b>[⌁] Total Checked:</b> {state['index']+1}/{state['total']}\n"
#             f"━━━━━━━━━━━━━\n"
#             f"[ϟ] T/t: <code>{elapsed:.2f}s</code>\n"
#             f"[ϟ] Checked By: {user.mention}",
#             reply_markup=buttons
#         )

#         response = await check_card(user.id, cc)
#         status_flag = "Declined ❌"
#         raw = response

#         if "ORDER_PLACED" in response:
#             status_flag = "Charged 💎"
#             state["charged"] += 1
#         elif any(x in response for x in [
#             "3D CC", "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP", "INSUFFICIENT_FUNDS",
#             "INVALID_CVC", "INCORRECT_CVC", "3DS_REQUIRED", "MISMATCHED_BILL", "3D_AUTHENTICATION",
#             "INCORRECT_ZIP", "INCORRECT_ADDRESS"
#         ]):
#             status_flag = "Approved ❎"
#             state["live"] += 1
#         elif "Declined" in response:
#             state["error"] += 1
#         else:
#             state["dead"] += 1

#         elapsed = time.time() - start
#         await msg.edit(
#             f"<pre>Started Checking</pre>\n"
#             f"━━━━━━━━━━━━━\n"
#             f"• <b>Card:</b> <code>{cc}</code>\n"
#             f"• <b>Response:</b> <code>{raw}</code>\n"
#             f"⛶ <b>Charged:</b> <code>{state['charged']}</code>\n"
#             f"⎔ <b>Live:</b> <code>{state['live']}</code>\n"
#             f"⌀ <b>Dead:</b> <code>{state['dead']}</code>\n"
#             f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
#             f"<b>[⌁] Error:</b> <code>{state['error']}</code>\n"
#             f"<b>[⌁] Total Checked:</b> {state['index']+1}/{state['total']}\n"
#             f"━━━━━━━━━━━━━\n"
#             f"[ϟ] T/t: <code>{elapsed:.2f}s</code>\n"
#             f"[ϟ] Checked By: {user.mention}",
#             reply_markup=buttons
#         )

#         # Broadcast if status_flag is Approved or Charged
#         if status_flag in ["Approved ❎", "Charged 💎"]:
#             await c.send_message(
#                 msg.chat.id,
#                 f"<b>#AutoShopify | Christopher ✦[SELF TEXT]</b>\n"
#                 f"━━━━━━━━━━━━━\n"
#                 f"<b>⌁ Card:</b> <code>{cc}</code>\n"
#                 f"<b>⌁ Status:</b> <code>{status_flag}</code>\n"
#                 f"<b>⌁Response:</b> <code>{raw}</code>\n"
#                 f"<b>⌁ Gateway:</b> <code>{state['gate']}</code>\n"
#                 f"━━━━━━━━━━━━━\n"
#                 f"[•] Checked By: {user.mention}\n"
#                 f"[•] T/t: <code>{elapsed:.2f}</code> | P/x: <code>[Live👌🏻]</code>"
#             )

#         state["index"] += 1
#         await asyncio.sleep(0.5)  # for rate limiting

#     if state["index"] >= state["total"]:
#         await msg.edit("<b>✅ All Cards Checked</b>", reply_markup=None)
#         user_state.pop(str(user.id), None)


# # Optional: Shift Site
# @Client.on_callback_query(filters.regex(r"tslf_shift:(\d+)"))
# async def shift_site(c: Client, cb: CallbackQuery):
#     uid = cb.matches[0].group(1)
#     if cb.from_user.id != int(uid):
#         return await cb.answer("Unauthorized!", show_alert=True)

#     state = user_state.get(uid)
#     if not state:
#         return await cb.answer("Session expired", show_alert=True)

#     state["site_index"] = (state["site_index"] + 1) % len(get_sites(uid))
#     state["gate"] = get_sites(uid)[state["site_index"]]
#     await cb.answer(f"Shifted to: {state['gate']}", show_alert=True)

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import os
import json
import time
import asyncio
import re
from BOT.Charge.Shopify.slf.slf import check_card  # your check logic

from BOT.Charge.Shopify.slf.site_manager import get_user_sites


def get_sites(user_id):
    sites = get_user_sites(str(user_id))
    return [s.get("url", "") for s in sites if s.get("url")]


def get_user_site_info(user_id):
    """Return sites as [{site, gate}, ...] for tslf compatibility."""
    sites = get_user_sites(str(user_id))
    return [{"site": s.get("url", ""), "gate": s.get("gateway", "Unknown")} for s in sites if s.get("url")]


def get_site_and_gate(user_id, index):
    sites = get_user_site_info(user_id)
    if not sites:
        return None, None
    item = sites[index % len(sites)]
    return item.get("site"), item.get("gate")


# Card normalizer
def extract_cards(text):
    pattern = r'\b(?:\d{13,16})[|:/\\](\d{1,2})[|:/\\](\d{2,4})[|:/\\](\d{3,4})\b'
    matches = re.findall(pattern, text)
    normalized = []
    for match in re.finditer(pattern, text):
        raw = match.group()
        parts = re.split(r"[|:/\\]", raw)
        if len(parts) == 4:
            cc, mm, yy, cvv = parts
            yy = f"20{yy}" if len(yy) == 2 else yy
            normalized.append(f"{cc}|{mm.zfill(2)}|{yy}|{cvv}")
    return list(dict.fromkeys(normalized))

# Global dict to track state
user_state = {}

@Client.on_message(filters.command("takshijbahvd") & filters.reply)
async def tslf_handler(c: Client, m: Message):
    user_id = str(m.from_user.id)
    sites = get_user_site_info(user_id)
    if len(sites) < 2:
        return await m.reply("<b>You need to add at least 2 sites using /txturl before using /tslf</b>")

    if not m.reply_to_message.document:
        return await m.reply("<b>Please reply to a text file (.txt) containing CCs.</b>")

    file_path = await m.reply_to_message.download()
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    os.remove(file_path)

    cards = extract_cards(content)
    if not cards:
        return await m.reply("<b>Invalid CC format detected in file.</b>")

    if len(cards) > 100:
        cards = cards[:100]
        await m.reply("<b>⚠️ Limit of 100 cards exceeded. Only the first 100 cards will be processed.</b>")

    site, gate = get_site_and_gate(user_id, 0)
    state = {
        "cards": cards,
        "index": 0,
        "charged": 0,
        "live": 0,
        "dead": 0,
        "error": 0,
        "start_time": time.time(),
        "checked": 0,
        "total": len(cards),
        "send_3ds_required": True,
        "site_index": 0,
        "running": False,
        "gate": gate,
        "site": site,
        "confirmed": False
    }
    user_state[user_id] = state

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Confirm 🟢", callback_data=f"tslf_confirm:{user_id}"),
         InlineKeyboardButton("End 🔴", callback_data=f"tslf_end:{user_id}")]
    ])
    msg = await m.reply(
        f"<pre>Preparing For Check</pre>\n"
        f"━━━━━━━━━━━━━\n"
        f"⊙ <b>Total CC :</b> <code>{len(cards)}</code>\n"
        f"⊙ <b>Gateway :</b> <code>{gate}</code>\n"
        f"⊙ <b>Site:</b> <code>{site}</code>\n"
        f"━━━━━━━━━━━━━\n"
        f"[ﾒ] <b>Checked By:</b> {m.from_user.mention}\n"
        f"⌥ <b>Dev :</b> <code>private</code>",
        reply_to_message_id=m.id,
        reply_markup=buttons
    )
    state["msg"] = msg


@Client.on_callback_query(filters.regex(r"tslf_confirm:(\d+)"))
async def tslf_confirm_button(c: Client, cb: CallbackQuery):
    uid = cb.matches[0].group(1)
    if cb.from_user.id != int(uid):
        return await cb.answer("You are not authorized!")

    state = user_state.get(uid)
    if not state or state.get("confirmed"):
        return await cb.answer("Session expired or already running.")

    state["running"] = True
    state["confirmed"] = True
    await cb.answer("Started Checking...")
    await start_check(c, cb.message, cb.from_user, state)


@Client.on_callback_query(filters.regex(r"tslf_end:(\d+)"))
async def tslf_end_button(c: Client, cb: CallbackQuery):
    uid = cb.matches[0].group(1)
    if cb.from_user.id != int(uid):
        return await cb.answer("You are not authorized!", show_alert=True)

    state = user_state.get(uid)
    if not state:
        return await cb.answer("Session expired!", show_alert=True)

    state["running"] = False
    if not state.get("confirmed"):
        await state["msg"].edit("<pre>Process Was Ended By User ⛔️</pre>", reply_markup=None)
    await cb.answer("Process Ended ⛔️")
    user_state.pop(uid, None)

async def start_check(c, msg, user, state):
    start = time.time()

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Shift Site", callback_data=f"tslf_shift:{user.id}"),
         InlineKeyboardButton(f"3DS {'🟢' if state['send_3ds_required'] else '🔴'}", callback_data=f"tslf_3ds_toggle:{user.id}")],
        [InlineKeyboardButton("Close", callback_data=f"tslf_close:{user.id}")]
    ])

    # Show "Processing" status
    await msg.edit(
        f"<pre>Started Checking</pre>\n"
        f"━━━━━━━━━━━━━\n"
        f"• <b>Card:</b> <code>-</code>\n"
        f"• <b>Response:</b> <code>Processing..!</code>\n"
        f"⛶ <b>Charged:</b> <code>{state['charged']}</code>\n"
        f"⎔ <b>Live:</b> <code>{state['live']}</code>\n"
        f"⌀ <b>Dead:</b> <code>{state['dead']}</code>\n"
        f"<b>[⌁] Error:</b> <code>{state['error']}</code>\n"
        f"<b>[⌁] Total Checked:</b> {state['index']+1}/{state['total']}\n"
        f"━━━━━━━━━━━━━\n"
        f"[ϟ] T/t: <code>0.0s</code>\n"
        f"[ϟ] Checked By: {user.mention}",
        reply_markup=buttons
    )

    # while state["index"] < state["total"] and state["running"]:
    #     cc = state["cards"][state["index"]]
    #     card_start_time = time.time()
    #     max_attempts = len(get_user_site_info(str(user.id)))
    #     attempts = 0
    #     response = ""
    #     raw = ""
    #     while attempts < max_attempts:
    #         site = state["site"]
    #         response = await check_card(user.id, cc, site=site)  # <- Make sure `check_card` supports `site=`
    #         raw = response or "No response"

    #         # Check for captcha in response
    #         if any(x in raw.lower() for x in ["captcha", "hcaptcha", "recaptcha", "verify you are", "access denied"]):
    #             # Shift site
    #             user_sites = get_user_site_info(str(user.id))
    #             state["site_index"] = (state["site_index"] + 1) % len(user_sites)
    #             shifted_site = user_sites[state["site_index"]]
    #             state["site"] = shifted_site.get("site", state["site"])
    #             state["gate"] = shifted_site.get("gate", state["gate"])

    #             # Notify user
    #             await c.send_message(
    #                 msg.chat.id,
    #                 f"⚠️ <b>Captcha Detected</b>\n"
    #                 f"Shifting to next site:\n"
    #                 f"<b>Site:</b> <code>{state['site']}</code>\n"
    #                 f"<b>Gate:</b> <code>{state['gate']}</code>"
    #             )
    #             attempts += 1
    #             await asyncio.sleep(0.3)
    #             continue
    #         else:
    #             break  # Exit retry loop if no captcha
    while state["index"] < state["total"] and state["running"]:
        end_index = min(state["index"] + 5, state["total"])
        current_batch = state["cards"][state["index"]:end_index]

        for cc in current_batch:
            if not state["running"]:
                break

            card_start_time = time.time()
            max_attempts = len(get_user_site_info(str(user.id)))
            attempts = 0
            response = ""
            raw = ""

            while attempts < max_attempts:
                site = state["site"]
                response = await check_card(user.id, cc, site=site)
                raw = response or "No response"

                if any(x in raw.lower() for x in ["captcha", "hcaptcha", "recaptcha", "verify you are", "access denied"]):
                    user_sites = get_user_site_info(str(user.id))
                    state["site_index"] = (state["site_index"] + 1) % len(user_sites)
                    shifted_site = user_sites[state["site_index"]]
                    state["site"] = shifted_site.get("site", state["site"])
                    state["gate"] = shifted_site.get("gate", state["gate"])

                    await c.send_message(
                        msg.chat.id,
                        f"⚠️ <b>Captcha Detected</b>\n"
                        f"Shifting to next site:\n"
                        f"<b>Site:</b> <code>{state['site']}</code>\n"
                        f"<b>Gate:</b> <code>{state['gate']}</code>"
                    )
                    attempts += 1
                    await asyncio.sleep(0.3)
                    continue
                else:
                    break

    #     card_elapsed = time.time() - card_start_time
    #     status_flag = "Declined ❌"

        if "ORDER_PLACED" in response:
            status_flag = "Charged 💎"
            state["charged"] += 1
        elif any(x in response for x in [
            "3D CC", "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP", "INSUFFICIENT_FUNDS",
            "INVALID_CVC", "INCORRECT_CVC", "3DS_REQUIRED", "MISMATCHED_BILL", "3D_AUTHENTICATION",
            "INCORRECT_ZIP", "INCORRECT_ADDRESS"
        ]):
            status_flag = "Approved ❎"
    #         state["live"] += 1
    #     elif "Declined" in response:
    #         state["error"] += 1
    #     else:
    #         state["dead"] += 1

    #     # Update message
    #     await msg.edit(
    #         f"<pre>Started Checking</pre>\n"
    #         f"━━━━━━━━━━━━━\n"
    #         f"• <b>Card:</b> <code>{cc}</code>\n"
    #         f"• <b>Response:</b> <code>{raw}</code>\n"
    #         f"⛶ <b>Charged:</b> <code>{state['charged']}</code>\n"
    #         f"⎔ <b>Live:</b> <code>{state['live']}</code>\n"
    #         f"⌀ <b>Dead:</b> <code>{state['dead']}</code>\n"
    #         f"<b>[⌁] Error:</b> <code>{state['error']}</code>\n"
    #         f"<b>[⌁] Total Checked:</b> {state['index']+1}/{state['total']}\n"
    #         f"━━━━━━━━━━━━━\n"
    #         f"[ϟ] T/t: <code>{card_elapsed:.2f}s</code>\n"
    #         f"[ϟ] Checked By: {user.mention}",
    #         reply_markup=buttons
    #     )

    #     # Decide whether to broadcast or not based on 3DS toggle
    #     send_broadcast = False
    #     if status_flag == "Charged 💎":
    #         send_broadcast = True
    #     elif status_flag == "Approved ❎":
    #         if "3DS_REQUIRED" in response and not state.get("send_3ds_required", True):
    #             send_broadcast = False
    #         else:
    #             send_broadcast = True

    #     # Broadcast live/hits
    #     if send_broadcast:
    #         await c.send_message(
    #             msg.chat.id,
    #             f"<b>#AutoShopify | Christopher ✦[SELF TEXT]</b>\n"
    #             f"━━━━━━━━━━━━━\n"
    #             f"<b>⌁ Card:</b> <code>{cc}</code>\n"
    #             f"<b>⌁ Status:</b> <code>{status_flag}</code>\n"
    #             f"<b>⌁ Response:</b> <code>{raw}</code>\n"
    #             f"<b>⌁ Gateway:</b> <code>{state['gate']}</code>\n"
    #             f"━━━━━━━━━━━━━\n"
    #             f"[•] Checked By: {user.mention}\n"
    #             f"[•] T/t: <code>{card_elapsed:.2f}</code> | P/x: <code>[Live👌🏻]</code>"
    #         )

    #     state["index"] += 1
    #     await asyncio.sleep(0.5)

    # # Done checking
    # if state["index"] >= state["total"]:
    #     total_time = time.time() - start
    #     await msg.edit("<b>✅ All Cards Checked</b>", reply_markup=None)

    #     await c.send_message(
    #         msg.chat.id,
    #         f"<b>✅ Checking Finished</b>\n"
    #         f"━━━━━━━━━━━━━\n"
    #         f"⛶ <b>Charged:</b> <code>{state['charged']}</code>\n"
    #         f"⎔ <b>Live:</b> <code>{state['live']}</code>\n"
    #         f"⌀ <b>Dead:</b> <code>{state['dead']}</code>\n"
    #         f"<b>[⌁] Error:</b> <code>{state['error']}</code>\n"
    #         f"<b>[⌁] Total Checked:</b> <code>{state['total']}</code>\n"
    #         f"━━━━━━━━━━━━━\n"
    #         f"[ϟ] Time Taken: <code>{total_time:.2f}s</code>\n"
    #         f"[ϟ] Checked By: {user.mention}"
    #     )

        # Same post-processing
            card_elapsed = time.time() - card_start_time
            status_flag = "Declined ❌"

            if "ORDER_PLACED" in response:
                status_flag = "Charged 💎"
                state["charged"] += 1
            elif any(x in response for x in [
                "3D CC", "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP", "INSUFFICIENT_FUNDS",
                "INVALID_CVC", "INCORRECT_CVC", "3DS_REQUIRED", "MISMATCHED_BILL", "3D_AUTHENTICATION",
                "INCORRECT_ZIP", "INCORRECT_ADDRESS"
            ]):
                status_flag = "Approved ❎"
                state["live"] += 1
            elif "Declined" in response:
                state["error"] += 1
            else:
                state["dead"] += 1

            await msg.edit(
                f"<pre>Started Checking</pre>\n"
                f"━━━━━━━━━━━━━\n"
                f"• <b>Card:</b> <code>{cc}</code>\n"
                f"• <b>Response:</b> <code>{raw}</code>\n"
                f"⛶ <b>Charged:</b> <code>{state['charged']}</code>\n"
                f"⎔ <b>Live:</b> <code>{state['live']}</code>\n"
                f"⌀ <b>Dead:</b> <code>{state['dead']}</code>\n"
                f"<b>[⌁] Error:</b> <code>{state['error']}</code>\n"
                f"<b>[⌁] Total Checked:</b> {state['index']+1}/{state['total']}\n"
                f"━━━━━━━━━━━━━\n"
                f"[ϟ] T/t: <code>{card_elapsed:.2f}s</code>\n"
                f"[ϟ] Checked By: {user.mention}",
                reply_markup=buttons
            )

            send_broadcast = False
            if status_flag == "Charged 💎":
                send_broadcast = True
            elif status_flag == "Approved ❎":
                if "3DS_REQUIRED" in response and not state.get("send_3ds_required", True):
                    send_broadcast = False
                else:
                    send_broadcast = True

            if send_broadcast:
                await c.send_message(
                    msg.chat.id,
                    f"<b>#AutoShopify | Christopher ✦[SELF TEXT]</b>\n"
                    f"━━━━━━━━━━━━━\n"
                    f"<b>⌁ Card:</b> <code>{cc}</code>\n"
                    f"<b>⌁ Status:</b> <code>{status_flag}</code>\n"
                    f"<b>⌁ Response:</b> <code>{raw}</code>\n"
                    f"<b>⌁ Gateway:</b> <code>{state['gate']}</code>\n"
                    f"━━━━━━━━━━━━━\n"
                    f"[•] Checked By: {user.mention}\n"
                    f"[•] T/t: <code>{card_elapsed:.2f}</code> | P/x: <code>[Live👌🏻]</code>"
                )

            state["index"] += 1

        await asyncio.sleep(1)

    # Done checking - moved outside the while loop
    if state["index"] >= state["total"]:
        total_time = time.time() - start
        await msg.edit("<b>✅ All Cards Checked</b>", reply_markup=None)

        await c.send_message(
            msg.chat.id,
            f"<b>✅ Checking Finished</b>\n"
            f"━━━━━━━━━━━━━\n"
            f"⛶ <b>Charged:</b> <code>{state['charged']}</code>\n"
            f"⎔ <b>Live:</b> <code>{state['live']}</code>\n"
            f"⌀ <b>Dead:</b> <code>{state['dead']}</code>\n"
            f"<b>[⌁] Error:</b> <code>{state['error']}</code>\n"
            f"<b>[⌁] Total Checked:</b> <code>{state['total']}</code>\n"
            f"━━━━━━━━━━━━━\n"
            f"[ϟ] Time Taken: <code>{total_time:.2f}s</code>\n"
            f"[ϟ] Checked By: {user.mention}"
        )
        user_state.pop(str(user.id), None)

@Client.on_callback_query(filters.regex(r"tslf_3ds_toggle:(\d+)"))
async def tslf_toggle_3ds(c: Client, cb: CallbackQuery):
    uid = cb.matches[0].group(1)
    if cb.from_user.id != int(uid):
        return await cb.answer("Unauthorized!", show_alert=True)

    state = user_state.get(uid)
    if not state:
        return await cb.answer("Session expired!", show_alert=True)

    state["send_3ds_required"] = not state["send_3ds_required"]
    status = "enabled" if state["send_3ds_required"] else "disabled"
    await cb.answer(f"3DS_REQUIRED messages {status}.", show_alert=True)


@Client.on_callback_query(filters.regex(r"tslf_close:(\d+)"))
async def tslf_close_button(c: Client, cb: CallbackQuery):
    uid = cb.matches[0].group(1)
    if cb.from_user.id != int(uid):
        return await cb.answer("You are not authorized!", show_alert=True)

    state = user_state.get(uid)
    if not state:
        return await cb.answer("Session expired!", show_alert=True)

    state["running"] = False
    try:
        await state["msg"].delete()
    except Exception:
        pass

    await cb.message.reply("<pre>Process Was Ended By User ⛔️</pre>")
    await cb.answer("Process Ended ⛔️", show_alert=True)
    user_state.pop(uid, None)

# Optional: Shift Site
@Client.on_callback_query(filters.regex(r"tslf_shift:(\d+)"))
async def shift_site(c: Client, cb: CallbackQuery):
    uid = cb.matches[0].group(1)
    if cb.from_user.id != int(uid):
        return await cb.answer("Unauthorized!")

    state = user_state.get(uid)
    if not state:
        return await cb.answer("Session expired")

    user_sites = get_user_site_info(uid)
    if not user_sites:
        return await cb.answer("No URL found! Proceeding with existing URL(s)")

    # Shift to the next site
    state["site_index"] = (state["site_index"] + 1) % len(user_sites)
    next_site = user_sites[state["site_index"]]

    state["site"] = next_site.get("site", state["site"])
    state["gate"] = next_site.get("gate", state["gate"])

    await cb.answer(f"Shifted to:\nSite: {state['site']}\nGate: {state['gate']}", show_alert=True)
