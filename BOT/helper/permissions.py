from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType, ParseMode

from BOT.helper.start import load_users
from BOT.db.store import load_owner_id, load_allowed_groups, save_allowed_groups

OWNER_ID = int(load_owner_id() or 0)

# Commands that require private chat - Only site/proxy management
PRIVATE_ONLY_COMMANDS = [
    "addurl", "slfurl", "seturl",
    "setpx",
]


async def is_premium_user(message: Message) -> bool:
    """Check if user is premium - currently all users have access."""
    return True


async def check_private_access(message: Message) -> bool:
    """
    Check if command is used in private chat.
    If used in group, guide user to use in private with professional UI.
    Returns True to continue, False to block.
    """
    # Always allow in private chat
    if message.chat.type == ChatType.PRIVATE:
        return True
    
    # For group chats, check if command needs private
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        # Extract command from message
        if message.text:
            command_text = message.text.split()[0] if message.text.split() else ""
            command = command_text.replace("/", "").replace(".", "").replace("$", "").lower()
            
            if command in PRIVATE_ONLY_COMMANDS:
                # Get bot username for link
                try:
                    bot_info = await message._client.get_me()
                    bot_username = bot_info.username
                    bot_link = f"https://t.me/{bot_username}"
                except:
                    bot_link = "https://t.me/YOUR_BOT"
                
                await message.reply(
                    f"""<pre>🔒 Private Command Required</pre>
━━━━━━━━━━━━━━━━━
<b>This command only works in private chat.</b>

<b>📋 Command:</b> <code>/{command}</code>

<b>🔐 Why Private Chat?</b>
• Protects your sensitive card data
• Faster response without queue
• Personal site management
• Better security & privacy

<b>📱 How to Use:</b>
1️⃣ Click the button below
2️⃣ Start the bot privately
3️⃣ Use your command there
━━━━━━━━━━━━━━━━━
<i>Your security is our priority!</i>""",
                    reply_to_message_id=message.id,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📱 Open Private Chat", url=bot_link)],
                        [InlineKeyboardButton("📖 Commands Help", callback_data="help_commands")]
                    ])
                )
                return False
    
    # Allow other cases
    return True


async def require_private_chat(message: Message, command_name: str = None) -> bool:
    """
    Decorator-style function to require private chat.
    Shows professional guide if used in group.
    
    Args:
        message: The Pyrogram message object
        command_name: Optional command name for better messaging
        
    Returns:
        True if in private chat, False if blocked
    """
    if message.chat.type == ChatType.PRIVATE:
        return True
    
    # Get bot info for link
    try:
        bot_info = await message._client.get_me()
        bot_username = bot_info.username
        bot_link = f"https://t.me/{bot_username}"
    except:
        bot_link = "https://t.me/YOUR_BOT"
    
    cmd_display = f"<code>/{command_name}</code>" if command_name else "This command"
    
    await message.reply(
        f"""<pre>🔐 Private Access Only</pre>
━━━━━━━━━━━━━━━━━
{cmd_display} <b>requires private chat.</b>

<b>Benefits of Private Chat:</b>
✅ Secure card data handling
✅ Personal site management
✅ No message queue delays
✅ Better user experience

<b>Click below to continue:</b>
━━━━━━━━━━━━━━━━━""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Start Private Chat", url=bot_link)]
        ])
    )
    return False

@Client.on_message(filters.command(["add", ".add", "$add"]) & filters.user(OWNER_ID))
async def add_group(client: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 2:
            return await message.reply("❌ Format: /add -100xxxx")

        chat_id = int(args[1])
        groups = load_allowed_groups()
        if chat_id in groups:
            return await message.reply("ℹ️ Already added.")

        groups.append(chat_id)
        save_allowed_groups(groups)
        await message.reply(f"✅ Group {chat_id} added.")
    except Exception as e:
        await message.reply(f"⚠️ Error: {e}")

@Client.on_message(filters.command("rmv") & filters.user(OWNER_ID))
async def remove_group(client: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 2:
            return await message.reply("❌ Format: /rmv -100xxxx")

        chat_id = int(args[1])
        groups = load_allowed_groups()
        if chat_id not in groups:
            return await message.reply("ℹ️ Group not in allowed list.")

        groups.remove(chat_id)
        save_allowed_groups(groups)
        await message.reply(f"✅ Group {chat_id} removed.")
    except Exception as e:
        await message.reply(f"⚠️ Error: {e}")

@Client.on_message(filters.command(["groupid", "id", "chatid"]))
async def get_group_id(client: Client, message: Message):
    """Shows the current chat ID"""
    chat_id = message.chat.id
    chat_type = message.chat.type
    chat_title = message.chat.title or "Private Chat"

    response = (
        "<b>📋 Chat Information</b>\n"
        f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
        f"<b>Chat Type:</b> <code>{chat_type}</code>\n"
        f"<b>Chat Title:</b> <code>{chat_title}</code>\n\n"
        f"<i>Use this ID with /add {chat_id} to approve this group</i>"
    )
    await message.reply(response)

@Client.on_message(filters.command(["add", "rmv"]) & filters.user(OWNER_ID))
async def modify_allowed_chats(bot, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("❌ Usage: /add <chat_id> or /rmv <chat_id>")

    command = message.command[0]
    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid chat ID.")

    allowed = load_allowed_groups()

    if command == "add":
        if chat_id not in allowed:
            allowed.append(chat_id)
            save_allowed_groups(allowed)
            return await message.reply_text(f"✅ Chat ID {chat_id} added to allowed list.")
        return await message.reply_text(f"ℹ️ Chat ID {chat_id} is already allowed.")

    if command == "rmv":
        if chat_id in allowed:
            allowed.remove(chat_id)
            save_allowed_groups(allowed)
            return await message.reply_text(f"✅ Chat ID {chat_id} removed from allowed list.")
        return await message.reply_text(f"❌ Chat ID {chat_id} not found in allowed list.")