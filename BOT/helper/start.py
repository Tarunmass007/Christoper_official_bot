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
            InlineKeyboardButton("Register", callback_data="register"),
            InlineKeyboardButton("Commands", callback_data="home")
        ],
        [
            InlineKeyboardButton("Close", callback_data="close")
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
                [InlineKeyboardButton("Home", callback_data="home"),
                 InlineKeyboardButton("Exit", callback_data="exit")]
            ])

            await callback_query.message.reply_text(f"<pre>User {profile} You Are Already Registered</pre>", reply_markup=buttons)
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
        [InlineKeyboardButton("Home", callback_data="home"),
         InlineKeyboardButton("Exit", callback_data="exit")]
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
                [InlineKeyboardButton("Home", callback_data="home"),
                 InlineKeyboardButton("Exit", callback_data="exit")]
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
        [InlineKeyboardButton("Home", callback_data="home"),
         InlineKeyboardButton("Exit", callback_data="exit")]
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
    home_text = """<pre>JOIN BEFORE USING. ✔️</pre>
<b>~ Main :</b> <b><a href="https://t.me/+IIHrr_9bwBM3NTA1">Join Now</a></b>
<b>~ Chat Group :</b> <b><a href="https://t.me/+IIHrr_9bwBM3NTA1">Join Now</a></b>
<b>~ Note :</b> <code>Report Bugs To @Chr1shtopher</code>
<b>~ Proxy :</b> <code>Live 💎</code>
<pre>Choose Your Gate Type :</pre>"""

    home_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Gates", callback_data="gates"),
            InlineKeyboardButton("Tools", callback_data="tools")
        ],
        [
            InlineKeyboardButton("Close", callback_data="exit")
        ]
    ])

    await message.reply(
        home_text,
        reply_to_message_id=message.id,
        reply_markup=home_buttons,
        disable_web_page_preview=True
    )


@Client.on_callback_query(filters.regex("^(exit|home|gates|tools|auth|charge|shopify|auto|braintree|stripe)$"))
async def handle_callbacks(client, callback_query):
    data = callback_query.data

    if data == "exit":
        try:
            await callback_query.message.edit_text("<pre>Thanks For Using #Christopher</pre>")
        except MessageNotModified:
            pass

    elif data == "home":
        # Home text jab home button click kare
        home_text = """<pre>JOIN BEFORE USING. ✔️</pre>
<b>~ Main :</b> <b><a href="https://t.me/+IIHrr_9bwBM3NTA1">Join Now</a></b>
<b>~ Chat Group :</b> <b><a href="https://t.me/+IIHrr_9bwBM3NTA1">Join Now</a></b>
<b>~ Note :</b> <code>Report Bugs To @Chr1shtopher</code>
<b>~ Proxy :</b> <code>Live 💎</code>
<pre>Choose Your Gate Type :</pre>"""

        home_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Gates", callback_data="gates"),
                InlineKeyboardButton("Tools", callback_data="tools")
            ],
            [
                InlineKeyboardButton("Close", callback_data="exit")
            ]
        ])

        try:
            await callback_query.message.edit_text(
                home_text,
                reply_markup=home_buttons,
                disable_web_page_preview=True
            )
        except MessageNotModified:
            pass

    elif data == "gates":
        # Gates ke andar jaake buttons dikhao
        gates_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Auth", callback_data="auth"),
                InlineKeyboardButton("Charge", callback_data="charge")
            ],
            [
                InlineKeyboardButton("Back", callback_data="home")  # yaha se home jaayega
            ]
        ])

        gates_text = "<pre>Choose Gate Type:</pre>"

        try:
            await callback_query.message.edit_text(
                gates_text,
                reply_markup=gates_buttons
            )
        except MessageNotModified:
            pass

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
<b>Note:</b> Works in groups & private
"""
        auth_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Back", callback_data="gates"),
                InlineKeyboardButton("Close", callback_data="exit")
            ]
        ])
        try:
            await callback_query.message.edit_text(
                auth_text,
                reply_markup=auth_buttons
            )
        except MessageNotModified:
            pass

    elif data == "charge":
        charge_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Shopify Self", callback_data="auto"),
                InlineKeyboardButton("Stripe $20", callback_data="stripe")
            ],
            [
                InlineKeyboardButton("Back", callback_data="gates"),
                InlineKeyboardButton("Close", callback_data="exit")
            ]
        ])

        charge_text = "<pre>#Christopher 〔 Charge 〕</pre>"

        try:
            await callback_query.message.edit_text(
                charge_text,
                reply_markup=charge_buttons
            )
        except MessageNotModified:
            pass

    elif data == "shopify":
        # Redirect to auto (self shopify) since we removed fixed shopify gates
        shopify_text = """<pre>#Christopher 〔Self Shopify〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Setup</b>: <code>/addurl https://store.com</code>
