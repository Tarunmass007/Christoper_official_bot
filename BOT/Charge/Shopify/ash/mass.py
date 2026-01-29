import re
import time
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access
from BOT.Charge.Shopify.ash.api import check_autoshopify
from BOT.Charge.Shopify.ash.response import format_mass_response
from BOT.gc.credit import deduct_credit_bulk

# User locks to prevent multiple mass checks
user_locks = {}

def extract_cards(text):
    """Extract all cards from text in format cc|mm|yy|cvv"""
    return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)

def chunk_cards(cards, size):
    """Chunk cards into batches"""
    for i in range(0, len(cards), size):
        yield cards[i:i + size]

@Client.on_message(filters.command(["mautosh_disabled", "mash_disabled"]))
async def handle_mass_autosh(client, message):
    """
    Handle /mautosh command for mass AutoShopify card checking

    Usage: /mautosh <cards in format cc|mm|yy|cvv>
           Reply to a message with cards
    """
    user_id = str(message.from_user.id)

    try:
        # Check if user has ongoing mass check
        if user_id in user_locks:
            return await message.reply(
                "<pre>⚠️ Wait!</pre>\n"
                "<b>Your previous</b> <code>/mautosh</code> <b>request is still processing.</b>\n"
                "<b>Please wait until it finishes.</b>",
                reply_to_message_id=message.id
            )

        user_locks[user_id] = True

        # Load users and check registration
        users = load_users()

        if user_id not in users:
            del user_locks[user_id]
            return await message.reply(
                "<pre>Access Denied 🚫</pre>\n"
                "<b>You have to register first using</b> <code>/register</code> <b>command.</b>",
                reply_to_message_id=message.id
            )

        # Check private access
        if not await check_private_access(message):
            del user_locks[user_id]
            return

        # Extract cards from command or replied message
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            del user_locks[user_id]
            return await message.reply(
                f"""<pre>Cards Not Found ❌</pre>
<b>Error:</b> <code>No cards found in your input</code>
<b>Usage:</b> <code>/mautosh cc|mm|yy|cvv</code>
<b>or reply to a message with cards</b>""",
                reply_to_message_id=message.id
            )

        cards = extract_cards(target_text)

        if not cards:
            del user_locks[user_id]
            return await message.reply(
                f"""<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>No valid cards found</code>
<b>Format:</b> <code>cc|mm|yy|cvv</code>""",
                reply_to_message_id=message.id
            )

        # Limit cards (max 50 for mass check)
        max_cards = 50
        if len(cards) > max_cards:
            cards = cards[:max_cards]
            await message.reply(
                f"<pre>⚠️ Card Limit</pre>\n"
                f"<b>Only checking first {max_cards} cards</b>"
            )

        # Calculate credits needed
        credits_needed = len(cards)

        # Show initial status
        loading_msg = await message.reply(
            f"<pre>Starting Mass Check..!</pre>\n"
            f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
            f"• <b>Total Cards:</b> <code>{len(cards)}</code>\n"
            f"• <b>Credits Needed:</b> <code>{credits_needed}</code>\n"
            f"• <b>Gate:</b> <code>AutoShopify</code>",
            reply_to_message_id=message.id
        )

        # Deduct credits first
        success, msg = deduct_credit_bulk(user_id, credits_needed)
        if not success:
            del user_locks[user_id]
            return await loading_msg.edit(
                f"""<pre>Insufficient Credits ❌</pre>
<b>Message:</b> <code>{msg}</code>
<b>Get Credits To Use</b>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>"""
            )

        start_time = time.time()
        results = []
        completed = 0

        # Process cards in batches of 5
        batch_size = 5

        for batch in chunk_cards(cards, batch_size):
            # Create tasks for batch
            tasks = [check_autoshopify(card) for card in batch]

            # Run batch concurrently
            batch_results = await asyncio.gather(*tasks)

            # Store results
            for card, result in zip(batch, batch_results):
                results.append((card, result))
                completed += 1

            # Update progress every batch
            progress = int((completed / len(cards)) * 100)
            await loading_msg.edit(
                f"<pre>Processing Cards..!</pre>\n"
                f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
                f"• <b>Progress:</b> <code>{completed}/{len(cards)}</code> ({progress}%)\n"
                f"• <b>Gate:</b> <code>AutoShopify</code>"
            )

            # Small delay between batches
            await asyncio.sleep(1)

        total_time = time.time() - start_time

        # Format and send final response
        user_info = {
            "name": message.from_user.first_name,
            "id": user_id
        }

        final_msg = format_mass_response(results, total_time, user_info)

        # Add buttons
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                InlineKeyboardButton("Plans", callback_data="plans_info")
            ]
        ])

        # Send final response
        await loading_msg.edit(
            final_msg,
            reply_markup=buttons,
            disable_web_page_preview=True
        )

    except Exception as e:
        print(f"Error in /mautosh: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(
            "<code>Internal Error Occurred. Try again later.</code>",
            reply_to_message_id=message.id
        )

    finally:
        # Always release the lock
        if user_id in user_locks:
            del user_locks[user_id]
