import json
import os
import asyncio
import threading

from dotenv import load_dotenv
load_dotenv()

from pyrogram import Client, idle
from pyrogram.types import BotCommand
from flask import Flask
from BOT.plans.plan1 import check_and_expire_plans as plan1_expiry
from BOT.plans.plan2 import check_and_expire_plans as plan2_expiry
from BOT.plans.plan3 import check_and_expire_plans as plan3_expiry
from BOT.plans.plan4 import check_and_expire_plans as plan4_expiry
from BOT.plans.redeem import check_and_expire_redeem_plans as redeem_expiry
from BOT.db.mongo import use_mongo, init_db, close_db, migrate_json_to_mongo

# Load bot credentials from FILES/config.json (existing implementation)
from BOT.config_loader import get_config
DATA = get_config()
API_ID = int(DATA.get("API_ID") or 0)
API_HASH = (DATA.get("API_HASH") or "").strip()
BOT_TOKEN = (DATA.get("BOT_TOKEN") or "").strip()
if not (API_ID and API_HASH and BOT_TOKEN):
    raise ValueError("Set BOT_TOKEN, API_ID, API_HASH in FILES/config.json.")

# Pyrogram plugins
plugins = dict(root="BOT")

# Pyrogram client
bot = Client(
    "MY_BOT",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=plugins
)

# Flask App
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", "3000"))
    app.run(host="0.0.0.0", port=port)

async def run_bot():
    if use_mongo():
        try:
            init_db()
            migrate_json_to_mongo()
            print("✅ MongoDB connected and ready.")
        except Exception as e:
            print(f"⚠️ MongoDB init failed: {e}. Using JSON storage.")
    await bot.start()
    print("✅ Bot is running...")

    # Register bot commands for autocomplete
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show help menu"),
        BotCommand("ping", "Check bot latency"),
        BotCommand("info", "Get user information"),
        BotCommand("cmds", "View all commands"),
        BotCommand("bin", "Check BIN information"),
        BotCommand("mbin", "Mass BIN lookup"),
        BotCommand("fake", "Generate fake identity"),
        BotCommand("gen", "Generate card numbers"),
        BotCommand("mod", "Modify card numbers"),
        BotCommand("sh", "Shopify charge"),
        BotCommand("msh", "Mass Shopify charge"),
        BotCommand("tsh", "Test Shopify"),
        BotCommand("tslf", "Test SLF"),
        BotCommand("testsh", "Shopify gate diagnostic (debug file)"),
        BotCommand("br", "Braintree checker"),
        BotCommand("st", "Stripe $20 charge"),
        BotCommand("register", "Register with the bot"),
        BotCommand("changegate", "Change Stripe Auth gate"),
        BotCommand("dork", "Find low checkout Shopify stores"),
        BotCommand("au", "Stripe Auth $0 check"),
        BotCommand("mau", "Stripe Auth mass check"),
        BotCommand("vbv", "VBV verification check"),
        BotCommand("mvbv", "Mass VBV verification check"),
        BotCommand("mbv", "MBV SecureCode verification check"),
        BotCommand("mmbv", "Mass MBV SecureCode verification check"),
        BotCommand("bt", "Braintree CVV check"),
        BotCommand("mbt", "Mass Braintree CVV check"),
        BotCommand("plans", "View available plans"),
        BotCommand("requestplan", "Request a plan"),
        BotCommand("myrequests", "View your plan requests"),
        BotCommand("cancelrequest", "Cancel a plan request"),
        BotCommand("redeem", "Redeem a plan key"),
        BotCommand("setpx", "Set proxy"),
        BotCommand("getpx", "Get current proxy"),
        BotCommand("checkproxy", "Test saved proxies"),
        BotCommand("delpx", "Delete proxy"),
        BotCommand("groupid", "Get group/chat ID"),
        BotCommand("fl", "Apply filter (reply to message)"),
        BotCommand("fback", "Send feedback (reply to message)"),
        BotCommand("addurl", "Add Shopify site for checking"),
        BotCommand("slfurl", "Add Shopify site (alias)"),
        BotCommand("sturl", "Add Stripe Auto Auth site (single)"),
        BotCommand("murl", "Add Stripe Auto Auth sites (mass)"),
        BotCommand("starr", "Stripe Auto Auth check (reply to CC)"),
        BotCommand("mstarr", "Stripe Auto Auth mass check"),
        BotCommand("geterrors", "Get error CCs file (mau|mstarr|msh|tsh)"),
        BotCommand("mysite", "View your current site"),
        BotCommand("mystarrsite", "View Stripe Auto Auth site"),
        BotCommand("swurls", "List all Stripe Auth sites (rotation)"),
        BotCommand("dsturl", "Delete one Stripe Auth site (url or index)"),
        BotCommand("clearstarr", "Clear all Stripe Auth sites"),
        BotCommand("delsite", "Remove your saved site"),
        BotCommand("txturl", "Add multiple sites (text or TXT file)"),
        BotCommand("txtls", "List your sites (up to 20)"),
        BotCommand("showsitetxt", "Get full site list as TXT file"),
        BotCommand("rurl", "Remove TXT sites"),
        BotCommand("clearurl", "Clear all saved sites"),
    ]

    await bot.set_bot_commands(commands)
    print("✅ Bot commands registered for autocomplete")

    # Background plan expiry tasks
    asyncio.create_task(plan1_expiry(bot))
    asyncio.create_task(plan2_expiry(bot))
    asyncio.create_task(plan3_expiry(bot))
    asyncio.create_task(plan4_expiry(bot))
    asyncio.create_task(redeem_expiry(bot))

    await idle()
    await bot.stop()
    if use_mongo():
        close_db()
        print("✅ MongoDB connection closed.")
    print("❌ Bot stopped.")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    # Run Flask in a separate thread
    threading.Thread(target=run_flask).start()

    # Start bot loop
    asyncio.run(run_bot())
