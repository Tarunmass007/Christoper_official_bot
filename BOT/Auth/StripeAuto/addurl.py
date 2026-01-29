"""
Stripe Auto Auth - Add URL (/sturl, /murl)
==========================================
Add WooCommerce Stripe Auth sites. Validates with test run before saving.
/sturl <url> - single URL
/murl <url1> <url2> ... or reply to message with URLs or reply to .txt file with URLs
Does NOT mingle with Shopify /addurl or existing Stripe Auth /au gate.
"""

import os
import re
import time
import asyncio
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from BOT.helper.start import load_users
from BOT.db.store import add_stripe_auth_site, get_stripe_auth_sites, get_primary_stripe_auth_site, clear_stripe_auth_sites
from BOT.tools.proxy import get_rotating_proxy
from BOT.Auth.StripeAuto.api import auto_stripe_auth
from BOT.Auth.StripeAuto.response import determine_stripe_auto_status

# Test card for validation (live-mode compatible; used when adding site via /sturl or /murl)
TEST_CARD = "5598880328708591|05|2029|362"


def normalize_stripe_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc or parsed.path.split("/")[0]
        return f"https://{netloc}"
    except Exception:
        return url


def extract_urls(text: str) -> List[str]:
    """Extract all URLs from text (message or file content). No limit; accurate detection."""
    if not text or not isinstance(text, str):
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    seen: set = set()
    out: List[str] = []

    # 1) Full URL with scheme (strip trailing punctuation)
    for m in re.finditer(r"https?://[^\s<>\"{}|\\^`\[\]\s]+", text, re.IGNORECASE):
        u = m.group(0).rstrip(".,;:)>\"]'").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    # 2) www. or domain.tld without scheme (one per line or space-separated)
    for m in re.finditer(
        r"(?:www\.|[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}(?:/[^\s<>\"{}|\\^`\[\]\s]*)?",
        text,
    ):
        u = m.group(0).rstrip(".,;:)>\"]'").strip()
        if u and len(u) > 4 and not u.startswith("http"):
            canonical = "https://" + u.lstrip("/")
            if canonical not in seen:
                seen.add(canonical)
                out.append(canonical)

    if out:
        return list(dict.fromkeys(out))
    # 3) Fallback: bare domains
    for m in re.finditer(r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}", text):
        d = m.group(0)
        if len(d) > 4:
            canonical = "https://" + d
            if canonical not in seen:
                seen.add(canonical)
                out.append(canonical)
    return list(dict.fromkeys(out))


async def validate_stripe_auth_site(url: str, proxy: Optional[str] = None, max_retries: int = 2) -> tuple[bool, Dict]:
    """Run test card; return (valid, result). Valid = APPROVED or CCN LIVE."""
    for _ in range(max_retries):
        try:
            res = await auto_stripe_auth(url, TEST_CARD, session=None, proxy=proxy, timeout_seconds=50)
            status = determine_stripe_auto_status(res)
            if status in ("APPROVED", "CCN LIVE"):
                return True, res
            return False, res
        except Exception as e:
            if _ == max_retries - 1:
                return False, {"response": "ERROR", "message": str(e)[:80]}
        await asyncio.sleep(0.5)
    return False, {"response": "ERROR", "message": "Validation failed"}


