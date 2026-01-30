"""
/testsh - Shopify gate diagnostic command.
Runs the gate flow step-by-step and writes parsing/token extraction results to a text file for debugging CHECKOUT_TOKENS_MISSING and related errors.
"""

import os
import re
import time
from datetime import datetime
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatType

from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access
from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.bulletproof_session import BulletproofSession
from BOT.Charge.Shopify.slf.api import run_shopify_checkout_diagnostic
from BOT.Charge.Shopify.slf.site_manager import get_user_sites, get_primary_site
from BOT.tools.proxy import get_rotating_proxy


def _format_diagnostic_to_text(data: dict) -> str:
    """Format diagnostic dict to a readable text file."""
    lines = []
    lines.append("=" * 70)
    lines.append("SHOPIFY GATE DIAGNOSTIC (/testsh)")
    lines.append(f"Generated: {datetime.utcnow().isoformat()}Z")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"URL: {data.get('url', 'N/A')}")
    lines.append(f"Domain: {data.get('domain', 'N/A')}")
    if data.get("error"):
        lines.append(f"ERROR: {data['error']}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 1: Low-product API")
    lines.append("-" * 70)
    s1 = data.get("step1_low_product") or {}
    for k, v in s1.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 2: Products (/products.json)")
    lines.append("-" * 70)
    s2 = data.get("step2_products") or {}
    for k, v in s2.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 3: Cart add (POST /cart/add.js)")
    lines.append("-" * 70)
    s3 = data.get("step3_cart_add") or {}
    for k, v in s3.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 4: Checkout URL")
    lines.append("-" * 70)
    lines.append(f"  checkout_url: {data.get('step4_checkout_url', 'N/A')}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 5: Checkout page (GET checkout)")
    lines.append("-" * 70)
    s5 = data.get("step5_checkout_page") or {}
    for k, v in s5.items():
        if k == "snippet_first_500" and v:
            lines.append(f"  {k}: (length {len(v)})")
            lines.append("  --- snippet ---")
            lines.append(v[:800] if len(v) > 800 else v)
            lines.append("  --- end snippet ---")
        elif k == "snippet_meta_session" and v:
            lines.append(f"  {k}: (length {len(v)})")
            lines.append("  --- meta session snippet ---")
            lines.append(v)
            lines.append("  --- end ---")
        else:
            lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append(f"  checkout_text_length: {data.get('checkout_text_length', 0)}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 6: Token presence (substring in page)")
    lines.append("-" * 70)
    s6 = data.get("step6_token_presence") or {}
    for k, v in s6.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 7: _extract_checkout_tokens_robust() result")
    lines.append("-" * 70)
    s7 = data.get("step7_robust_tokens") or {}
    for k, v in s7.items():
        if v is None:
            lines.append(f"  {k}: None (MISSING)")
        else:
            lines.append(f"  {k}: len={v.get('len', 0)}, first_80={v.get('first_80', '')!r}")
            if v.get("value"):
                lines.append(f"      value_preview: {v.get('value', '')!r}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 8: Regex session token tests")
    lines.append("-" * 70)
    for i, t in enumerate(data.get("step8_regex_session_tests") or []):
        lines.append(f"  Test {i+1} ({t.get('name', '')}): matched={t.get('matched')}, group1_len={t.get('group1_len', 0)}")
        if t.get("group1_first80"):
            lines.append(f"    group1_first80: {t.get('group1_first80')!r}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 9: Capture session token (prefix/suffix)")
    lines.append("-" * 70)
    for i, t in enumerate(data.get("step9_capture_session_tests") or []):
        lines.append(f"  Test {i+1}: prefix={t.get('prefix', '')!r}, suffix={t.get('suffix', '')!r}")
        lines.append(f"    result_len={t.get('result_len', 0)}, result_first80={t.get('result_first80')!r}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("STEP 10: Capture source token (prefix/suffix)")
    lines.append("-" * 70)
    for i, t in enumerate(data.get("step10_capture_source_tests") or []):
        lines.append(f"  Test {i+1}: prefix={t.get('prefix', '')!r}, suffix={t.get('suffix', '')!r}")
        lines.append(f"    result_len={t.get('result_len', 0)}, result_first80={t.get('result_first80')!r}")
    lines.append("")
    lines.append("=" * 70)
    lines.append("END DIAGNOSTIC")
    lines.append("=" * 70)
    return "\n".join(lines)


def _get_test_url(message: Message) -> Optional[str]:
    """Get URL from command args or user's first saved site."""
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        url = parts[1].strip()
        if "://" in url or url.startswith("www.") or "." in url:
            return url if "://" in url else "https://" + url
    user_id = str(message.from_user.id) if message.from_user else ""
    sites = get_user_sites(user_id)
    sites = [s for s in sites if s.get("active", True)]
    if sites:
        primary = get_primary_site(user_id)
        if primary and primary.get("url"):
            return (primary.get("url") or "").strip()
        return (sites[0].get("url") or "").strip()
    return None


@Client.on_message(filters.command(["testsh"]) & filters.private)
async def handle_testsh(client: Client, message: Message):
    """
    /testsh [URL]
    Run Shopify gate diagnostic: products -> cart -> checkout page -> token parsing.
    Writes each step and parsing result to a text file and sends it.
    If URL omitted, uses your first saved site.
    """
    try:
        if not await check_private_access(message):
            return
        users = load_users()
        user_id = str(message.from_user.id) if message.from_user else ""
        if user_id not in users:
            await message.reply(
                "<code>Register first with /register</code>",
                reply_to_message_id=message.id,
            )
            return
        url = _get_test_url(message)
        if not url:
            await message.reply(
                "<b>No site to test.</b>\n"
                "Usage: <code>/testsh https://store.myshopify.com</code>\n"
                "Or add a site with /addurl then run <code>/testsh</code>.",
                reply_to_message_id=message.id,
            )
            return
        status_msg = await message.reply(
            f"<code>Running diagnostic for {url} ...</code>\n"
            "Fetching products → cart → checkout page → parsing tokens. This may take 30–60s.",
            reply_to_message_id=message.id,
        )
        try:
            proxy = get_rotating_proxy(int(user_id)) if user_id.isdigit() else get_rotating_proxy(user_id)
        except Exception:
            proxy = None
        try:
            async with BulletproofSession(timeout_seconds=90, proxy=proxy, use_playwright=False) as session:
                data = await run_shopify_checkout_diagnostic(url, session, proxy)
        except Exception as e:
            data = {"url": url, "domain": "", "error": str(e)}
        os.makedirs("DATA", exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"testsh_{user_id}_{ts}.txt"
        filepath = os.path.join("DATA", filename)
        text_content = _format_diagnostic_to_text(data)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text_content)
        await status_msg.edit_text(
            f"<code>Diagnostic done.</code> Sending results file..."
        )
        await message.reply_document(
            document=filepath,
            caption=f"<b>/testsh</b> diagnostic for <code>{url}</code>\n"
            f"Check STEP 6 (token presence), STEP 7 (robust_tokens), STEP 8–10 (regex/capture).",
            reply_to_message_id=message.id,
        )
        try:
            os.remove(filepath)
        except Exception:
            pass
    except Exception as e:
        await message.reply(
            f"<code>Error: {e}</code>",
            reply_to_message_id=message.id,
        )
