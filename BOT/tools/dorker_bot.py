"""
Telegram Bot Integration for Shopify Dorker
============================================
Adds /dork command to the bot for finding low checkout Shopify stores.
"""

import asyncio
import json
import os
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from BOT.tools.dorker import dork_shopify_stores, DORK_QUERIES
from BOT.helper.start import load_users, load_owner_id
from BOT.helper.permissions import check_private_access

DORK_RESULTS_FILE = "DATA/dorked_stores.json"
user_dorking = {}  # Track active dorking sessions


@Client.on_message(filters.command("dork") & filters.private)
async def dork_command(client: Client, message: Message):
    """Handle /dork command for finding Shopify stores."""
    if not message.from_user:
        return
    
    user_id = str(message.from_user.id)
    
    # Check if user is registered
    users = load_users()
    if user_id not in users:
        return await message.reply(
            """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
            parse_mode=ParseMode.HTML
        )
    
    # Check private access
    if not await check_private_access(message):
        return
    
    # Check if already dorking
    if user_id in user_dorking:
        return await message.reply(
            """<pre>⚠️ Wait!</pre>
<b>Your previous dorking session is still running.</b>
<b>Please wait until it finishes.</b>""",
            parse_mode=ParseMode.HTML
        )
    
    user_dorking[user_id] = True
    
    try:
        # Get optional parameters
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        # Parse arguments
        max_stores = 20  # Default
        use_captcha = False
        captcha_key = None
        
        for i, arg in enumerate(args):
            if arg == "--max" and i + 1 < len(args):
                try:
                    max_stores = int(args[i + 1])
                    max_stores = min(max_stores, 100)  # Cap at 100
                except ValueError:
                    pass
            elif arg == "--2captcha" and i + 1 < len(args):
                captcha_key = args[i + 1]
                use_captcha = True
            elif arg == "--help":
                return await message.reply(
                    """<pre>📖 Dorker Help</pre>
━━━━━━━━━━━━━━━
<b>Usage:</b> <code>/dork [options]</code>

<b>Options:</b>
• <code>--max [number]</code> - Maximum stores to find (default: 20, max: 100)
• <code>--2captcha [api_key]</code> - 2Captcha API key for captcha bypass
• <code>--help</code> - Show this help

<b>Examples:</b>
<code>/dork</code> - Find 20 stores (default)
<code>/dork --max 50</code> - Find up to 50 stores
<code>/dork --2captcha YOUR_API_KEY</code> - Use captcha bypass

<b>Note:</b> Dorking may take several minutes. Be patient!""",
                    parse_mode=ParseMode.HTML
                )
        
        # Send initial message
        status_msg = await message.reply(
            f"""<pre>🔍 Dorking Shopify Stores...</pre>
━━━━━━━━━━━━━━━
<b>• Status:</b> <code>Starting search...</code>
<b>• Max Stores:</b> <code>{max_stores}</code>
<b>• Captcha Bypass:</b> <code>{'✅ Enabled' if use_captcha else '❌ Disabled'}</code>
━━━━━━━━━━━━━━━
<i>This may take a few minutes. Please wait...</i>""",
            parse_mode=ParseMode.HTML
        )
        
        # Run dorking
        try:
            stores = await dork_shopify_stores(
                captcha_api_key_2captcha=captcha_key if use_captcha else None,
                max_stores=max_stores
            )
        except Exception as e:
            await status_msg.edit(
                f"""<pre>❌ Dorking Failed</pre>
━━━━━━━━━━━━━━━
<b>Error:</b> <code>{str(e)[:100]}</code>
━━━━━━━━━━━━━━━""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Save results
        os.makedirs("DATA", exist_ok=True)
        with open(DORK_RESULTS_FILE, "w") as f:
            json.dump(stores, f, indent=2)
        
        # Format results
        if not stores:
            await status_msg.edit(
                """<pre>❌ No Stores Found</pre>
━━━━━━━━━━━━━━━
<b>No verified low-checkout stores found.</b>
<b>Try again later or adjust search parameters.</b>
━━━━━━━━━━━━━━━""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Create results message
        results_text = f"""<pre>✅ Dorking Complete</pre>
━━━━━━━━━━━━━━━
<b>• Found:</b> <code>{len(stores)} verified stores</code>
<b>• Status:</b> <code>Success</code>
━━━━━━━━━━━━━━━

<b>📋 Top Stores:</b>
"""
        
        # Show top 10 stores
        sorted_stores = sorted(stores, key=lambda x: x.get('min_price', 999))[:10]
        for i, store in enumerate(sorted_stores, 1):
            store_name = store.get('store_name', 'Unknown')[:30]
            url = store.get('url', '')[:50]
            min_price = store.get('min_price', 0)
            results_text += f"<b>{i}.</b> <code>{store_name}</code>\n"
            results_text += f"   💰 <code>${min_price:.2f}</code> | <code>{url}</code>\n\n"
        
        results_text += f"""━━━━━━━━━━━━━━━
<b>💡 Tip:</b> Use <code>/addurl</code> to add stores to your list.
<b>📁 Results saved to:</b> <code>DATA/dorked_stores.json</code>
━━━━━━━━━━━━━━━"""
        
        # Create keyboard with action buttons
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📥 Download Results", callback_data=f"dork_download_{user_id}"),
                InlineKeyboardButton("➕ Add All", callback_data=f"dork_addall_{user_id}")
            ],
            [
                InlineKeyboardButton("🔄 Dork Again", callback_data="dork_again"),
                InlineKeyboardButton("❌ Close", callback_data="dork_close")
            ]
        ])
        
        await status_msg.edit(
            results_text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        await message.reply(
            f"""<pre>❌ Error</pre>
<b>Error:</b> <code>{str(e)[:200]}</code>""",
            parse_mode=ParseMode.HTML
        )
    finally:
        user_dorking.pop(user_id, None)


@Client.on_callback_query(filters.regex(r"^dork_download_(\d+)$"))
async def dork_download_callback(client: Client, cq):
    """Download dorked stores as file."""
    try:
        user_id = str(cq.from_user.id)
        callback_user_id = cq.matches[0].group(1) if cq.matches else None
        
        if callback_user_id != user_id:
            await cq.answer("❌ Access denied", show_alert=True)
            return
        
        if not os.path.exists(DORK_RESULTS_FILE):
            await cq.answer("❌ No results found", show_alert=True)
            return
        
        # Read and format results
        with open(DORK_RESULTS_FILE, "r") as f:
            stores = json.load(f)
        
        # Create text file
        text_content = "Shopify Stores Found by Dorker\n"
        text_content += "=" * 50 + "\n\n"
        
        for i, store in enumerate(stores, 1):
            text_content += f"{i}. {store.get('store_name', 'Unknown')}\n"
            text_content += f"   URL: {store.get('url', 'N/A')}\n"
            text_content += f"   Min Price: ${store.get('min_price', 0):.2f}\n"
            text_content += f"   Max Price: ${store.get('max_price', 0):.2f}\n"
            text_content += "\n"
        
        # Send as document
        await client.send_document(
            cq.from_user.id,
            document=text_content.encode(),
            file_name=f"dorked_stores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            caption="📥 Dorked Shopify Stores"
        )
        
        await cq.answer("✅ Results sent!", show_alert=False)
        
    except Exception as e:
        await cq.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)


@Client.on_callback_query(filters.regex(r"^dork_addall_(\d+)$"))
async def dork_addall_callback(client: Client, cq):
    """Add all dorked stores to user's site list."""
    try:
        user_id = str(cq.from_user.id)
        callback_user_id = cq.matches[0].group(1) if cq.matches else None
        
        if callback_user_id != user_id:
            await cq.answer("❌ Access denied", show_alert=True)
            return
        
        if not os.path.exists(DORK_RESULTS_FILE):
            await cq.answer("❌ No results found", show_alert=True)
            return
        
        # Read stores
        with open(DORK_RESULTS_FILE, "r") as f:
            stores = json.load(f)
        
        # Import site manager functionality
        from BOT.Charge.Shopify.slf.site_manager import add_site_for_user
        
        added_count = 0
        for store in stores:
            url = store.get('url', '')
            if url:
                try:
                    # Add store to user's list
                    # Format: add_site_for_user(user_id, url, gateway, price, set_primary)
                    min_price = store.get('min_price', 0)
                    price_str = f"{min_price:.2f}" if min_price > 0 else "N/A"
                    gateway = f"Shopify Normal ${price_str}" if price_str != "N/A" else "Shopify Normal"
                    success = add_site_for_user(user_id, url, gateway, price_str, set_primary=False)
                    if success:
                        added_count += 1
                except Exception as e:
                    print(f"Error adding store {url}: {e}")
                    continue
        
        await cq.answer(f"✅ Added {added_count} stores to your list!", show_alert=True)
        
    except Exception as e:
        await cq.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)


@Client.on_callback_query(filters.regex("^dork_again$"))
async def dork_again_callback(client: Client, cq):
    """Start dorking again."""
    await cq.answer("Use /dork command to start again", show_alert=False)


@Client.on_callback_query(filters.regex("^dork_close$"))
async def dork_close_callback(client: Client, cq):
    """Close dork results."""
    try:
        await cq.message.delete()
        await cq.answer()
    except Exception:
        pass