⟐ <b>Check</b>: <code>/sh cc|mes|ano|cvv</code>
⟐ <b>Mass</b>: <code>/msh cc|mes|ano|cvv</code>
⟐ <b>TXT</b>: <code>/tsh cc|mes|ano|cvv</code>
⟐ <b>Status: Active ✅</b>
"""
        shopify_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Back", callback_data="charge"),
                InlineKeyboardButton("Close", callback_data="exit")
            ]
        ])
        try:
            await callback_query.message.edit_text(
                shopify_text,
                reply_markup=shopify_buttons
            )
        except MessageNotModified:
            pass

    elif data == "auto":
        auto_text = """<pre>#Christopher 〔Self Shopify〕</pre>
━━━━━━━━━━━━━━━
<b>📋 Site Management:</b>
⟐ <code>/addurl site.com</code> - Add Site (Private)
⟐ <code>/txturl site.com</code> - Add TXT Site (Private)
⟐ <code>/txtls</code> - View TXT Sites
⟐ <code>/mysite</code> - View Current Site
⟐ <code>/remurl</code> - Remove Site
━━━━━━━━━━━━━━━
<b>⚡ Check Commands:</b>
⟐ <code>/sh cc|mm|yy|cvv</code> - Single Check
⟐ <code>/msh</code> - Mass Check (Reply)
⟐ <code>/tsh</code> - TXT Sites Check (Reply)
━━━━━━━━━━━━━━━
<b>🔧 Proxy:</b>
⟐ <code>/setpx proxy</code> - Set Proxy (Private)
⟐ <code>/getpx</code> - View Proxy
⟐ <code>/delpx</code> - Delete Proxy
━━━━━━━━━━━━━━━
<b>Status: Active ✅</b>
"""
        auto_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Back", callback_data="charge"),
                InlineKeyboardButton("Close", callback_data="exit")
            ]
        ])
        try:
            await callback_query.message.edit_text(
                auto_text,
                reply_markup=auto_buttons
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
<b>Limit:</b> <code>As Per Plan</code>
<b>Status:</b> <code>Active ✅</code>
━━━━━━━━━━━━━━━
<b>Note:</b> Works in groups & private
"""
        stripe_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Back", callback_data="charge"),
                InlineKeyboardButton("Close", callback_data="exit")
            ]
        ])
        try:
            await callback_query.message.edit_text(
                stripe_text,
                reply_markup=stripe_buttons
            )
        except MessageNotModified:
            pass

    elif data in ["braintree"]:
        braintree_text = """<pre>#Christopher 〔Braintree Auth〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Name</b>: <code>Braintree Auth</code>
⟐ <b>Command</b>: <code>/b3 cc|mes|ano|cvv</code>
⟐ <b>Status: Active ✅</b>
"""

        braintree_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Back", callback_data="gates"),
                InlineKeyboardButton("Close", callback_data="exit")
            ]
        ])
        try:
            await callback_query.message.edit_text(
                braintree_text,
                reply_markup=braintree_buttons
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
⟐ <code>/mbin bin1 bin2</code> - Mass BIN
━━━━━━━━━━━━━━━
<b>🎲 Generators:</b>
⟐ <code>/gen bin|mm|yy|cvv|amt</code> - Card Gen
⟐ <code>/fake [country]</code> - Fake Identity
━━━━━━━━━━━━━━━
<b>📊 Other:</b>
⟐ <code>/ping</code> - Bot Latency
⟐ <code>/info</code> - Your Info
⟐ <code>/plans</code> - View Plans
━━━━━━━━━━━━━━━
<b>Status: Active ✅</b>
"""
        tools_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Back", callback_data="home"),
                InlineKeyboardButton("Close", callback_data="exit")
            ]
        ])
        try:
            await callback_query.message.edit_text(
                tools_text,
                reply_markup=tools_buttons
            )
        except MessageNotModified:
            pass