@Client.on_message(filters.command(["sturl"]))
async def sturl_handler(client: Client, message: Message):
    """Add single Stripe Auth site. /sturl https://yoursite.com"""
    if not message.from_user:
        return
    user_id = str(message.from_user.id)
    users = load_users()
    if user_id not in users:
        return await message.reply(
            "<pre>Access Denied 🚫</pre>\n<b>Register first:</b> <code>/register</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
    args = message.command[1:]
    if not args:
        return await message.reply(
            "<pre>Stripe Auto - Add Site</pre>\n━━━━━━━━━━━━━\n<b>Usage:</b> <code>/sturl https://yoursite.com</code>\n<b>Example:</b> <code>/sturl www.melearning.co.uk</code>\n\n<b>After adding:</b> Use <code>/starr</code> to check cards.\n<b>Mass add:</b> <code>/murl url1 url2</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
    url = normalize_stripe_url(args[0])
    status_msg = await message.reply(
        f"<pre>Validating Stripe Auth Site...</pre>\n<b>URL:</b> <code>{url}</code>\n<b>Status:</b> <i>Running test auth...</i>",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML,
    )
    start = time.time()
    proxy = get_rotating_proxy(int(user_id))
    valid, res = await validate_stripe_auth_site(url, proxy)
    elapsed = round(time.time() - start, 2)
    if not valid:
        err = res.get("message", res.get("response", "Unknown"))[:60]
        return await status_msg.edit_text(
            f"<pre>Invalid Site ❌</pre>\n━━━━━━━━━━━━━\n<b>URL:</b> <code>{url}</code>\n<b>Error:</b> <code>{err}</code>\n\n<b>Tip:</b> Use a WooCommerce site with Stripe/WC Payments add-payment-method.\n<b>Time:</b> <code>{elapsed}s</code>",
            parse_mode=ParseMode.HTML,
        )
    add_stripe_auth_site(user_id, url, set_primary=True)
    await status_msg.edit_text(
        f"<pre>Stripe Auth Site Added ✅</pre>\n━━━━━━━━━━━━━\n<b>Site:</b> <code>{url}</code>\n<b>Status:</b> Test auth passed\n<b>Command:</b> <code>/starr</code> (reply to CC)\n━━━━━━━━━━━━━\n<b>Time:</b> <code>{elapsed}s</code>",
        parse_mode=ParseMode.HTML,
    )


async def _get_murl_urls(client: Client, message: Message) -> List[str]:
    """Get URLs for murl: from command args, reply text, or replied .txt file."""
    args = list(message.command[1:])
    if message.reply_to_message:
        if message.reply_to_message.text:
            args = extract_urls(message.reply_to_message.text)
        elif message.reply_to_message.document:
            doc = message.reply_to_message.document
            fname = (doc.file_name or "").lower()
            if fname.endswith(".txt"):
                path = None
                try:
                    path = await client.download_media(message.reply_to_message)
                    if path and os.path.isfile(path):
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        args = extract_urls(content)
                except Exception:
                    pass
                finally:
                    if path and os.path.isfile(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass
    return args


@Client.on_message(filters.command(["murl"]))
async def murl_handler(client: Client, message: Message):
    """Add multiple Stripe Auth sites. /murl url1 url2 or reply to message or .txt file with URLs."""
    if not message.from_user:
        return
    user_id = str(message.from_user.id)
    users = load_users()
    if user_id not in users:
        return await message.reply(
            "<pre>Access Denied 🚫</pre>\n<b>Register first:</b> <code>/register</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
    args = await _get_murl_urls(client, message)
    if not args:
        return await message.reply(
            "<pre>Stripe Auto - Mass Add</pre>\n<b>Usage:</b> <code>/murl url1 url2 url3</code> or reply to a message/.txt file with URLs.",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
    urls = [normalize_stripe_url(u) for u in args]
    status_msg = await message.reply(
        f"<pre>Validating {len(urls)} site(s)...</pre>\n<b>Status:</b> <i>Testing auth...</i>",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML,
    )
    start = time.time()
    proxy = get_rotating_proxy(int(user_id))
    added = 0
    failed = []
    total_urls = len(urls)
    for i, url in enumerate(urls):
        # Throttle progress updates: every 5 URLs or first/last to avoid rate limits
        try:
            if i == 0 or i == total_urls - 1 or (i + 1) % 5 == 0:
                await status_msg.edit_text(
                    f"<pre>Validating...</pre>\n<b>Progress:</b> <code>{i + 1}/{total_urls}</code>\n<b>Current:</b> <code>{url[:45]}...</code>" if len(url) > 45 else f"<pre>Validating...</pre>\n<b>Progress:</b> <code>{i + 1}/{total_urls}</code>\n<b>Current:</b> <code>{url}</code>",
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            pass
        valid, _ = await validate_stripe_auth_site(url, proxy, max_retries=1)
        if valid:
            add_stripe_auth_site(user_id, url, set_primary=(added == 0))
            added += 1
        else:
            failed.append(url[:35])
    elapsed = round(time.time() - start, 2)
    if added == 0:
        await status_msg.edit_text(
            f"<pre>No valid sites ❌</pre>\n<b>Checked:</b> <code>{len(urls)}</code>\n<b>Failed:</b> All (WooCommerce Stripe add-payment-method required)\n<b>Time:</b> <code>{elapsed}s</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    lines = [
        f"<pre>Stripe Auth sites added ✅</pre>",
        "━━━━━━━━━━━━━",
        f"<b>• Added:</b> <code>{added}</code>",
        f"<b>• Failed:</b> <code>{len(failed)}</code>",
        f"<b>• Command:</b> <code>/starr</code>",
        f"<b>• Time:</b> <code>{elapsed}s</code>",
    ]
    if failed:
        lines.append(f"\n<b>Failed:</b> {', '.join(failed[:5])}")
    await status_msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


@Client.on_message(filters.command(["mystarrsite", "starrsite"]))
async def mystarrsite_handler(client: Client, message: Message):
    """Show current Stripe Auto Auth site."""
    if not message.from_user:
        return
    user_id = str(message.from_user.id)
    users = load_users()
    if user_id not in users:
        return await message.reply(
            "<pre>Access Denied 🚫</pre>\n<b>Register first:</b> <code>/register</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
    site = get_primary_stripe_auth_site(user_id)
    sites = get_stripe_auth_sites(user_id)
    if not site:
        return await message.reply(
            "<pre>No Stripe Auth site</pre>\n<b>Add one:</b> <code>/sturl https://yoursite.com</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
    lines = [
        f"<pre>Stripe Auto Auth Site</pre>",
        "━━━━━━━━━━━━━",
        f"<b>• Current:</b> <code>{site.get('url', '')}</code>",
        f"<b>• Total saved:</b> <code>{len(sites)}</code>",
        f"<b>• Check:</b> <code>/starr</code> (reply to CC)",
    ]
    await message.reply("\n".join(lines), reply_to_message_id=message.id, parse_mode=ParseMode.HTML)


@Client.on_message(filters.command(["clearstarr", "delstarrsite"]))
async def clearstarr_handler(client: Client, message: Message):
    """Clear all saved Stripe Auth sites for user."""
    if not message.from_user:
        return
    user_id = str(message.from_user.id)
    n = clear_stripe_auth_sites(user_id)
    await message.reply(
        f"<pre>Stripe Auth sites cleared</pre>\n<b>Removed:</b> <code>{n}</code> site(s).\nAdd again with <code>/sturl</code>.",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML,
    )
