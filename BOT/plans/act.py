from pyrogram import Client, filters
from pyrogram.types import Message
from BOT.plans.plan1 import activate_plus_plan
from BOT.plans.plan2 import activate_pro_plan
from BOT.plans.plan3 import activate_elite_plan
from BOT.plans.plan4 import activate_vip_plan
from BOT.plans.plan5 import activate_ult_plan
# from BOT.plans.free import activate_free_plan
from BOT.helper.start import load_owner_id
from BOT.helper.start import load_users, save_users 

from datetime import datetime

OWNER_ID = load_owner_id()

def extract_user_id(message: Message) -> str:
    if message.reply_to_message:
        return str(message.reply_to_message.from_user.id)
    args = message.text.split()
    if len(args) >= 2:
        return args[1].replace("@", "")
    return None

def is_owner(user_id: int) -> bool:
    return str(user_id) == str(OWNER_ID)

def is_facility_owner(user_id: int) -> bool:
    """Check if user is a facility owner (restricted from giving plans)"""
    users = load_users()
    user = users.get(str(user_id), {})
    return user.get("facility_owner", False)

async def notify_user_plan_activated(app, user_id: str, plan_name: str):
    users = load_users()
    user = users.get(str(user_id))
    if not user:
        return

    plan = user.get("plan", {})
    activated_at = plan.get("activated_at", "N/A")
    expires_at = plan.get("expires_at", "N/A")
    antispam = plan.get("antispam", "N/A")
    mlimit = plan.get("mlimit", "N/A")
    badge = plan.get("badge", "❓")

    # Example prices — customize as needed
    plan_prices = {
        "Plus": "$1",
        "Pro": "$6",
        "Elite": "$9",
        "VIP": "$15"
    }

    await app.send_message(
        int(user_id),
        f"""<pre>✅ Plan Activated Successfully</pre>
<b>• Plan:</b> <code>{plan_name}</code>
<b>• Price:</b> <code>{plan_prices.get(plan_name, '₹0')}</code>
<b>• Activated At:</b> <code>{activated_at}</code>
<b>• Expires At:</b> <code>{expires_at}</code>
<b>• Anti-Spam:</b> <code>{antispam}s</code>
<b>• Mass Limit:</b> <code>{mlimit}</code>
<b>• Badge:</b> {badge}

🎉 Thank you for choosing our premium service.
Use <code>/info</code> anytime to check your current status.
"""
    )

@Client.on_message(filters.command("plus") & (filters.private | filters.group))
async def handle_plus(client, message: Message):
    if not is_owner(message.from_user.id):
        return await message.reply("⛔ Only the owner can activate plans.")

    if is_facility_owner(message.from_user.id):
        return await message.reply("⛔ Facility owners cannot provide plans to other users.")

    user_id = extract_user_id(message)
    if not user_id:
        return await message.reply("❗Usage: `/plus [user_id|@username|reply]`", quote=True)

    result = await activate_plus_plan(user_id)
    if result == "already_active":
        return await message.reply("💠 User already has an active Plus plan.")
    elif result:
        await message.reply(f"✅ Plus plan activated for `{user_id}`.")
        await notify_user_plan_activated(client, user_id, "Plus")
    else:
        await message.reply("❌ Failed to activate Plus plan. User not registered.")

@Client.on_message(filters.command("pro") & (filters.private | filters.group))
async def handle_pro(client, message: Message):
    if not is_owner(message.from_user.id):
        return await message.reply("⛔ Only the owner can activate plans.")

    if is_facility_owner(message.from_user.id):
        return await message.reply("⛔ Facility owners cannot provide plans to other users.")

    user_id = extract_user_id(message)
    if not user_id:
        return await message.reply("❗Usage: `/pro [user_id|@username|reply]`", quote=True)

    result = await activate_pro_plan(user_id)
    if result == "already_active":
        return await message.reply("💎 User already has an active Pro plan.")
    elif result:
        await message.reply(f"✅ Pro plan activated for `{user_id}`.")
        await notify_user_plan_activated(client, user_id, "Pro")
    else:
        await message.reply("❌ Failed to activate Pro plan. User not registered.")

