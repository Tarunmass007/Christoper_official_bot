import time
import asyncio
from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.errors import FloodWait, UserIsBlocked, PeerIdInvalid, InputUserDeactivated, UserDeactivatedBan
from pyrogram.types import Message

from BOT.config_loader import get_config
from BOT.db.store import load_users as _load_users

config = get_config()
OWNER_ID = int(config.get("OWNER") or 0)


def load_users():
    return list(_load_users().keys())

broadcast_filter = filters.command("b") & filters.user(OWNER_ID)

@Client.on_message(broadcast_filter)
async def broadcast_handler(client: Client, message: Message):
    users = load_users()
    total = len(users)
    success = 0
    failed = 0
    start_time = time.time()

    # Decide mode: forward or text
    if message.reply_to_message:
        async def forward_to_user(user_id):
            nonlocal success, failed
            try:
                await client.forward_messages(int(user_id), message.chat.id, message.reply_to_message.id)
                success += 1
            except (UserIsBlocked, PeerIdInvalid, InputUserDeactivated, UserDeactivatedBan, FloodWait):
                failed += 1
            except Exception:
                failed += 1

        async def broadcast_batch(batch):
            await asyncio.gather(*(forward_to_user(uid) for uid in batch))

    else:
        if len(message.text.split()) == 1:
            await message.reply("⚠️ Send message as: <code>/b your message here</code> or reply to a message with /b")
            return

        text = message.text.split(" ", 1)[1]

        async def send_to_user(user_id):
            nonlocal success, failed
            try:
                await client.send_chat_action(int(user_id), ChatAction.TYPING)
                await client.send_message(int(user_id), text)
                success += 1
            except (UserIsBlocked, PeerIdInvalid, InputUserDeactivated, UserDeactivatedBan, FloodWait):
                failed += 1
            except Exception:
                failed += 1

        async def broadcast_batch(batch):
            await asyncio.gather(*(send_to_user(uid) for uid in batch))

    
    batch_size = 20
    for i in range(0, total, batch_size):
        batch = users[i:i + batch_size]
        await broadcast_batch(batch)
        await asyncio.sleep(3)

    end_time = time.time()
    elapsed = end_time - start_time
    speed = success / elapsed if elapsed > 0 else 0
    success_rate = (success / total * 100) if total > 0 else 0

    report = f"""
<pre>Broadcasting Succesfully ✅</pre>
════════════════════
⊙ <b>Total Recipients:</b> <code>{total}</code>
⊙ <b>Successfully Sent:</b> <code>{success}</code>
⊙ <b>Failed:</b> <code>{failed}</code>
⊙ <b>Success Rate:</b> <code>{success_rate:.1f}%</code>
⊙ <b>Time Taken:</b> <code>{int(elapsed // 60)}m {int(elapsed % 60)}s</code>
⊙ <b>Speed:</b> <code>{speed:.1f} users/sec</code>
"""
    await message.reply(report)
