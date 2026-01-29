"""
Braintree CVV Auth Checker
Iditarod.com gate: login -> payment-methods -> add-payment-method -> Braintree tokenize -> submit.
Account rotation, proxy support, real response parsing.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from BOT.tools.braintree_cvv.iditarod_gate import run_iditarod_check_parallel

executor = ThreadPoolExecutor(max_workers=16)


def check_braintree_cvv_sync(
    card: str,
    mes: str,
    ano: str,
    cvv: str,
    proxy: Optional[str] = None,
) -> dict:
    """
    Braintree CVV check via Iditarod.com (parallel all-accounts, add payment method).
    Uses multi-thread across all accounts; retries without proxy on proxy/connection errors.
    """
    result = run_iditarod_check_parallel(card, mes, ano, cvv, proxy)
    if result.get("status") == "error" and proxy:
        resp = (result.get("response") or "").lower()
        if "proxy" in resp or "connection" in resp or "timeout" in resp:
            result = run_iditarod_check_parallel(card, mes, ano, cvv, None)
    return result


async def async_check_braintree_cvv(
    card: str,
    mes: str,
    ano: str,
    cvv: str,
    proxy: Optional[str] = None,
) -> dict:
    """Async wrapper for Braintree CVV check (Iditarod gate)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor,
        check_braintree_cvv_sync,
        card,
        mes,
        ano,
        cvv,
        proxy,
    )