@Client.on_message(filters.command("elite") & (filters.private | filters.group))
async def handle_elite(client, message: Message):
    if not is_owner(message.from_user.id):
        return await message.reply("⛔ Only the owner can activate plans.")

    if is_facility_owner(message.from_user.id):
        return await message.reply("⛔ Facility owners cannot provide plans to other users.")

    user_id = extract_user_id(message)
    if not user_id:
        return await message.reply("❗Usage: `/elite [user_id|@username|reply]`", quote=True)

    result = await activate_elite_plan(user_id)
    if result == "already_active":
        return await message.reply("🔷 User already has an active Elite plan.")
    elif result:
        await message.reply(f"✅ Elite plan activated for `{user_id}`.")
        await notify_user_plan_activated(client, user_id, "Elite")
    else:
        await message.reply("❌ Failed to activate Elite plan. User not registered.")

@Client.on_message(filters.command("vip") & (filters.private | filters.group))
async def handle_vip(client, message: Message):
    if not is_owner(message.from_user.id):
        return await message.reply("⛔ Only the owner can activate plans.")

    if is_facility_owner(message.from_user.id):
        return await message.reply("⛔ Facility owners cannot provide plans to other users.")

    user_id = extract_user_id(message)
    if not user_id:
        return await message.reply("❗Usage: `/vip [user_id|@username|reply]`", quote=True)

    result = await activate_vip_plan(user_id)
    if result == "already_active":
        return await message.reply("👑 User already has an active VIP plan.")
    elif result:
        await message.reply(f"✅ VIP plan activated for `{user_id}`.")
        await notify_user_plan_activated(client, user_id, "VIP")
    else:
        await message.reply("❌ Failed to activate VIP plan. User not registered.")

@Client.on_message(filters.command("ult") & (filters.private | filters.group))
async def handle_ult(client, message: Message):
    if not is_owner(message.from_user.id):
        return await message.reply("⛔ Only the owner can activate plans.")

    if is_facility_owner(message.from_user.id):
        return await message.reply("⛔ Facility owners cannot provide plans to other users.")

    user_id = extract_user_id(message)
    if not user_id:
        return await message.reply("❗Usage: `/ult [user_id|@username|reply]`", quote=True)

    result = await activate_ult_plan(user_id)
    if result == "already_active":
        return await message.reply("👑 User already has an active ULTIMATE plan.")
    elif result:
        await message.reply(f"✅ ULTIMATE plan activated for `{user_id}`.")
        await notify_user_plan_activated(client, user_id, "VIP")
    else:
        await message.reply("❌ Failed to activate ULTIMATE plan. User not registered.")

@Client.on_message(filters.command("setfacility") & filters.private)
async def set_facility_owner(client, message: Message):
    """Mark a user as facility owner (restricted from giving plans)"""
    if not is_owner(message.from_user.id):
        return await message.reply("⛔ Only the main owner can set facility owners.")

    user_id = extract_user_id(message)
    if not user_id:
        return await message.reply("❗Usage: `/setfacility [user_id|@username|reply]`", quote=True)

    users = load_users()
    if str(user_id) not in users:
        return await message.reply("❌ User not registered in the system.")

    users[str(user_id)]["facility_owner"] = True
    save_users(users)

    await message.reply(f"✅ User `{user_id}` has been marked as a facility owner.\nThey can no longer provide plans to other users.")

@Client.on_message(filters.command("unsetfacility") & filters.private)
async def unset_facility_owner(client, message: Message):
    """Remove facility owner restriction from a user"""
    if not is_owner(message.from_user.id):
        return await message.reply("⛔ Only the main owner can unset facility owners.")

    user_id = extract_user_id(message)
    if not user_id:
        return await message.reply("❗Usage: `/unsetfacility [user_id|@username|reply]`", quote=True)

    users = load_users()
    if str(user_id) not in users:
        return await message.reply("❌ User not registered in the system.")

    users[str(user_id)]["facility_owner"] = False
    save_users(users)

    await message.reply(f"✅ Facility owner restriction removed from user `{user_id}`.\nThey can now provide plans if they have owner permissions.")

@Client.on_message(filters.command("listfacility") & filters.private)
async def list_facility_owners(client, message: Message):
    """List all facility owners"""
    if not is_owner(message.from_user.id):
        return await message.reply("⛔ Only the main owner can view facility owners.")

    users = load_users()
    facility_owners = []

    for user_id, user_data in users.items():
        if user_data.get("facility_owner", False):
            username = user_data.get("username", "N/A")
            first_name = user_data.get("first_name", "Unknown")
            facility_owners.append(f"• `{user_id}` - {first_name} (@{username})")

    if not facility_owners:
        return await message.reply("📋 No facility owners found.")

    facility_list = "\n".join(facility_owners)
    await message.reply(f"<b>📋 Facility Owners (Restricted from giving plans):</b>\n\n{facility_list}")
