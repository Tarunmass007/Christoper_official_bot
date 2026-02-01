import json
import os
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from datetime import datetime
import asyncio
from BOT.helper.start import load_owner_id, get_ist_time
from BOT.plans.plan_config import PLAN_DETAILS

PLAN_REQUESTS_FILE = "DATA/plan_requests.json"
request_lock = asyncio.Lock()

def load_plan_requests():
    """Load plan requests from JSON file"""
    try:
        with open(PLAN_REQUESTS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_plan_requests(requests):
    """Save plan requests to JSON file"""
    os.makedirs("DATA", exist_ok=True)
    with open(PLAN_REQUESTS_FILE, "w") as f:
        json.dump(requests, f, indent=4)

@Client.on_message(filters.command("plans") & (filters.private | filters.group))
async def show_plans(client: Client, message: Message):
    """Display all available subscription plans (Ultimate hidden from users, visible to admins)"""
    from BOT.helper.start import load_owner_id
    
    OWNER_ID = load_owner_id()
    is_owner = str(message.from_user.id) == str(OWNER_ID) if OWNER_ID else False

    plans_text = """<b>📊 Available Subscription Plans</b>
━━━━━━━━━━━━━━━━━━━━

"""

    # Filter plans: hide Ultimate from regular users, show to owner
    if is_owner:
        plans_to_show = PLAN_DETAILS.items()
    else:
        plans_to_show = [(k, v) for k, v in PLAN_DETAILS.items() if k != "Ultimate"]
    
    for plan_name, details in plans_to_show:
        features_list = "\n".join([f"  • {feature}" for feature in details["features"]])

        plans_text += f"""<b>{details['badge']} {plan_name} Plan</b>
<b>Price:</b> <code>{details['price']}</code>
<b>Duration:</b> <code>{details['duration']}</code>
<b>Features:</b>
{features_list}

━━━━━━━━━━━━━━━━━━━━

"""

    plans_text += """<b>💡 How to Get a Plan:</b>
Use <code>/requestplan [plan_name]</code> to request a plan.

<b>Example:</b> <code>/requestplan Pro</code>

<b>Contact:</b> @Chr1shtopher for payment details."""

    # Build keyboard: hide Ultimate button from regular users
    keyboard_buttons = [
        [
            InlineKeyboardButton("Request Plus", callback_data="request_Plus"),
            InlineKeyboardButton("Request Pro", callback_data="request_Pro")
        ],
        [
            InlineKeyboardButton("Request Elite", callback_data="request_Elite"),
            InlineKeyboardButton("Request VIP", callback_data="request_VIP")
        ],
    ]
    if is_owner:
        keyboard_buttons.append([
            InlineKeyboardButton("Request Ultimate", callback_data="request_Ultimate")
        ])
    keyboard_buttons.append([
        InlineKeyboardButton("My Requests", callback_data="my_requests"),
        InlineKeyboardButton("Close", callback_data="close_plans")
    ])
    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    await message.reply(plans_text, reply_markup=keyboard)


@Client.on_message(filters.command("addcredits", prefixes="/") & filters.private)
async def addcredits_command(client: Client, message: Message):
    """Admin only: add credits to a user. Format: /addcredits <username|userid> <amount>"""
    from BOT.db.store import load_owner_id, resolve_user_id, add_credits, get_user

    OWNER_ID = load_owner_id()
    if not message.from_user or str(message.from_user.id) != str(OWNER_ID):
        await message.reply(
            "<pre>⛔ Access Denied</pre>\nThis command is only available to the owner.",
            reply_to_message_id=message.id,
            parse_mode="HTML",
        )
        return
    parts = (message.text or "").strip().split(maxsplit=2)
    if len(parts) < 3:
        await message.reply(
            "<pre>Add Credits (Admin)</pre>\n━━━━━━━━━━━━━━━\n"
            "<b>Usage:</b> <code>/addcredits &lt;username|userid&gt; &lt;amount&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/addcredits 123456789 100</code>\n"
            "• <code>/addcredits @johndoe 50</code>\n\n"
            "Credits are added to the user's plan and reflected in DB (same as plans).",
            reply_to_message_id=message.id,
            parse_mode="HTML",
        )
        return
    identifier = parts[1].strip()
    try:
        amount = int(parts[2].strip())
    except ValueError:
        await message.reply(
            "❌ <b>Invalid amount.</b> Use a positive integer (e.g. <code>100</code>).",
            reply_to_message_id=message.id,
            parse_mode="HTML",
        )
        return
    if amount <= 0:
        await message.reply(
            "❌ <b>Amount must be positive.</b>",
            reply_to_message_id=message.id,
            parse_mode="HTML",
        )
        return
    user_id = resolve_user_id(identifier)
    if not user_id:
        await message.reply(
            f"❌ User not found for <code>{identifier}</code>. User must be registered; use user ID or @username.",
            reply_to_message_id=message.id,
            parse_mode="HTML",
        )
        return
    success, msg = add_credits(user_id, amount)
    user_data = get_user(user_id)
    name = (user_data or {}).get("first_name", "N/A")
    username = (user_data or {}).get("username")
    username_str = f"@{username}" if username else "N/A"
    if success:
        await message.reply(
            f"<pre>✅ Credits Added</pre>\n━━━━━━━━━━━━━━━\n"
            f"<b>User:</b> <code>{name}</code> ({username_str})\n"
            f"<b>User ID:</b> <code>{user_id}</code>\n"
            f"<b>Result:</b> {msg}\n━━━━━━━━━━━━━━━",
            reply_to_message_id=message.id,
            parse_mode="HTML",
        )
    else:
        await message.reply(
            f"❌ <b>Failed</b>: {msg}",
            reply_to_message_id=message.id,
            parse_mode="HTML",
        )


@Client.on_message(filters.command("requestplan") & (filters.private | filters.group))
async def request_plan_command(client: Client, message: Message):
    """Handle plan request via command"""
    args = message.text.split(maxsplit=1)

    from BOT.helper.start import load_owner_id
    
    OWNER_ID = load_owner_id()
    is_owner = str(message.from_user.id) == str(OWNER_ID) if OWNER_ID else False
    
    # Available plans for display (hide Ultimate from users)
    available_plans = "Plus, Pro, Elite, VIP" + (", Ultimate" if is_owner else "")
    
    if len(args) < 2:
        await message.reply(
            "❗ <b>Usage:</b> <code>/requestplan [plan_name]</code>\n\n"
            f"<b>Available plans:</b> {available_plans}\n"
            "<b>Example:</b> <code>/requestplan Pro</code>"
        )
        return

    plan_name = args[1].capitalize()

    # Check if plan exists and if user can request it (Ultimate only for owner)
    if plan_name not in PLAN_DETAILS:
        await message.reply(
            f"❌ Invalid plan name: <code>{plan_name}</code>\n\n"
            f"<b>Available plans:</b> {available_plans}"
        )
        return
    
    # Block Ultimate requests from non-owners
    if plan_name == "Ultimate" and not is_owner:
        await message.reply(
            "❌ <b>Access Denied</b>\n\n"
            "The Ultimate plan is not available for public requests.\n"
            "Please contact @Chr1shtopher for more information."
        )
        return

    await create_plan_request(client, message.from_user, plan_name, message)

@Client.on_callback_query(filters.regex(r"^request_"))
async def request_plan_callback(client: Client, callback_query: CallbackQuery):
    """Handle plan request via button"""
    plan_name = callback_query.data.replace("request_", "")
    await create_plan_request(client, callback_query.from_user, plan_name, callback_query.message)
    await callback_query.answer(f"Request for {plan_name} plan submitted!", show_alert=True)

async def create_plan_request(client: Client, user, plan_name: str, message: Message):
    """Create a new plan request"""
    async with request_lock:
        requests = load_plan_requests()
        user_id = str(user.id)

        # Check if user already has a pending request
        if user_id in requests and requests[user_id].get("status") == "pending":
            existing_plan = requests[user_id]["plan"]
            await message.reply(
                f"⚠️ You already have a pending request for <b>{existing_plan}</b> plan.\n"
                "Please wait for owner approval or use <code>/cancelrequest</code> first."
            )
            return

        # Create new request
        requests[user_id] = {
            "user_id": user.id,
            "username": user.username or "N/A",
            "first_name": user.first_name,
            "plan": plan_name,
            "requested_at": get_ist_time(),
            "status": "pending"
        }

        save_plan_requests(requests)

    plan_details = PLAN_DETAILS[plan_name]

    # Notify user
    await message.reply(
        f"""✅ <b>Plan Request Submitted Successfully!</b>

<b>Requested Plan:</b> {plan_details['badge']} {plan_name}
<b>Price:</b> <code>{plan_details['price']}</code>
<b>Duration:</b> <code>{plan_details['duration']}</code>
<b>Status:</b> <code>⏳ Pending Approval</code>

💬 Please contact @Chr1shtopher to complete the payment.
Once payment is verified, your plan will be activated.

Use <code>/myrequests</code> to check request status."""
    )

    # Notify owner
    OWNER_ID = load_owner_id()
    if OWNER_ID:
        try:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                    InlineKeyboardButton("❌ Deny", callback_data=f"deny_{user_id}")
                ],
                [
                    InlineKeyboardButton("View All Requests", callback_data="list_all_requests")
                ]
            ])

            await client.send_message(
                int(OWNER_ID),
                f"""🔔 <b>New Plan Request</b>

<b>User:</b> {user.first_name} (@{user.username or 'N/A'})
<b>User ID:</b> <code>{user.id}</code>
<b>Plan:</b> {plan_details['badge']} {plan_name}
<b>Price:</b> <code>{plan_details['price']}</code>
<b>Requested At:</b> <code>{get_ist_time()}</code>

Use buttons below to approve or deny.""",
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"Failed to notify owner: {e}")

