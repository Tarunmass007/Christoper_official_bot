from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified

@Client.on_message(filters.command(["help", ".help", "$help"]))
async def help_command(client: Client, message: Message):
    """Display help information and available commands"""

    help_text = """<pre>━━━━━ 📚 HELP MENU 📚 ━━━━━</pre>
<b>Welcome to Christopher Help Center!</b>

<i>Browse through different command categories to learn what each command does.</i>

<pre>Select a category below:</pre>"""

    help_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏠 Basic", callback_data="help_basic"),
            InlineKeyboardButton("🔧 Tools", callback_data="help_tools")
        ],
        [
            InlineKeyboardButton("⚡ Gates", callback_data="help_gates"),
            InlineKeyboardButton("💎 Plans", callback_data="help_plans")
        ],
        [
            InlineKeyboardButton("👑 Admin", callback_data="help_admin"),
            InlineKeyboardButton("🌐 Proxy", callback_data="help_proxy")
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="help_close")
        ]
    ])

    await message.reply(
        help_text,
        reply_to_message_id=message.id,
        reply_markup=help_buttons,
        disable_web_page_preview=True
    )


@Client.on_callback_query(filters.regex("^help_"))
async def help_callback(client: Client, callback_query: CallbackQuery):
    """Handle help menu navigation"""

    data = callback_query.data
    
    # Handle help_commands callback (from permissions.py)
    if data == "help_commands":
        await callback_query.answer()
        commands_text = """<pre>📋 Available Commands</pre>
━━━━━━━━━━━━━━━
<b>🔐 Private Chat Commands:</b>
• <code>/addurl</code> - Add Shopify site
• <code>/mysite</code> - View your site
• <code>/sh</code> - Check card on site
• <code>/txturl</code> - Add multiple sites

<b>⚡ Group Commands:</b>
• <code>/sh</code> - Shopify charge
• <code>/st</code> - Stripe charge
• <code>/br</code> - Braintree check
• <code>/bt</code> - Braintree CVV
• <code>/bin</code> - BIN lookup

<b>🔧 Tool Commands:</b>
• <code>/fake</code> - Generate fake info
• <code>/gen</code> - Generate cards
• <code>/vbv</code> - VBV check

<b>💎 Plan Commands:</b>
• <code>/plans</code> - View plans
• <code>/buy</code> - Purchase credits
━━━━━━━━━━━━━━━
<i>Use /help for full command list</i>"""
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="help_main")],
            [InlineKeyboardButton("❌ Close", callback_data="help_close")]
        ])
        
        try:
            await callback_query.message.edit_text(
                commands_text,
                reply_markup=buttons
            )
        except MessageNotModified:
            pass
        return

    if data == "help_close":
        try:
            await callback_query.message.edit_text("<pre>Thanks for using Christopher! ✨</pre>")
        except MessageNotModified:
            pass
        return

    elif data == "help_main":
        # Main help menu
        help_text = """<pre>━━━━━ 📚 HELP MENU 📚 ━━━━━</pre>
<b>Welcome to Christopher Help Center!</b>

<i>Browse through different command categories to learn what each command does.</i>

<pre>Select a category below:</pre>"""

        help_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏠 Basic", callback_data="help_basic"),
                InlineKeyboardButton("🔧 Tools", callback_data="help_tools")
            ],
            [
                InlineKeyboardButton("⚡ Gates", callback_data="help_gates"),
                InlineKeyboardButton("💎 Plans", callback_data="help_plans")
            ],
            [
                InlineKeyboardButton("👑 Admin", callback_data="help_admin"),
                InlineKeyboardButton("🌐 Proxy", callback_data="help_proxy")
            ],
            [
                InlineKeyboardButton("❌ Close", callback_data="help_close")
            ]
        ])

        try:
            await callback_query.message.edit_text(
                help_text,
                reply_markup=help_buttons,
                disable_web_page_preview=True
            )
        except MessageNotModified:
            pass

    elif data == "help_basic":
        basic_text = """<pre>━━━ 🏠 BASIC COMMANDS ━━━</pre>

<b>/start</b> - <i>Start the bot and see welcome message</i>

<b>/register</b> - <i>Register yourself to use the bot</i>

<b>/cmds</b> - <i>Display all available gates and tools menu</i>

<b>/help</b> - <i>Show this help menu with command descriptions</i>

<b>/ping</b> - <i>Check bot's response time and latency</i>

<b>/info</b> - <i>Get user information (self, reply, or by ID)</i>
<code>Usage: /info [user_id] or reply to a message</code>

<b>/groupid</b> | <b>/id</b> | <b>/chatid</b>
<i>Get the current chat/group ID</i>

<b>/fl</b> - <i>Filter and extract credit cards from text or files</i>
<code>Usage: /fl [text with cards] or reply to a file</code>
"""
        basic_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="help_main"),
                InlineKeyboardButton("❌ Close", callback_data="help_close")
            ]
        ])

        try:
            await callback_query.message.edit_text(
                basic_text,
                reply_markup=basic_buttons
            )
        except MessageNotModified:
            pass

    elif data == "help_tools":
        tools_text = """<pre>━━━ 🔧 TOOLS COMMANDS ━━━</pre>

<b>/bin</b> - <i>Perform BIN (Bank Identification Number) lookup</i>
<code>Usage: /bin 456789</code>

<b>/mbin</b> - <i>Mass BIN lookup for multiple BINs at once</i>
<code>Usage: /mbin 456789 421234 532156</code>

<b>/fake</b> | <b>/f</b>
<i>Generate fake user identity (name, address, phone, etc.)</i>
<code>Usage: /fake [country_code]</code>
<code>Example: /fake US</code>

<b>/mod</b> - <i>Check card modulus/validation</i>
<code>Usage: /mod cc|mes|ano|cvv</code>

<b>/gen</b> - <i>Generate random numbers or data</i>
<code>Usage: /gen [pattern]</code>
"""
        tools_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="help_main"),
                InlineKeyboardButton("❌ Close", callback_data="help_close")
            ]
        ])

        try:
            await callback_query.message.edit_text(
                tools_text,
                reply_markup=tools_buttons
            )
        except MessageNotModified:
            pass

    elif data == "help_gates":
        gates_text = """<pre>━━━ ⚡ GATE COMMANDS ━━━</pre>

<b>═══ Shopify Gates ═══</b>

<b>/sh</b> - <i>Shopify charge (your sites)</i>
<code>Usage: /sh cc|mes|ano|cvv</code>

<b>/msh</b> - <i>Mass Shopify charge</i>
<code>Limit: 9 cards/site/15min</code>

<b>/tsh</b> - <i>Test Shopify gate</i>

<b>/tslf</b> - <i>Test SLF gate</i>

<b>═══ Braintree ═══</b>

<b>/bt</b> - <i>Braintree CVV check</i>
<code>Usage: /bt cc|mes|ano|cvv</code>

<b>/mbt</b> - <i>Mass Braintree CVV</i>

<b>═══ URL Management ═══</b>

<b>/addurl</b> - <i>Add custom Shopify URL to bot (private)</i>
<code>Usage: /addurl https://example.com</code>

<b>/txturl</b> - <i>Add URL to text file</i>

<b>/txtls</b> - <i>List all URLs from text file</i>

<b>/rurl</b> - <i>Remove URL from list</i>
"""
        gates_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="help_main"),
                InlineKeyboardButton("❌ Close", callback_data="help_close")
            ]
        ])

        try:
            await callback_query.message.edit_text(
                gates_text,
                reply_markup=gates_buttons
            )
        except MessageNotModified:
            pass

    elif data == "help_plans":
        plans_text = """<pre>━━━ 💎 PLAN COMMANDS ━━━</pre>

<b>/plans</b> - <i>View all available subscription plans</i>

<b>/requestplan</b> - <i>Request a subscription plan</i>
<code>Usage: /requestplan [plan_name]</code>

<b>/myrequests</b> - <i>View your plan requests</i>

<b>/cancelrequest</b> - <i>Cancel your pending plan request</i>
<code>Usage: /cancelrequest [request_id]</code>

<b>/red</b> | <b>/redeem</b>
<i>Redeem a plan activation code</i>
<code>Usage: /redeem [code]</code>

<b>/act</b> - <i>Activate redemption code</i>

<b>═══ Plan Types ═══</b>
• Free - Basic access with 100 credits
• Plus - Enhanced features
• Pro - Professional tier
• Elite - Advanced capabilities
• VIP - Premium access
"""
        plans_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="help_main"),
                InlineKeyboardButton("❌ Close", callback_data="help_close")
            ]
        ])

        try:
            await callback_query.message.edit_text(
                plans_text,
                reply_markup=plans_buttons
            )
        except MessageNotModified:
            pass

    elif data == "help_admin":
        admin_text = """<pre>━━━ 👑 ADMIN COMMANDS ━━━</pre>

<b>⚠️ These commands are for bot administrators only.</b>

<b>/add</b> | <b>/.add</b> | <b>/$add</b>
<i>Add authorized groups to the bot</i>
<code>Usage: /add [group_id]</code>

<b>/rmv</b> - <i>Remove groups from authorized list</i>
<code>Usage: /rmv [group_id]</code>

<b>/b</b> - <i>Broadcast message to all bot users</i>
<code>Usage: /b [your message]</code>

<b>═══ Plan Management ═══</b>

<b>/listrequests</b> - <i>List all plan requests</i>

<b>/approveplan</b> - <i>Approve a user's plan request</i>
<code>Usage: /approveplan [request_id]</code>

<b>/denyplan</b> - <i>Deny a user's plan request</i>
<code>Usage: /denyplan [request_id]</code>

<b>/plus</b> - <i>Activate Plus plan for a user</i>
<b>/pro</b> - <i>Activate Pro plan for a user</i>
<b>/elite</b> - <i>Activate Elite plan for a user</i>
<b>/vip</b> - <i>Activate VIP plan for a user</i>
<b>/ult</b> - <i>Activate Ultimate plan for a user</i>

<b>/setfacility</b> - <i>Set plan facilities</i>
<b>/unsetfacility</b> - <i>Remove plan facilities</i>
<b>/listfacility</b> - <i>List all plan facilities</i>
"""
        admin_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="help_main"),
                InlineKeyboardButton("❌ Close", callback_data="help_close")
            ]
        ])

        try:
            await callback_query.message.edit_text(
                admin_text,
                reply_markup=admin_buttons
            )
        except MessageNotModified:
            pass

    elif data == "help_proxy":
        proxy_text = """<pre>━━━ 🌐 PROXY COMMANDS ━━━</pre>

<b>/setpx</b> - <i>Set proxy for bot operations</i>
<code>Usage: /setpx ip:port:username:password</code>
<code>Example: /setpx 1.2.3.4:8080:user:pass</code>

<b>/delpx</b> - <i>Delete/remove saved proxy</i>
<code>Usage: /delpx</code>

<b>/getpx</b> - <i>Get your currently saved proxy</i>
<code>Usage: /getpx</code>

<b>═══ Proxy Info ═══</b>
• Proxies help maintain privacy
• Set once and use across all gates
• HTTP/HTTPS/SOCKS5 supported
• Format: <code>ip:port:user:pass</code>
"""
        proxy_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="help_main"),
                InlineKeyboardButton("❌ Close", callback_data="help_close")
            ]
        ])

        try:
            await callback_query.message.edit_text(
                proxy_text,
                reply_markup=proxy_buttons
            )
        except MessageNotModified:
            pass
