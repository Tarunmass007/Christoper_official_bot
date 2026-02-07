"""
Professional Shopify Site URL Handler (Unified)
Robust site validation with lowest product parsing for /addurl and /txturl commands.
Works in both private chats and groups.

Site-add flow (addurl / txturl):
1. Fetch /products.json → find lowest product (price, variant, gateway).
2. Run test checkout with current Shopify gate API (test card).
3. If ReceiptId is present → valid site → SAVE.
4. If ReceiptId is NOT present → invalid site → DO NOT SAVE.

Features:
- Lowest product price detection, gateway detection.
- Test check (ReceiptId) before saving; only verified sites stored.
- Unified site storage (store/MongoDB). Group and private chat support.
- Cloudscraper fallback for stickerdad.com and protected stores.
"""

import json
import time
import asyncio
import re
import random
import logging
from urllib.parse import urlparse
from typing import Optional, Dict, Any, Tuple, List

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.slf.api import autoshopify_with_captcha_retry
from BOT.tools.proxy import get_rotating_proxy
from BOT.helper.start import load_users

# Railway low-product API (same as gate) - used first for addurl/txturl to support digital/low-price products
LOW_PRODUCT_API_BASE = "https://shopify-api-new-production.up.railway.app"

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

from BOT.Charge.Shopify.slf.site_manager import (
    add_site_for_user,
    get_primary_site,
    get_user_sites,
    clear_user_sites,
)

def save_site_for_user_unified(user_id: str, site: str, gateway: str, price: str = "N/A") -> bool:
    """Save a site for a user using unified site manager; set as primary."""
    gate_name = f"Shopify Normal ${price}" if price and price != "N/A" else "Shopify Normal"
    return add_site_for_user(user_id, site, gate_name, price or "N/A", set_primary=True)


logger = logging.getLogger(__name__)

# Timeout configurations (fast for addurl/txturl)
FAST_TIMEOUT = 12
STANDARD_TIMEOUT = 22
MAX_RETRIES = 2
FETCH_RETRIES = 2
RAILWAY_API_TIMEOUT = 30  # Longer for Railway API (external service)
RAILWAY_API_RETRIES = 3   # Retries for stickerdad.com, protected stores

# Test card for addurl/txturl gate validation (Visa test)
TEST_CARD = "4111111111111111|12|2026|123"

# Currency symbols mapping
CURRENCY_SYMBOLS = {
    'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥', 'CNY': '¥',
    'INR': '₹', 'AUD': 'A$', 'CAD': 'C$', 'CHF': 'CHF', 'SGD': 'S$',
    'NZD': 'NZ$', 'MXN': 'MX$', 'BRL': 'R$', 'ZAR': 'R', 'AED': 'د.إ',
    'SEK': 'kr', 'NOK': 'kr', 'DKK': 'kr', 'PLN': 'zł', 'THB': '฿',
    'IDR': 'Rp', 'MYR': 'RM', 'PHP': '₱', 'HKD': 'HK$', 'KRW': '₩',
    'TRY': '₺', 'RUB': '₽', 'ILS': '₪', 'CZK': 'Kč', 'HUF': 'Ft'
}

# User agents pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# Gateway patterns
GATEWAY_PATTERNS = {
    "Shopify Payments": ["shopify payments", "normal"],
    "Stripe": ["stripe"],
    "PayPal": ["paypal", "braintree paypal"],
    "Braintree": ["braintree"],
    "Authorize.net": ["authorize", "authorizenet"],
    "Square": ["square"],
    "Klarna": ["klarna"],
    "Affirm": ["affirm"],
    "Afterpay": ["afterpay", "clearpay"],
    "Shop Pay": ["shop pay", "shoppay"],
}


def normalize_url(url: str) -> str:
    """Normalize and clean URL to standard format."""
    url = url.strip().lower()
    url = url.rstrip('/')
    for suffix in ['/products', '/collections', '/cart', '/checkout', '/pages']:
        if suffix in url:
            url = url.split(suffix)[0]
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        domain = domain.split(':')[0]
        return f"https://{domain}"
    except Exception:
        return url