@Client.on_message(filters.command("myrequests") & (filters.private | filters.group))
async def my_requests_command(client: Client, message: Message):
    """Show user's plan requests"""
    await show_my_requests(message.from_user.id, message)

@Client.on_callback_query(filters.regex("^my_requests$"))
async def my_requests_callback(client: Client, callback_query: CallbackQuery):
    """Show user's plan requests via callback"""
    await show_my_requests(callback_query.from_user.id, callback_query.message)
    await callback_query.answer()

async def show_my_requests(user_id: int, message: Message):
    """Display user's plan request history"""
    requests = load_plan_requests()
    user_id_str = str(user_id)

    if user_id_str not in requests:
        await message.reply("📋 You haven't requested any plans yet.\n\nUse <code>/plans</code> to view available plans.")
        return

    request = requests[user_id_str]
    status_emoji = {
        "pending": "⏳",
        "approved": "✅",
        "denied": "❌"
    }

    status = request.get("status", "pending")
    plan_details = PLAN_DETAILS.get(request["plan"], {})

    text = f"""<b>📋 Your Plan Request</b>

<b>Plan:</b> {plan_details.get('badge', '❓')} {request['plan']}
<b>Price:</b> <code>{plan_details.get('price', 'N/A')}</code>
<b>Status:</b> <code>{status_emoji.get(status, '❓')} {status.capitalize()}</code>
<b>Requested At:</b> <code>{request['requested_at']}</code>
"""

    if status == "approved":
        text += f"\n✅ <b>Your request has been approved!</b>\nYour plan should be activated shortly."
    elif status == "denied":
        text += f"\n❌ <b>Your request was denied.</b>\nContact @Chr1shtopher for more information."
    else:
        text += f"\n⏳ <b>Waiting for owner approval.</b>"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("View Plans", callback_data="view_all_plans")],
        [InlineKeyboardButton("Close", callback_data="close_plans")]
    ])

    await message.reply(text, reply_markup=keyboard)

