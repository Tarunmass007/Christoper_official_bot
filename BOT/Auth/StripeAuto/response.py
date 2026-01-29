"""Stripe Auto Auth response classification."""

from typing import Dict


def determine_stripe_auto_status(result: Dict) -> str:
    """Classify result into APPROVED, CCN LIVE, DECLINED, ERROR."""
    if not result:
        return "ERROR"
    resp = (result.get("response") or "").upper()
    if resp in ("APPROVED", "LIVE", "SUCCESS"):
        return "APPROVED"
    if resp in ("CCN LIVE", "CCN", "3DS", "INCORRECT_CVC", "INVALID_CVC", "INCORRECT_ZIP", "POSTAL_CODE"):
        return "CCN LIVE"
    if resp in ("DECLINED", "DECLINE", "REJECTED", "EXPIRED", "LOST", "STOLEN", "FRAUD", "DO NOT HONOR"):
        return "DECLINED"
    return "ERROR"
