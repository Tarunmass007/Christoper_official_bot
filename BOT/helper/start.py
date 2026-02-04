import asyncio
import html
import json
import os

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified

from BOT.db.store import (
    load_users,
    save_users,
    load_owner_id,
    get_ist_time,
    default_plan,
)

# Create a lock for user operations to prevent race conditions
user_lock = asyncio.Lock()

USERS_FILE = "DATA/users.json"  # kept for backwards refs; actual storage in BOT.db.store
CONFIG_FILE = "FILES/config.json"


def clean_text(text):
    if not text:
        return "N/A"
    return html.unescape(text)

@Client.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    # Check if message is from a user (not a channel or anonymous admin)
    if not message.from_user:
        await message.reply("This command can only be used by users, not channels or anonymous admins.")
        return

    # Loading animation: "Hello !!"
    animated_texts = ["[", "[H", "[He", "[Hel", "[Hell", "[Hello", "[Hello !", "[Hello !!]"]

    sent = await message.reply("<pre>[</pre>", quote=True)

    for text in animated_texts[1:]:
        await asyncio.sleep(0.12)
        try:
            await sent.edit_text(f"<pre>{text}</pre>")
        except:
            pass

    # User's display name
    name = message.from_user.first_name
    if message.from_user.last_name:
        name += f" {message.from_user.last_name}"
    profile = f"<a href='tg://user?id={message.from_user.id}'>{name}</a>"

    final_text = f"""
[<a href='https://t.me/Chr1shtopher'>⛯</a>] <b>Christopher | Version - 1.0</b>
<pre>Constantly Upgrading...</pre>
━━━━━━━━━━━━━
<b>Hello,</b> {profile}
<i>How Can I Help You Today.?! 📊</i>
⌀ <b>Your UserID</b> - <code>{message.from_user.id}</code>
⛶ <b>BOT Status</b> - <code>Online 🟢</code>
⎔ <b>Explore</b> - <b>Click the buttons below to discover</b>
<b>all the features we offer!</b>
"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔐 Auth Gates", callback_data="auth"),
            InlineKeyboardButton("💳 Charge Gates", callback_data="charge")
        ],
        [
            InlineKeyboardButton("🔧 Tools", callback_data="tools"),
            InlineKeyboardButton("📋 Commands", callback_data="allcmds")
        ],
        [
            InlineKeyboardButton("👤 Register", callback_data="register"),
            InlineKeyboardButton("❌ Close", callback_data="close")
        ]
    ])

    await asyncio.sleep(0.5)
    try:
        await sent.edit_text(final_text.strip(), reply_markup=keyboard, disable_web_page_preview=True)
    except MessageNotModified:
        pass

# Handle the register callback (button press)
@Client.on_callback_query(filters.regex("register"))
async def register_callback(client, callback_query):
    async with user_lock:
        users = load_users()
        user_id = str(callback_query.from_user.id)

        OWNER_ID = load_owner_id()

        if user_id in users:
            user_data = users[user_id]
            first_name = user_data["first_name"]
            profile = f"<a href='tg://user?id={user_id}'>{first_name}</a> ({user_data['role']})"

            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Commands", callback_data="home"),
                 InlineKeyboardButton("❌ Close", callback_data="exit")]
            ])

            await callback_query.message.edit_text(f"<pre>User {profile} You Are Already Registered</pre>", reply_markup=buttons)
            return

        first_name = callback_query.from_user.first_name
        username = callback_query.from_user.username if callback_query.from_user.username else None

        plan_data = default_plan(user_id)
        role = plan_data["plan"]

        users[user_id] = {
            "first_name": first_name,
            "username": username,
            "user_id": callback_query.from_user.id,
            "registered_at": get_ist_time(),
            "plan": plan_data,
            "role": role,
        }

        save_users(users)

    users = load_users()
    user_data = users[user_id]
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Commands", callback_data="home"),
         InlineKeyboardButton("❌ Close", callback_data="exit")]
    ])

    try:
        await callback_query.message.edit_text(f"""<pre>Registration Successfull ✔</pre>