@Client.on_message(filters.command("cancelrequest") & (filters.private | filters.group))
async def cancel_request(client: Client, message: Message):
    """Cancel user's pending plan request"""
    async with request_lock:
        requests = load_plan_requests()
        user_id = str(message.from_user.id)

        if user_id not in requests or requests[user_id].get("status") != "pending":
            await message.reply("❌ You don't have any pending plan requests to cancel.")
            return

        plan_name = requests[user_id]["plan"]
        del requests[user_id]
        save_plan_requests(requests)

    await message.reply(f"✅ Your pending request for <b>{plan_name}</b> plan has been cancelled.")

# Owner commands
@Client.on_message(filters.command("listrequests") & filters.private)
async def list_requests_command(client: Client, message: Message):
    """List all pending plan requests (Owner only)"""
    OWNER_ID = load_owner_id()
    if str(message.from_user.id) != str(OWNER_ID):
        await message.reply("⛔ This command is only available to the owner.")
        return

    await show_all_requests(message)

@Client.on_callback_query(filters.regex("^list_all_requests$"))
async def list_requests_callback(client: Client, callback_query: CallbackQuery):
    """List all pending plan requests via callback (Owner only)"""
    OWNER_ID = load_owner_id()
    if str(callback_query.from_user.id) != str(OWNER_ID):
        await callback_query.answer("⛔ Owner only!", show_alert=True)
        return

    await show_all_requests(callback_query.message)
    await callback_query.answer()