def clean_domain(domain: str) -> str:
    """Clean and validate domain format."""
    domain = domain.replace('https://', '').replace('http://', '').strip('/')
    domain = domain.split('/')[0]
    domain = domain.lower()
    if not domain or len(domain) < 3:
        raise ValueError("Domain too short")
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$', domain):
        raise ValueError("Invalid domain format")
    return domain


def get_random_headers() -> Dict[str, str]:
    """Generate random but realistic browser headers."""
    ua = random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "sec-ch-ua": '"Chromium";v="120", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }


def _parse_products_json(raw: str) -> List[Dict]:
    """Robust JSON parse for products.json. Handles BOM, malformed edges."""
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    if text.startswith("\ufeff"):
        text = text[1:]
    if text.lstrip().startswith("<"):
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    products = data.get("products") if isinstance(data, dict) else None
    return products if isinstance(products, list) else []


def _fetch_products_cloudscraper_sync(base_url: str, proxy: Optional[str] = None) -> List[Dict]:
    """Sync fetch via cloudscraper (captcha bypass). Fallback when TLS fails. Longer timeout for stickerdad.com."""
    if not HAS_CLOUDSCRAPER:
        return []
    url = f"{base_url.rstrip('/')}/products.json?limit=100"
    timeout = max(FAST_TIMEOUT, RAILWAY_API_TIMEOUT - 5)  # 25s for Cloudflare-protected sites
    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        if proxy and str(proxy).strip():
            px = str(proxy).strip()
            if not px.startswith(("http://", "https://")):
                px = f"http://{px}"
            scraper.proxies = {"http": px, "https": px}
        r = scraper.get(url, timeout=timeout)
        if r.status_code != 200:
            return []
        return _parse_products_json(r.text)
    except Exception:
        return []


def extract_between(text: str, start_marker: str, end_marker: str) -> Optional[str]:
    """Extract string between two markers."""
    try:
        start_idx = text.index(start_marker) + len(start_marker)
        end_idx = text.index(end_marker, start_idx)
        return text[start_idx:end_idx]
    except (ValueError, IndexError):
        return None


def detect_gateway(page_content: str) -> str:
    """Detect payment gateway from page content."""
    content_lower = page_content.lower()
    gateway = extract_between(page_content, 'extensibilityDisplayName&quot;:&quot;', '&quot')
    if gateway:
        if gateway == "Shopify Payments":
            return "Normal"
        return gateway
    for gateway_name, patterns in GATEWAY_PATTERNS.items():
        for pattern in patterns:
            if pattern in content_lower:
                return gateway_name
    return "Unknown"


def get_currency_symbol(code: str) -> str:
    """Get currency symbol for code."""
    return CURRENCY_SYMBOLS.get(code.upper(), f"{code} ")


async def fetch_products_json(
    session: TLSAsyncSession,
    base_url: str,
    proxy: Optional[str] = None,
) -> List[Dict]:
    """Fetch products from Shopify /products.json. Session first, then cloudscraper fallback."""
    products: List[Dict] = []
    products_url = f"{base_url.rstrip('/')}/products.json?limit=100"
    for attempt in range(FETCH_RETRIES):
        try:
            resp = await asyncio.wait_for(
                session.get(
                    products_url,
                    headers=get_random_headers(),
                    follow_redirects=True,
                ),
                timeout=FAST_TIMEOUT,
            )
            if resp.status_code != 200:
                break
            raw = getattr(resp, "content", None)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            elif hasattr(resp, "text"):
                raw = getattr(resp, "text", "") or ""
            else:
                raw = ""
            products = _parse_products_json(raw)
            if products:
                return products
            if raw.strip().startswith("<") and HAS_CLOUDSCRAPER:
                try:
                    products = await asyncio.to_thread(
                        _fetch_products_cloudscraper_sync,
                        base_url,
                        proxy,
                    )
                    if products:
                        return products
                except Exception:
                    pass
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
            pass
    if HAS_CLOUDSCRAPER and not products:
        try:
            products = await asyncio.to_thread(
                _fetch_products_cloudscraper_sync,
                base_url,
                proxy,
            )
        except Exception:
            pass
    return products if isinstance(products, list) else []