╭━━━━━━━━━━
│● <b>Name</b> : <code>{first_name} [{user_data['plan']['badge']}]</code>
│● <b>UserID</b> : <code>{user_id}</code>
│● <b>Credits</b> : <code>{user_data['plan']['credits']}</code>
│● <b>Role</b> : <code>{user_data['role']}</code>
╰━━━━━━━━━━""", reply_markup=buttons)
    except MessageNotModified:
        pass


# Handle the /register command
@Client.on_message(filters.command("register"))
async def register_command(client, message):
    # Check if message is from a user (not a channel or anonymous admin)
    if not message.from_user:
        await message.reply("This command can only be used by users, not channels or anonymous admins.")
        return

    async with user_lock:
        users = load_users()
        user_id = str(message.from_user.id)

        OWNER_ID = load_owner_id()

        if user_id in users:
            user_data = users[user_id]
            first_name = user_data["first_name"]
            profile = f"<a href='tg://user?id={user_id}'>{first_name}</a> ({user_data['role']})"

            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Commands", callback_data="home"),
                 InlineKeyboardButton("❌ Close", callback_data="exit")]
            ])

            await client.send_message(
                chat_id=message.chat.id,
                text=f"<pre>User {profile} You Are Already Registered</pre>",
                reply_to_message_id=message.id,
                reply_markup=buttons,
            )
            return

        first_name = message.from_user.first_name
        username = message.from_user.username if message.from_user.username else None

        plan_data = default_plan(user_id)
        role = plan_data["plan"]

        users[user_id] = {
            "first_name": first_name,
            "username": username,
            "user_id": message.from_user.id,
            "registered_at": get_ist_time(),
            "plan": plan_data,
            "role": role,
        }

        save_users(users)

    users = load_users()
    user_data = users[user_id]
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Commands", callback_data="home"),
         InlineKeyboardButton("❌ Close", callback_data="exit")]
    ])

    # Reply to the original message for successful registration
    await client.send_message(
        chat_id=message.chat.id,
        text=f"""<pre>Registration Successfull ✔</pre>
╭━━━━━━━━━━
│● <b>Name</b> : <code>{first_name} [{user_data['plan']['badge']}]</code>
│● <b>UserID</b> : <code>{user_id}</code>
│● <b>Credits</b> : <code>{user_data['plan']['credits']}</code>
│● <b>Role</b> : <code>{user_data['role']}</code>
╰━━━━━━━━━━""",
        reply_to_message_id=message.id,
        reply_markup=buttons
    )

@Client.on_message(filters.command("cmds"))
async def show_cmds(client, message):
    home_text = """<pre>📋 #Christopher — Commands Menu</pre>
━━━━━━━━━━━━━━━
<b>🔐 Auth:</b> <code>/au</code> <code>/mau</code> <code>/starr</code> <code>/mstarr</code> <code>/b3</code>
<b>💳 Charge:</b> <code>/sh</code> <code>/msh</code> <code>/st</code> <code>/mst</code> <code>/sc</code> <code>/msc</code> <code>/br</code>
<b>📌 Sites:</b> <code>/addurl</code> <code>/txturl</code> <code>/mysite</code> <code>/tsh</code>
<b>🔧 Tools:</b> <code>/bin</code> <code>/vbv</code> <code>/setpx</code> <code>/plans</code> <code>/help</code>
━━━━━━━━━━━━━━━
<b>~ Main:</b> <a href="https://t.me/+IIHrr_9bwBM3NTA1">Join Now</a>
<b>~ Note:</b> <code>Report bugs → @Chr1shtopher</code>
<pre>Choose category below:</pre>"""

    home_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔐 Auth Gates", callback_data="auth"),
            InlineKeyboardButton("💳 Charge Gates", callback_data="charge")
        ],
        [
            InlineKeyboardButton("🔧 Tools & More", callback_data="tools"),
            InlineKeyboardButton("📋 All Commands", callback_data="allcmds")
        ],
        [InlineKeyboardButton("❌ Close", callback_data="exit")]
    ])

    await message.reply(
        home_text,
        reply_to_message_id=message.id,
        reply_markup=home_buttons,
        disable_web_page_preview=True,
        parse_mode="HTML"
    )

@Client.on_callback_query(filters.regex("^(exit|home|close|auth|charge|tools|allcmds|auto|stripe|stripeworker|braintree)$"))
async def handle_callbacks(client, callback_query):
    data = callback_query.data

    if data in ["exit", "close"]:
        try:
            await callback_query.message.edit_text("<pre>Thanks For Using #Christopher 👋</pre>")
        except MessageNotModified:
            pass
        return

    elif data == "home":
        home_text = """<pre>📋 #Christopher — Commands Menu</pre>