async def show_all_requests(message: Message):
    """Display all plan requests"""
    requests = load_plan_requests()

    if not requests:
        await message.reply("📋 No plan requests found.")
        return

    pending_requests = []
    approved_requests = []
    denied_requests = []

    for user_id, request in requests.items():
        status = request.get("status", "pending")
        plan_details = PLAN_DETAILS.get(request["plan"], {})

        request_line = f"• <code>{user_id}</code> - {request['first_name']} (@{request['username']}) - {plan_details.get('badge', '❓')} {request['plan']}"

        if status == "pending":
            pending_requests.append(request_line)
        elif status == "approved":
            approved_requests.append(request_line)
        else:
            denied_requests.append(request_line)

    text = "<b>📊 Plan Requests Overview</b>\n\n"

    if pending_requests:
        text += "<b>⏳ Pending Requests:</b>\n" + "\n".join(pending_requests) + "\n\n"

    if approved_requests:
        text += "<b>✅ Approved Requests:</b>\n" + "\n".join(approved_requests) + "\n\n"

    if denied_requests:
        text += "<b>❌ Denied Requests:</b>\n" + "\n".join(denied_requests) + "\n\n"

    text += "\n<b>Commands:</b>\n"
    text += "• <code>/approveplan [user_id]</code> - Approve request\n"
    text += "• <code>/denyplan [user_id]</code> - Deny request"

    await message.reply(text)