def find_lowest_variant_from_products(products: List[Dict]) -> Optional[Dict]:
    """Find lowest priced product from products list. Prefer available variants; fallback to lowest price regardless."""
    lowest_price = float('inf')
    lowest_product = None
    lowest_variant = None
    fallback_price = float('inf')
    fallback_product = None
    fallback_variant = None
    for product in products:
        variants = product.get('variants', []) or []
        for variant in variants:
            try:
                available = variant.get('available', False)
                price_str = variant.get('price', '0') or '0'
                price = float(price_str) if price_str else 0.0
                if price < 0.10:
                    continue
                if available and price < lowest_price:
                    lowest_price = price
                    lowest_product = product
                    lowest_variant = variant
                if price < fallback_price:
                    fallback_price = price
                    fallback_product = product
                    fallback_variant = variant
            except (ValueError, TypeError):
                continue
    if lowest_product and lowest_variant:
        return {'product': lowest_product, 'variant': lowest_variant, 'price': lowest_price}
    if fallback_product and fallback_variant:
        return {'product': fallback_product, 'variant': fallback_variant, 'price': fallback_price}
    return None


def _fetch_low_product_api_sync(domain: str, proxy: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Sync fetch from Railway API https://shopify-api-new-production.up.railway.app/<domain>
    Returns parsed dict with variant id, price, requires_shipping, etc. or None.
    Used by addurl/txturl so digital/low-price products (e.g. $1) are accepted.
    Retries for stickerdad.com and protected stores.
    """
    if not domain or not str(domain).strip():
        return None
    domain = str(domain).strip().lower()
    if "://" in domain:
        domain = urlparse(f"//{domain}").netloc or domain
    domain = (domain or "").split("/")[0]
    domains_to_try = [domain]
    if domain.startswith("www."):
        domains_to_try.append(domain[4:])
    else:
        domains_to_try.append("www." + domain)
    for _domain in domains_to_try:
        for attempt in range(RAILWAY_API_RETRIES):
            try:
                api_url = f"{LOW_PRODUCT_API_BASE}/{_domain}"
                if HAS_CLOUDSCRAPER:
                    scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
                    proxies = {"http": proxy, "https": proxy} if proxy and str(proxy).strip() else None
                    r = scraper.get(api_url, timeout=RAILWAY_API_TIMEOUT, proxies=proxies)
                else:
                    import urllib.request
                    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/80.0.3987.149 Safari/537.36"})
                    r = urllib.request.urlopen(req, timeout=RAILWAY_API_TIMEOUT)
                    class R:
                        status_code = r.status if hasattr(r, 'status') else 200
                        text = r.read().decode("utf-8", errors="ignore")
                    r = R
                if getattr(r, "status_code", 0) != 200:
                    if attempt < RAILWAY_API_RETRIES - 1:
                        time.sleep(1.0 + attempt)
                        continue
                    break
                text = (getattr(r, "text", None) or "").strip()
                if not text or text.startswith("<"):
                    if attempt < RAILWAY_API_RETRIES - 1:
                        time.sleep(1.0 + attempt)
                        continue
                    break
                data = json.loads(text)
                if not isinstance(data, dict) or not data.get("success"):
                    break
                variant = data.get("variant")
                pricing = data.get("pricing")
                product = data.get("product")
                location = data.get("location")
                if not isinstance(variant, dict) or variant.get("id") is None:
                    break
                variant_id = None
                try:
                    vid = variant.get("id")
                    if isinstance(vid, (int, float)):
                        variant_id = int(vid)
                    else:
                        variant_id = int(str(vid))
                except (TypeError, ValueError):
                    break
                if variant_id is None:
                    break
                price_val = None
                if isinstance(pricing, dict):
                    try:
                        price_val = float(pricing.get("price", 0) or 0)
                    except (TypeError, ValueError):
                        pass
                price_val = price_val if price_val is not None else 0.0
                if price_val > 25.0:
                    break
                return {
                    "variantid": variant_id,
                    "price": price_val,
                    "requires_shipping": variant.get("requires_shipping", False),
                    "formatted_price": (pricing or {}).get("formatted_price", f"${price_val:.2f}"),
                    "currency_code": (pricing or {}).get("currency_code", "USD"),
                    "country_code": (location or {}).get("country_code", "US"),
                    "product_title": (product or {}).get("title", "N/A")[:50] if isinstance(product, dict) else "N/A",
                    "cart_add_url": (data.get("checkout") or {}).get("cart_add_url"),
                }
            except Exception:
                if attempt < RAILWAY_API_RETRIES - 1:
                    time.sleep(1.0 + attempt)
                    continue
                break
    return None


async def validate_and_parse_site(
    url: str,
    session: TLSAsyncSession,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate if a URL is a working Shopify store and parse lowest product.
    Uses Railway API first (https://shopify-api-new-production.up.railway.app/<domain>) so digital
    and low-price products (e.g. $1) work for stickerdad.com and similar. Fallback: products.json.
    """
    result = {
        "valid": False,
        "url": url,
        "gateway": "Normal",
        "price": "N/A",
        "error": None,
        "product_id": None,
        "product_title": None,
        "currency": "USD",
        "formatted_price": None,
    }
    try:
        normalized_url = normalize_url(url)
        result["url"] = normalized_url
        domain = urlparse(normalized_url).netloc or normalized_url.replace("https://", "").replace("http://", "").split("/")[0]
        # 1) Try Railway low-product API first (supports digital/low-price products, stickerdad.com etc.)
        try:
            api_result = await asyncio.to_thread(_fetch_low_product_api_sync, domain, proxy)
            if api_result and api_result.get("variantid") is not None:
                price_val = api_result.get("price", 0) or 0
                if price_val <= 25.0:
                    result["valid"] = True
                    result["product_id"] = api_result["variantid"]
                    result["product_title"] = api_result.get("product_title", "N/A")
                    result["price"] = f"{price_val:.2f}"
                    result["formatted_price"] = api_result.get("formatted_price") or f"${price_val:.2f}"
                    result["currency"] = api_result.get("currency_code") or "USD"
                    return result
        except Exception:
            pass
        # 2) Fallback: products.json
        products = await fetch_products_json(session, normalized_url, proxy)
        if not products and HAS_CLOUDSCRAPER:
            try:
                products = await asyncio.to_thread(
                    _fetch_products_cloudscraper_sync,
                    normalized_url,
                    proxy,
                )
            except Exception:
                pass
        if not products:
            result["error"] = "No products (not Shopify or protected)"
            return result
        lowest = find_lowest_variant_from_products(products)
        if not lowest:
            result["error"] = "No parseable variants from products.json"
            return result
        price_value = lowest['price']
        if price_value > 25.0:
            result["error"] = f"Price too high: ${price_value:.2f} (max $25.00)"
            result["valid"] = False
            return result
        result["valid"] = True
        result["product_id"] = lowest['variant'].get('id')
        result["product_title"] = lowest['product'].get('title', 'N/A')[:50]
        result["price"] = f"{lowest['price']:.2f}"
        result["formatted_price"] = f"${lowest['price']:.2f}"
        return result
    except Exception as e:
        result["error"] = str(e)[:50]
        return result


def get_user_current_site(user_id: str) -> Optional[Dict[str, str]]:
    """Get user's currently saved site using unified site manager."""
    site = get_primary_site(user_id)
    if site:
        return {
            "site": site.get("url"),
            "gate": site.get("gateway"),
            "price": site.get("price", "N/A")
        }
    return None


async def test_site_with_card(url: str, proxy: Optional[str] = None, max_retries: int = 5) -> tuple[bool, dict]:
    """
    Run a /sh-style test check on a single URL with TEST_CARD.
    Returns (has_receipt, result). When no receipt, result contains actual gate error.
    If ReceiptId is present in any attempt (e.g. after CAPTCHA on earlier attempt), site is valid.
    """
    proxy_url = None
    if proxy and str(proxy).strip():
        px = str(proxy).strip()
        proxy_url = px if px.startswith(("http://", "https://")) else f"http://{px}"
    last_res = {"Response": "NO_RECEIPT", "ReceiptId": None, "Price": "0.00"}
    for attempt in range(max_retries):
        try:
            async with TLSAsyncSession(timeout_seconds=20, proxy=proxy_url) as session:
                res = await asyncio.wait_for(
                    autoshopify_with_captcha_retry(
                        url, TEST_CARD, session, max_captcha_retries=4, proxy=proxy_url
                    ),
                    timeout=65.0,
                )
                last_res = res
                if res.get("ReceiptId"):
                    return True, res
        except asyncio.TimeoutError:
            last_res = {"Response": "TIMEOUT_90S", "ReceiptId": None, "Price": "0.00"}
        except Exception as e:
            last_res = {"Response": f"ERROR: {str(e)[:80]}", "ReceiptId": None, "Price": "0.00"}
        if attempt < max_retries - 1:
            await asyncio.sleep(1.0 + attempt * 0.5)
    resp = (last_res.get("Response") or "").strip()
    if not resp:
        resp = "NO_RECEIPT"
    return False, {"Response": resp, "ReceiptId": None, "Price": last_res.get("Price") or "0.00"}


# ==================== COMMAND HANDLERS ====================

@Client.on_message(filters.command(["addurl", "slfurl", "seturl"]))
async def add_site_handler(client: Client, message: Message):
    """
    Handle /addurl command to add and validate Shopify sites.
    Works in both private chats and groups. Parses lowest product and validates before saving.
    """
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    clickable_name = f"<a href='tg://user?id={user_id}'>{user_name}</a>"

    users = load_users()
    if user_id not in users:
        return await message.reply(
            """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    args = message.command[1:]
    if not args and message.reply_to_message and message.reply_to_message.text:
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        args = re.findall(url_pattern, message.reply_to_message.text)
        if not args:
            domain_pattern = r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'
            args = re.findall(domain_pattern, message.reply_to_message.text)

    if not args:
        return await message.reply(
            """<pre>📖 Add Site Guide</pre>
━━━━━━━━━━━━━
<b>Add a Shopify site for checking:</b>

<code>/addurl https://store.myshopify.com</code>
<code>/addurl store.com</code>
<code>/addurl site1.com site2.com</code> <i>(multiple)</i>

<b>After adding:</b> Use <code>/sh</code> or <code>/slf</code> to check cards

<b>Other Commands:</b>
• <code>/mysite</code> - View your current site
• <code>/txturl</code> - Add multiple sites
• <code>/txtls</code> - List all your sites
• <code>/delsite</code> - Remove your site
━━━━━━━━━━━━━
<i>Works in groups & private chats!</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    urls = args[:10]
    total_urls = len(urls)
    start_time = time.time()

    status_msg = await message.reply(
        f"""<pre>🔍 Validating Shopify Sites...</pre>
━━━━━━━━━━━━━
<b>Sites:</b> <code>{total_urls}</code>
<b>Status:</b> <i>Parsing lowest products...</i>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )

    try:
        user_proxy = get_rotating_proxy(int(user_id))

        async def validate_with_progress():
            results = []
            for idx, url in enumerate(urls, 1):
                try:
                    async with TLSAsyncSession(timeout_seconds=FAST_TIMEOUT, proxy=user_proxy) as session:
                        result = await validate_and_parse_site(url, session, user_proxy)
                    results.append(result)
                    if idx % 1 == 0 or idx == len(urls):
                        await status_msg.edit_text(
                            f"""<pre>🔍 Validating Shopify Sites...</pre>
━━━━━━━━━━━━━
<b>Sites:</b> <code>{total_urls}</code>
<b>Progress:</b> <code>{idx}/{total_urls}</code>
<b>Status:</b> <i>Parsing products & checking price...</i>""",
                            parse_mode=ParseMode.HTML
                        )
                except Exception as e:
                    results.append({
                        "valid": False,
                        "url": url,
                        "error": str(e)[:50],
                        "price": "N/A"
                    })
            return results

        results = await validate_with_progress()
        valid_sites = [r for r in results if r["valid"]]
        invalid_sites = [r for r in results if not r["valid"]]

        if not valid_sites:
            time_taken = round(time.time() - start_time, 2)
            error_lines = []
            for site in invalid_sites[:5]:
                err = site.get('error', 'Invalid') or 'Invalid'
                error_lines.append(f"• <code>{site['url'][:40]}</code> → {err}")
            error_text = "\n".join(error_lines)
            return await status_msg.edit_text(
                f"""<pre>Invalid Site(s) ❌</pre>
━━━━━━━━━━━━━
<b>Checked:</b> <code>{total_urls}</code>
<b>Valid:</b> <code>0</code> (no products from products.json)

<b>Errors:</b>
{error_text}

<b>Tips:</b>
• Use a Shopify store with <code>/products.json</code>
• Full URL: <code>https://store.com</code>
━━━━━━━━━━━━━
⏱️ <b>Time:</b> <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )

        proxy_url = user_proxy
        if user_proxy and str(user_proxy).strip():
            px = str(user_proxy).strip()
            proxy_url = px if px.startswith(("http://", "https://")) else f"http://{px}"

        product_preview = []
        for s in valid_sites[:3]:
            name = (s.get("product_title") or "Product")[:40]
            price = s.get("formatted_price") or f"${s.get('price', 'N/A')}"
            product_preview.append(f"• {name} — {price}")
        product_preview_text = "\n".join(product_preview) if product_preview else "—"
        spinners = ("◐", "◓", "◑", "◒")

        async def spinner_loop():
            i = 0
            while True:
                try:
                    s = spinners[i % 4]
                    await status_msg.edit_text(
                        f"""<pre>{s} Testing Sites...</pre>
━━━━━━━━━━━━━
<b>📦 Parsed product(s):</b>
{product_preview_text}

<b>Valid Sites:</b> <code>{len(valid_sites)}</code>
<b>Status:</b> <i>{s} Running test checkout...</i>""",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
                i += 1
                await asyncio.sleep(1.0)

        await status_msg.edit_text(
            f"""<pre>◐ Testing Sites...</pre>
━━━━━━━━━━━━━
<b>📦 Parsed product(s):</b>
{product_preview_text}

<b>Valid Sites:</b> <code>{len(valid_sites)}</code>
<b>Status:</b> <i>◐ Running test checkout...</i>""",
            parse_mode=ParseMode.HTML
        )

        async def test_and_save(site_info):
            has_rec, test_res = await test_site_with_card(site_info["url"], proxy_url, max_retries=2)
            if has_rec:
                pr = test_res.get("Price") or site_info.get("price") or "N/A"
                try:
                    pv = float(pr)
                    pr = f"{pv:.2f}" if pv != int(pv) else str(int(pv))
                except (TypeError, ValueError):
                    pr = str(pr) if pr else "N/A"
                site_info["price"] = pr
                site_info["formatted_price"] = f"${pr}"
                site_info["test_result"] = test_res.get("Response", "OK")
                save_site_for_user_unified(user_id, site_info["url"], site_info.get("gateway", "Normal"), pr)
                return site_info
            # CAPTCHA_REQUIRED / HCAPTCHA / JUST A MOMENT = valid site (products parsed), captcha blocked checkout - still add as valid
            resp = (test_res.get("Response") or "").strip().upper()
            if any(x in resp for x in ["CAPTCHA", "CAPTCHA_REQUIRED", "HCAPTCHA", "JUST A MOMENT", "CAPTCHA_TOKEN", "CAPTCHA_TOKEN_MISSING"]):
                pr = site_info.get("price") or "N/A"
                try:
                    pv = float(pr)
                    pr = f"{pv:.2f}" if pv != int(pv) else str(int(pv))
                except (TypeError, ValueError):
                    pr = str(pr) if pr else "N/A"
                site_info["price"] = pr
                site_info["formatted_price"] = f"${pr}"
                site_info["test_result"] = "CAPTCHA_REQUIRED"
                save_site_for_user_unified(user_id, site_info["url"], site_info.get("gateway", "Normal"), pr)
                return site_info
            site_info["test_error"] = (test_res.get("Response") or "NO_RECEIPT").strip()
            return None

        test_tasks = [test_and_save(v) for v in valid_sites]
        spinner_task = asyncio.create_task(spinner_loop())
        try:
            test_results = await asyncio.gather(*test_tasks, return_exceptions=True)
        finally:
            spinner_task.cancel()
            try:
                await spinner_task
            except asyncio.CancelledError:
                pass

        sites_with_receipt = []
        for result in test_results:
            if result and not isinstance(result, Exception):
                sites_with_receipt.append(result)

        if not sites_with_receipt:
            time_taken = round(time.time() - start_time, 2)
            # Build parsed product line(s) for each validated site
            product_lines = []
            for s in valid_sites[:5]:
                name = (s.get("product_title") or "Product")[:45]
                price = s.get("formatted_price") or f"${s.get('price', 'N/A')}"
                product_lines.append(f"• <b>{name}</b> — <code>{price}</code>")
            parsed_block = "\n".join(product_lines) if product_lines else "• <i>No product details</i>"
            error_lines = []
            for s in valid_sites[:5]:
                err = (s.get("test_error") or "NO_RECEIPT").strip()[:50]
                error_lines.append(f"• <code>{s['url'][:35]}</code>\n  └─ {err}")
            error_text = "\n".join(error_lines) if error_lines else "All test checkouts failed to generate receipt."
            gate_err = (valid_sites[0].get("test_error") or "NO_RECEIPT").strip()[:60]
            return await status_msg.edit_text(
                f"""<pre>No Sites Verified ❌</pre>
━━━━━━━━━━━━━
<b>📦 Parsed product(s):</b>
{parsed_block}

<b>💳 Gate test:</b> Did not return receipt/bill.
(Site has products; test checkout failed.)

<b>Gate Errors:</b>
{error_text}

<b>Gate error:</b> <code>{gate_err}</code>

<b>Tips:</b>
• Set proxy: <code>/setpx</code>
• Use a gate that completes checkout with receipt
━━━━━━━━━━━━━
⏱️ <b>Time:</b> <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )

        time_taken = round(time.time() - start_time, 2)
        primary_site = sites_with_receipt[0]
        site_url = primary_site["url"]
        gateway = primary_site.get("gateway", "Normal")
        price = primary_site["price"]
        product_title = primary_site.get("product_title", "N/A")
        formatted_price = primary_site.get("formatted_price", f"${price}")

        response_lines = [
            f"<pre>Site Added Successfully ✅</pre>",
            "━━━━━━━━━━━━━",
            f"[⌯] <b>Site:</b> <code>{site_url}</code>",
            f"[⌯] <b>Gateway:</b> <code>Shopify Normal</code>",
            f"[⌯] <b>Price:</b> <code>{formatted_price}</code>",
            f"[⌯] <b>Product:</b> <code>{product_title}...</code>",
            f"[⌯] <b>Status:</b> <code>Active ✓</code> (test card verified)",
        ]
        if len(sites_with_receipt) > 1:
            response_lines.append("")
            response_lines.append(f"<b>Also verified ({len(sites_with_receipt) - 1}):</b>")
            for s in sites_with_receipt[1:5]:
                response_lines.append(f"• <code>{s['url'][:35]}</code> [${s.get('price', 'N/A')}]")
        if invalid_sites:
            response_lines.append("")
            response_lines.append(f"<b>Failed:</b> <code>{len(invalid_sites)}</code> site(s)")
        response_lines.extend([
            "━━━━━━━━━━━━━",
            f"[⌯] <b>Command:</b> <code>/sh</code> or <code>/slf</code>",
            f"[⌯] <b>Time:</b> <code>{time_taken}s</code>",
            f"[⌯] <b>User:</b> {clickable_name}",
        ])

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✓ Check Card", callback_data="show_check_help"),
                InlineKeyboardButton("📋 My Sites", callback_data="show_my_sites")
            ]
        ])

        await status_msg.edit_text(
            "\n".join(response_lines),
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
            disable_web_page_preview=True
        )

    except Exception as e:
        time_taken = round(time.time() - start_time, 2)
        logger.error("addurl error: %s", e, exc_info=True)
        await status_msg.edit_text(
            f"""<pre>Error Occurred ⚠️</pre>
━━━━━━━━━━━━━
<b>Error:</b> <code>{str(e)[:100]}</code>
<b>Time:</b> <code>{time_taken}s</code>

<b>Please try again or contact support.</b>""",
            parse_mode=ParseMode.HTML
        )


@Client.on_message(filters.command(["mysite", "getsite", "siteinfo"]))
async def my_site_handler(client: Client, message: Message):
    """Show user's currently saved primary site."""
    user_id = str(message.from_user.id)
    site_info = get_user_current_site(user_id)
    if not site_info:
        return await message.reply(
            """<pre>No Site Found ℹ️</pre>
<b>You haven't added any site yet.</b>

Use <code>/addurl https://store.com</code> to add a Shopify site.""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    all_sites = get_user_sites(user_id)
    total_count = len(all_sites)
    await message.reply(
        f"""<pre>Your Primary Site 📋</pre>
━━━━━━━━━━━━━
[⌯] <b>Site:</b> <code>{site_info.get('site', 'N/A')}</code>
[⌯] <b>Gateway:</b> <code>{site_info.get('gate', 'Unknown')}</code>
[⌯] <b>Price:</b> <code>${site_info.get('price', 'N/A')}</code>
━━━━━━━━━━━━━
<b>Total Sites:</b> <code>{total_count}</code>
<b>Commands:</b> <code>/sh</code> or <code>/slf</code> to check cards
<b>List All:</b> <code>/txtls</code>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command(["delsite", "removesite", "clearsite", "remurl"]))
async def delete_site_handler(client: Client, message: Message):
    """Delete all of user's saved sites (unified storage)."""
    user_id = str(message.from_user.id)
    try:
        count = clear_user_sites(user_id)
        if count > 0:
            return await message.reply(
                f"<pre>Sites Removed ✅</pre>\n<b>Cleared {count} site(s).</b> You can add again with <code>/addurl</code>.",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        await message.reply(
            "<pre>No Site Found ℹ️</pre>\n<b>You don't have any site saved.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.reply(
            f"<pre>Error ⚠️</pre>\n<code>{str(e)[:80]}</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )


# ==================== CALLBACK HANDLERS ====================

@Client.on_callback_query(filters.regex("^show_check_help$"))
async def show_check_help_callback(client, callback_query):
    """Show card checking help."""
    await callback_query.answer()
    await callback_query.message.reply(
        """<pre>📖 Card Checking Guide</pre>
━━━━━━━━━━━━━
<b>Single Card Check:</b>
<code>/sh 4111111111111111|12|2025|123</code>

<b>Reply to Card:</b>
Reply to a message containing a card with <code>/sh</code>

<b>Mass Check:</b>
<code>/msh</code> (reply to list of cards)

<b>Format:</b> <code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>
━━━━━━━━━━━━━
<b>Supported Gates:</b>
• Shopify Payments (Normal)
• Stripe
• PayPal/Braintree
━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^show_my_sites$"))
async def show_my_sites_callback(client, callback_query):
    """Show user's all sites."""
    user_id = str(callback_query.from_user.id)
    sites = get_user_sites(user_id)
    if not sites:
        await callback_query.answer("❌ No sites saved!", show_alert=True)
        return
    lines = ["<pre>📋 Your Sites</pre>", "━━━━━━━━━━━━━"]
    for i, site in enumerate(sites[:10], 1):
        is_primary = "⭐" if site.get("is_primary") else ""
        url = site.get("url", "N/A")[:35]
        lines.append(f"{i}. {is_primary}<code>{url}</code>")
    if len(sites) > 10:
        lines.append(f"\n<i>...and {len(sites) - 10} more</i>")
    lines.append("━━━━━━━━━━━━━")
    lines.append(f"<b>Total:</b> <code>{len(sites)}</code> sites")
    await callback_query.answer()
    await callback_query.message.reply(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^show_my_site$"))
async def show_my_site_callback(client, callback_query):
    """Show user's primary site."""
    user_id = str(callback_query.from_user.id)
    site_info = get_user_current_site(user_id)
    if site_info:
        await callback_query.answer(
            f"📋 YOUR SITE\n\n"
            f"🌐 {site_info.get('site', 'N/A')[:40]}\n"
            f"⚡ {site_info.get('gate', 'Unknown')[:30]}\n\n"
            f"Use /sh to check cards!",
            show_alert=True
        )
    else:
        await callback_query.answer(
            "❌ No site saved!\n\n"
            "Use /addurl to add a site.",
            show_alert=True
        )


@Client.on_callback_query(filters.regex("^plans_info$"))
async def plans_info_callback(client, callback_query):
    """Show plans information."""
    await callback_query.answer()
    await callback_query.message.reply(
        """<pre>💎 Available Plans</pre>
━━━━━━━━━━━━━
<b>🎟️ Free Plan:</b>
• 10 credits/day
• 10s antispam delay
• Basic features

<b>⭐ Premium Plan:</b>
• 500 credits/day
• 3s antispam delay
• All gates access
• Priority support

<b>👑 VIP Plan:</b>
• Unlimited credits
• No antispam delay
• All features
• 24/7 support
━━━━━━━━━━━━━
Use <code>/buy</code> to purchase!""",
        parse_mode=ParseMode.HTML
    )
