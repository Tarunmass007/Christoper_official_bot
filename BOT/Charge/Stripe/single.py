import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from BOT.db.store import get_user_id  # Assuming this exists for user ID
from BOT.tools.bin import get_bin_details
from BOT.Auth.StripeAuth.worker_api import async_stripe_auth  # Existing auth function
from .charge_api import async_stripe_charge  # New charge function

@Client.on_message(filters.command("sc"))
async def handle_single_stripe(client, message):
    user_id = get_user_id(message.from_user.id)
    card = message.text.split(" ", 1)[1] if len(message.text.split()) > 1 else None
    if not card:
        await message.reply("Usage: /sc cc|mm|yy|cvc")
        return

    # Prompt gate selection
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Stripe Auth", callback_data=f"gate_auth:{card}:{user_id}"),
         InlineKeyboardButton("Stripe Charge", callback_data=f"gate_charge:{card}:{user_id}")]
    ])
    await message.reply("Select which gate:", reply_markup=keyboard)

@Client.on_callback_query(filters.regex(r"^gate_(auth|charge):"))
async def handle_gate_selection(client, callback: CallbackQuery):
    data = callback.data.split(":")
    gate = data[0].split("_")[1]
    card = data[1]
    user_id = int(data[2])

    if gate == "auth":
        result = await async_stripe_auth(card)  # Route to existing auth
    elif gate == "charge":
        result = await async_stripe_charge(card)  # Route to new charge

    bin_details = await get_bin_details(card[:6])
    response_text = format_response(result, card, bin_details, gate.upper())  # Assuming format function
    await callback.message.edit_text(response_text)
    await callback.answer("Gate selected and processed!")

def format_response(result, card, bin_details, gate):
    status = "Charged ✅" if result['status'] == 'charged' else "Declined ❌" if result['status'] == 'declined' else "Error ⚠️"
    return f"""
[#Stripe{gate}] | {status} ✦
━━━━━━━━━━━━━━━
[•] Card: {card}
[•] Gateway: Stripe {gate}
[•] Status: {status}
[•] Response: {result['message']}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
[+] BIN: {bin_details['bin']}
[+] Info: {bin_details['vendor']} - {bin_details['type']} - {bin_details['level']}
[+] Bank: {bin_details['bank']} 🏦
[+] Country: {bin_details['country']} {bin_details['flag']}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
[ﾒ] Checked By: @{callback.from_user.username} [Pro]
[ϟ] Dev: Chr1shtopher
━━━━━━━━━━━━━━━
"""