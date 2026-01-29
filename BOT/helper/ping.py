from pyrogram import Client, filters
from time import time

@Client.on_message(filters.command("ping"))
async def ping_handler(client, message):
    start = time()
    temp = await message.reply("🚥")  # Send temporary ping message
    end = time()
    await temp.delete()  # Clean

    ping_ms = round((end - start) * 1000)

    if ping_ms <= 200:
        level = "Excellent ⚡"
    elif ping_ms <= 350:
        level = "Good ✔️"
    elif ping_ms <= 500:
        level = "Moderate ⚠️"
    else:
        level = "Poor ❌"

    await message.reply(
        f"""<pre>
┌────[SYSTEM PING]
│ 
⌯ Response : <b><code>{ping_ms} ms</code></b>
⌯ Status   : <b><code>{level}</code></b>
└────────────────────
</pre>""",
        reply_to_message_id=message.id
    )