━━━━━━━━━━━━━━━
<b>🔐 Auth:</b> <code>/au</code> <code>/mau</code> <code>/starr</code> <code>/mstarr</code> <code>/b3</code>
<b>💳 Charge:</b> <code>/sh</code> <code>/msh</code> <code>/st</code> <code>/mst</code> <code>/sc</code> <code>/msc</code> <code>/br</code>
<b>📌 Sites:</b> <code>/addurl</code> <code>/txturl</code> <code>/mysite</code> <code>/tsh</code>
<b>🔧 Tools:</b> <code>/bin</code> <code>/vbv</code> <code>/setpx</code> <code>/plans</code> <code>/help</code>
━━━━━━━━━━━━━━━
<b>~ Main:</b> <a href="https://t.me/+IIHrr_9bwBM3NTA1">Join Now</a>
<b>~ Note:</b> <code>Report bugs → @Chr1shtopher</code>
<pre>Choose category below:</pre>"""
        
        home_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔐 Auth Gates", callback_data="auth"),
                InlineKeyboardButton("💳 Charge Gates", callback_data="charge")
            ],
            [
                InlineKeyboardButton("🔧 Tools & More", callback_data="tools"),
                InlineKeyboardButton("📋 All Commands", callback_data="allcmds")
            ],
            [InlineKeyboardButton("❌ Close", callback_data="exit")]
        ])
        
        try:
            await callback_query.message.edit_text(
                home_text,
                reply_markup=home_buttons,
                disable_web_page_preview=True,
                parse_mode="HTML"
            )
        except MessageNotModified:
            pass
        return

    elif data == "auth":
        auth_text = """<pre>#Christopher 〔AUTH GATES〕</pre>
━━━━━━━━━━━━━━━
<b>⚡ Braintree Auth:</b>
⟐ <code>/b3 cc|mm|yy|cvv</code> - Single
⟐ <b>Status:</b> <code>Active ✅</code>
━━━━━━━━━━━━━━━
<b>⚡ Stripe Auth:</b>
⟐ <code>/au cc|mm|yy|cvv</code> - Single
⟐ <code>/mau</code> - Mass (Reply)
⟐ <b>Status:</b> <code>Active ✅</code>
━━━━━━━━━━━━━━━
<b>Note:</b> Works in groups & private"""
        
        auth_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Main Menu", callback_data="home"),
                InlineKeyboardButton("❌ Close", callback_data="exit")
            ]
        ])
        
        try:
            await callback_query.message.edit_text(
                auth_text,
                reply_markup=auth_buttons,
                parse_mode="HTML"
            )
        except MessageNotModified:
            pass

    elif data == "charge":
        charge_text = """<pre>#Christopher 〔 CHARGE GATES 〕</pre>
━━━━━━━━━━━━━━━
Choose charge gate type below."""
        
        charge_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🛒 Shopify Self", callback_data="auto"),
                InlineKeyboardButton("💎 Stripe $20", callback_data="stripe")
            ],
            [InlineKeyboardButton("⚡ Stripe Worker", callback_data="stripeworker")],
            [
                InlineKeyboardButton("📋 Main Menu", callback_data="home"),
                InlineKeyboardButton("❌ Close", callback_data="exit")
            ]
        ])
        
        try:
            await callback_query.message.edit_text(
                charge_text,
                reply_markup=charge_buttons,
                parse_mode="HTML"
            )
        except MessageNotModified:
            pass

    elif data == "tools":
        tools_text = """<pre>#Christopher 〔TOOLS〕</pre>
━━━━━━━━━━━━━━━
<b>🔧 Proxy Management:</b>
⟐ <code>/setpx proxy</code> - Set Proxy (Private)
⟐ <code>/getpx</code> - View Your Proxy
⟐ <code>/delpx</code> - Delete Proxy
━━━━━━━━━━━━━━━
<b>🔍 Lookup Tools:</b>
⟐ <code>/bin 543210</code> - BIN Lookup
⟐ <code>/vbv</code> <code>/mvbv</code> — VBV/MBV
━━━━━━━━━━━━━━━
<b>📊 Other Tools:</b>
⟐ <code>/plans</code> - View Plans
⟐ <code>/ping</code> - Bot Status
⟐ <code>/info</code> - User Info
━━━━━━━━━━━━━━━
<b>Status:</b> <code>Active ✅</code>"""
        
        tools_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Main Menu", callback_data="home"),
                InlineKeyboardButton("❌ Close", callback_data="exit")
            ]
        ])
        
        try:
            await callback_query.message.edit_text(
                tools_text,
                reply_markup=tools_buttons,
                parse_mode="HTML"
            )
        except MessageNotModified:
            pass

    elif data == "allcmds":
        allcmds_text = """<pre>#Christopher — All Commands</pre>
