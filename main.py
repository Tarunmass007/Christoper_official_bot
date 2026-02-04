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

    # Register bot commands for search bar pop-up (menu when user types /)
    commands = [
        # Basic
        BotCommand("start", "Start the bot"),
        BotCommand("register", "Register to use the bot"),
        BotCommand("cmds", "Commands & gates menu"),
        BotCommand("help", "Help & command list"),
        BotCommand("ping", "Check bot latency"),
        BotCommand("info", "User / chat info"),
        BotCommand("groupid", "Get group or chat ID"),
        BotCommand("id", "Get chat ID (alias)"),
        # Auth gates
        BotCommand("au", "Stripe Auth single check"),
        BotCommand("mau", "Stripe Auth mass (reply)"),
        BotCommand("starr", "Stripe Auto Auth single"),
        BotCommand("mstarr", "Stripe Auto Auth mass (reply / .txt)"),
        BotCommand("b3", "Braintree Auth check"),
        # Charge gates
        BotCommand("sh", "Shopify charge (your site)"),
        BotCommand("msh", "Shopify mass (reply)"),
        BotCommand("tsh", "Shopify TXT sites check"),
        BotCommand("st", "Stripe $20 charge single"),
        BotCommand("mst", "Stripe $20 mass (reply)"),
        BotCommand("sc", "Stripe Worker single check"),
        BotCommand("msc", "Stripe Worker mass (reply / .txt)"),
        BotCommand("yo", "Sam's Club Plus check (8 runners)"),
        BotCommand("br", "Braintree charge check"),
        BotCommand("bt", "Braintree CVV check"),
        BotCommand("mbt", "Braintree CVV mass"),
        # Site management
        BotCommand("addurl", "Add Shopify site"),
        BotCommand("txturl", "Add sites (text or file)"),
        BotCommand("txtls", "List TXT sites"),
        BotCommand("mysite", "View current site"),
        BotCommand("delsite", "Remove saved site"),
        BotCommand("remurl", "Remove site (alias)"),
        BotCommand("sturl", "Add Stripe Auto site"),
        BotCommand("murl", "Add Stripe Auto sites (mass)"),
        BotCommand("mystarrsite", "View Stripe Auto site"),
        BotCommand("swurls", "List Stripe Auth sites"),
        BotCommand("dsturl", "Delete Stripe Auth site"),
        BotCommand("clearstarr", "Clear Stripe Auth sites"),
        BotCommand("rurl", "Remove TXT sites"),
        BotCommand("clearurl", "Clear all sites"),
        BotCommand("showsitetxt", "Download site list (TXT)"),
        # Tools
        BotCommand("bin", "BIN lookup"),
        BotCommand("mbin", "Mass BIN lookup"),
        BotCommand("vbv", "VBV check"),
        BotCommand("mvbv", "Mass VBV check"),
        BotCommand("mbv", "MBV SecureCode check"),
        BotCommand("mmbv", "Mass MBV check"),
        BotCommand("gen", "Generate cards"),
        BotCommand("mod", "Modify card format"),
        BotCommand("fake", "Generate fake identity"),
        BotCommand("setpx", "Set proxy"),
        BotCommand("getpx", "View proxy"),
        BotCommand("delpx", "Delete proxy"),
        BotCommand("checkproxy", "Test proxies"),
        BotCommand("fl", "Filter cards (reply)"),
        BotCommand("geterrors", "Get error CCs file"),
        BotCommand("dork", "Find Shopify stores (private)"),
        BotCommand("changegate", "Change Stripe Auth gate"),
        BotCommand("testsh", "Shopify gate test (debug)"),
        # Plans & redeem
        BotCommand("plans", "View plans"),
        BotCommand("buy", "Buy credits / plan"),
        BotCommand("red", "Redeem code"),
        BotCommand("redeem", "Redeem plan key"),
        BotCommand("requestplan", "Request a plan"),
        BotCommand("myrequests", "Your plan requests"),
        BotCommand("cancelrequest", "Cancel plan request"),
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