@Client.on_message(filters.command("approveplan") & filters.private)
async def approve_plan_command(client: Client, message: Message):
    """Approve a plan request (Owner only)"""
    OWNER_ID = load_owner_id()
    if str(message.from_user.id) != str(OWNER_ID):
        await message.reply("⛔ This command is only available to the owner.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.reply("❗ <b>Usage:</b> <code>/approveplan [user_id]</code>")
        return

    user_id = args[1]
    await approve_plan_request(client, user_id, message)

@Client.on_callback_query(filters.regex(r"^approve_"))
async def approve_plan_callback(client: Client, callback_query: CallbackQuery):
    """Approve a plan request via button (Owner only)"""
    user_id = callback_query.data.replace("approve_", "")
    await approve_plan_request(client, user_id, callback_query.message)
    await callback_query.answer("✅ Request approved!", show_alert=True)

async def approve_plan_request(client: Client, user_id: str, message: Message):
    """Approve a user's plan request"""
    async with request_lock:
        requests = load_plan_requests()

        if user_id not in requests:
            await message.reply(f"❌ No plan request found for user ID: <code>{user_id}</code>")
            return

        request = requests[user_id]

        if request.get("status") != "pending":
            await message.reply(f"⚠️ Request is already {request.get('status')}.")
            return

        requests[user_id]["status"] = "approved"
        requests[user_id]["approved_at"] = get_ist_time()
        save_plan_requests(requests)

    plan_name = request["plan"]
    plan_details = PLAN_DETAILS[plan_name]

    # Notify user
    try:
        await client.send_message(
            int(user_id),
            f"""✅ <b>Plan Request Approved!</b>

Your request for <b>{plan_details['badge']} {plan_name}</b> plan has been approved!

The owner will activate your plan shortly.
You'll receive a confirmation once it's activated.

Thank you for choosing our service! 🎉"""
        )
    except Exception as e:
        print(f"Failed to notify user {user_id}: {e}")

    # Notify owner
    await message.reply(
        f"""✅ <b>Plan Request Approved</b>

<b>User:</b> {request['first_name']} (@{request['username']})
<b>User ID:</b> <code>{user_id}</code>
<b>Plan:</b> {plan_details['badge']} {plan_name}

💡 Now activate the plan using:
<code>/{plan_name.lower()} {user_id}</code>"""
    )

@Client.on_message(filters.command("denyplan") & filters.private)
async def deny_plan_command(client: Client, message: Message):
    """Deny a plan request (Owner only)"""
    OWNER_ID = load_owner_id()
    if str(message.from_user.id) != str(OWNER_ID):
        await message.reply("⛔ This command is only available to the owner.")
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply("❗ <b>Usage:</b> <code>/denyplan [user_id] [reason]</code>")
        return

    user_id = args[1]
    reason = args[2] if len(args) > 2 else "No reason provided"
    await deny_plan_request(client, user_id, reason, message)

@Client.on_callback_query(filters.regex(r"^deny_"))
async def deny_plan_callback(client: Client, callback_query: CallbackQuery):
    """Deny a plan request via button (Owner only)"""
    user_id = callback_query.data.replace("deny_", "")
    await deny_plan_request(client, user_id, "Denied by owner", callback_query.message)
    await callback_query.answer("❌ Request denied!", show_alert=True)

async def deny_plan_request(client: Client, user_id: str, reason: str, message: Message):
    """Deny a user's plan request"""
    async with request_lock:
        requests = load_plan_requests()

        if user_id not in requests:
            await message.reply(f"❌ No plan request found for user ID: <code>{user_id}</code>")
            return

        request = requests[user_id]

        if request.get("status") != "pending":
            await message.reply(f"⚠️ Request is already {request.get('status')}.")
            return

        requests[user_id]["status"] = "denied"
        requests[user_id]["denied_at"] = get_ist_time()
        requests[user_id]["reason"] = reason
        save_plan_requests(requests)

    plan_name = request["plan"]
    plan_details = PLAN_DETAILS[plan_name]

    # Notify user
    try:
        await client.send_message(
            int(user_id),
            f"""❌ <b>Plan Request Denied</b>

Your request for <b>{plan_details['badge']} {plan_name}</b> plan has been denied.

<b>Reason:</b> {reason}

For more information, please contact @Chr1shtopher."""
        )
    except Exception as e:
        print(f"Failed to notify user {user_id}: {e}")

    # Notify owner
    await message.reply(
        f"""❌ <b>Plan Request Denied</b>

<b>User:</b> {request['first_name']} (@{request['username']})
<b>User ID:</b> <code>{user_id}</code>
<b>Plan:</b> {plan_details['badge']} {plan_name}
<b>Reason:</b> {reason}"""
    )

# Callback handlers for navigation
@Client.on_callback_query(filters.regex("^close_plans$"))
async def close_plans(client: Client, callback_query: CallbackQuery):
    """Close plans message"""
    await callback_query.message.delete()
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^view_all_plans$"))
async def view_plans_callback(client: Client, callback_query: CallbackQuery):
    """View plans via callback"""
    await show_plans(client, callback_query.message)
    await callback_query.answer()