━━━━━━━━━━━━━━━
<b>🔐 AUTH</b>
<code>/au</code> <code>/mau</code> — Stripe Auth | <code>/b3</code> — Braintree
━━━━━━━━━━━━━━━
<b>💳 CHARGE</b>
<code>/sh</code> <code>/msh</code> — Shopify Self | <code>/st</code> <code>/mst</code> — Stripe $20 | <code>/sc</code> <code>/msc</code> — Stripe Worker
━━━━━━━━━━━━━━━
<b>📌 SITES</b>
<code>/addurl</code> <code>/txturl</code> <code>/mysite</code> <code>/tsh</code>
━━━━━━━━━━━━━━━
<b>🔧 TOOLS</b>
<code>/bin</code> <code>/vbv</code> <code>/setpx</code> <code>/plans</code> <code>/ping</code>
━━━━━━━━━━━━━━━
<b>📋 OTHER</b>
<code>/start</code> <code>/register</code> <code>/cmds</code> <code>/help</code>"""
        
        allcmds_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Main Menu", callback_data="home"),
                InlineKeyboardButton("❌ Close", callback_data="exit")
            ]
        ])
        
        try:
            await callback_query.message.edit_text(
                allcmds_text,
                reply_markup=allcmds_buttons,
                parse_mode="HTML"
            )
        except MessageNotModified:
            pass

    elif data == "auto":
        auto_text = """<pre>#Christopher 〔Self Shopify〕</pre>
━━━━━━━━━━━━━━━
<b>📋 Site Management:</b>
⟐ <code>/addurl site.com</code> - Add Site
⟐ <code>/txturl site.com</code> - Add TXT Site
⟐ <code>/mysite</code> - View Current Site
⟐ <code>/remurl</code> - Remove Site
━━━━━━━━━━━━━━━
<b>⚡ Check Commands:</b>
⟐ <code>/sh cc|mm|yy|cvv</code> - Single
⟐ <code>/msh</code> - Mass Check (Reply)
⟐ <code>/tsh</code> - TXT Sites Check
━━━━━━━━━━━━━━━
<b>Status: Active ✅</b>"""
        
        auto_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Main Menu", callback_data="home"),
                InlineKeyboardButton("❌ Close", callback_data="exit")
            ]
        ])
        
        try:
            await callback_query.message.edit_text(
                auto_text,
                reply_markup=auto_buttons,
                parse_mode="HTML"
            )
        except MessageNotModified:
            pass

    elif data == "stripe":
        stripe_text = """<pre>#Christopher 〔Stripe $20 Charge〕</pre>
━━━━━━━━━━━━━━━
<b>⚡ Stripe $20 Charge:</b>
⟐ <code>/st cc|mm|yy|cvv</code> - Single
⟐ <code>/mst</code> - Mass (Reply)
━━━━━━━━━━━━━━━
<b>Status:</b> <code>Active ✅</code>"""
        
        stripe_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Main Menu", callback_data="home"),
                InlineKeyboardButton("❌ Close", callback_data="exit")
            ]
        ])
        
        try:
            await callback_query.message.edit_text(
                stripe_text,
                reply_markup=stripe_buttons,
                parse_mode="HTML"
            )
        except MessageNotModified:
            pass

    elif data == "stripeworker":
        stripeworker_text = """<pre>#Christopher 〔 Stripe Worker Charge 〕</pre>
━━━━━━━━━━━━━━━
<b>⚡ Stripe Worker Gate:</b>
⟐ <code>/sc cc|mm|yy|cvv</code> — Single check
⟐ <code>/msc</code> — Mass check (reply or .txt file)
⟐ <b>Status:</b> <code>Active ✅</code>"""
        
        stripeworker_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Main Menu", callback_data="home"),
                InlineKeyboardButton("❌ Close", callback_data="exit")
            ]
        ])
        
        try:
            await callback_query.message.edit_text(
                stripeworker_text,
                reply_markup=stripeworker_buttons,
                parse_mode="HTML"
            )
        except MessageNotModified:
            pass

    elif data == "braintree":
        braintree_text = """<pre>#Christopher 〔Braintree Auth〕</pre>
━━━━━━━━━━━━━━━
⟐ <b>Command</b>: <code>/b3 cc|mm|yy|cvv</code>
⟐ <b>Status: Active ✅</b>"""

        braintree_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Main Menu", callback_data="home"),
                InlineKeyboardButton("❌ Close", callback_data="exit")
            ]
        ])
        
        try:
            await callback_query.message.edit_text(
                braintree_text,
                reply_markup=braintree_buttons,
                parse_mode="HTML"
            )
        except MessageNotModified:
            pass
