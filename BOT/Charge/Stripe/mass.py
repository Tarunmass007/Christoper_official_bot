import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from BOT.db.store import get_user_id
from BOT.tools.bin import get_bin_details
from BOT.Auth.StripeAuth.worker_api import async_stripe_auth
from .charge_api import async_stripe_charge

temp_cards = {}  # Temporary storage; use MongoDB in production

@Client.on_message(filters.command("msc"))
async def handle_mass_stripe(client, message):
    user_id = get_user_id(message.from_user.id)
    cards_text = message.text.split(" ", 1)[1] if len(message.text.split()) > 1 else None
    if not cards_text:
        await message.reply("Usage: /msc cc|mm|yy|cvc\ncc|mm|yy|cvc\n...")
        return
    cards = cards_text.strip().split("\n")

    # Prompt gate selection
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Stripe Auth", callback_data=f"mass_auth:{user_id}"),
         InlineKeyboardButton("Stripe Charge", callback_data=f"mass_charge:{user_id}")],
        [InlineKeyboardButton("Stop", callback_data=f"stop_mass:{user_id}")]
    ])
    msg = await message.reply("Select which gate:", reply_markup=keyboard)

    temp_cards[user_id] = cards

@Client.on_callback_query(filters.regex(r"^(mass_auth|mass_charge|stop_mass):"))
async def handle_mass_gate(client, callback: CallbackQuery):
    data = callback.data.split(":")
    action = data[0]
    user_id = int(data[1])

    if action == "stop_mass":
        temp_cards.pop(user_id, None)
        await callback.message.edit_text("Mass check stopped.")
        return

    gate = action.split("_")[1]
    cards = temp_cards.pop(user_id, [])
    if not cards:
        await callback.answer("No cards found.")
        return

    results = await asyncio.gather(*[process_card(card, gate) for card in cards])

    response = "\n\n".join([format_mass_result(res, card, gate) for res, card in zip(results, cards)])
    await callback.message.edit_text(response)
    await callback.answer("Mass check completed!")

async def process_card(card, gate):
    if gate == "auth":
        return await async_stripe_auth(card)
    elif gate == "charge":
        return await async_stripe_charge(card)

def format_mass_result(result, card, gate):
    bin_details = get_bin_details(card[:6])  # Sync for simplicity
    return format_response(result, card, bin_details, gate)  # Reuse from single.py