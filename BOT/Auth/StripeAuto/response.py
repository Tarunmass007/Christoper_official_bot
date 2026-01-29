"""Stripe Auto Auth response classification.
3DS / action_required = CCN LIVE (same as starr-shop.eu gate).
"""

from typing import Dict


def determine_stripe_auto_status(result: Dict) -> str:
    """Classify result into APPROVED, CCN LIVE, DECLINED, ERROR. 3DS/action_required -> CCN LIVE."""
    if not result:
        return "ERROR"
    resp = (result.get("response") or "").upper()
    msg = (result.get("message") or "").upper()
    combined = f"{resp} {msg}"
    # APPROVED
    if resp in ("APPROVED", "LIVE", "SUCCESS"):
        return "APPROVED"
    # 3DS / action_required = CCN LIVE (card is live)
    if resp in ("3DS_REQUIRED", "CCN LIVE", "CCN", "3DS") or any(
        x in combined for x in ["ACTION REQUIRED", "ACTION_REQUIRED", "3D SECURE", "AUTHENTICATION REQUIRED", "CHALLENGE"]
    ):
        return "CCN LIVE"
    if resp in ("CCN LIVE", "CCN", "INCORRECT_CVC", "INVALID_CVC", "INCORRECT_ZIP", "POSTAL_CODE"):
        return "CCN LIVE"
    if resp in ("DECLINED", "DECLINE", "REJECTED", "EXPIRED", "LOST", "STOLEN", "FRAUD", "DO NOT HONOR"):
        return "DECLINED"
    return "ERROR"
