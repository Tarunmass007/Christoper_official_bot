"""
Unified Site Manager for Shopify Checkers.
Storage delegated to BOT.db.store (MongoDB or JSON).

IMPORTANT: No default sites for admin/owner.
All users (including admin/owner) must add sites manually using /addurl or /txturl.
No special handling or default sites are provided for any user.
"""

import random
from typing import Dict, List, Optional, Tuple

from dataclasses import dataclass

from BOT.db.store import (
    load_unified_sites,
    save_unified_sites,
    get_user_sites,
    get_user_active_sites,
    get_primary_site,
    add_site_for_user,
    add_sites_batch,
    remove_site_for_user,
    clear_user_sites,
    mark_site_failed,
    reset_site_fail_count,
)

# Legacy paths kept for backwards refs; actual storage in BOT.db.store
UNIFIED_SITES_PATH = "DATA/user_sites.json"
LEGACY_SITES_PATH = "DATA/sites.json"
LEGACY_TXT_SITES_PATH = "DATA/txtsite.json"


@dataclass
class SiteInfo:
    """Represents a single site with its details."""
    url: str
    gateway: str
    price: str = "N/A"
    active: bool = True
    fail_count: int = 0


class SiteRotator:
    """
    Handles site rotation for retry logic on captcha/errors.
    Rotates through user's sites until a real response is obtained.
    """

    def __init__(self, user_id: str, max_retries: int = 3):
        self.user_id = str(user_id)
        self.max_retries = max_retries
        self.sites = get_user_active_sites(self.user_id)
        self.current_index = 0
        self.tried_sites = set()
        self.retry_count = 0

    def has_sites(self) -> bool:
        return len(self.sites) > 0

    def get_current_site(self) -> Optional[Dict]:
        if not self.sites:
            return None
        return self.sites[self.current_index % len(self.sites)]

    def get_next_site(self) -> Optional[Dict]:
        if not self.sites:
            return None
        current = self.get_current_site()
        if current:
            self.tried_sites.add(current.get("url", "").lower())
        for _ in range(len(self.sites)):
            self.current_index = (self.current_index + 1) % len(self.sites)
            next_site = self.sites[self.current_index]
            if next_site.get("url", "").lower() not in self.tried_sites:
                return next_site
        if self.retry_count < self.max_retries:
            self.retry_count += 1
            self.tried_sites.clear()
            self.current_index = (self.current_index + 1) % len(self.sites)
            return self.sites[self.current_index]
        return None

    def get_random_site(self) -> Optional[Dict]:
        if not self.sites:
            return None
        return random.choice(self.sites)

    def should_retry(self, response: str) -> bool:
        if not response:
            return True
        response_upper = response.upper()
        retry_keywords = [
            "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE", "VERIFY",
            "SITE_EMPTY", "SITE_HTML", "SITE_CAPTCHA", "SITE_HTTP", "SITE_CONNECTION",
            "SITE_DEAD", "SITE DEAD", "SITE_NO_PRODUCTS", "SITE_PRODUCTS_EMPTY", "SITE_INVALID_JSON",
            "CART_ERROR", "CART_HTML", "CART_INVALID", "CART_CREATION",
            "SESSION_ERROR", "SESSION_ID", "SESSION_INVALID",
            "NO_AVAILABLE_PRODUCTS", "BUILD", "NEGOTIATE", "DELIVERY_ERROR",
            "CHECKOUT_HTML", "CHECKOUT_TOKENS", "CHECKOUT_HTTP",
            "TIMEOUT", "CONNECTION", "RATE_LIMIT", "BLOCKED", "PROXY_ERROR",
            "429", "502", "503", "504",
            "RECEIPT_EMPTY", "SUBMIT_INVALID_JSON", "SUBMIT_HTTP",
        ]
        return any(kw in response_upper for kw in retry_keywords)

    def is_real_response(self, response: str) -> bool:
        if not response:
            return False
        response_upper = response.upper()
        real_keywords = [
            "CHARGED", "ORDER_PLACED", "THANK_YOU", "SUCCESS", "COMPLETE",
            "3DS", "3D_SECURE", "AUTHENTICATION", "INCORRECT_CVC", "INVALID_CVC",
            "INCORRECT_ZIP", "INCORRECT_ADDRESS", "MISMATCHED", "INSUFFICIENT_FUNDS",
            "CARD_DECLINED", "DECLINED", "GENERIC_DECLINE", "DO_NOT_HONOR",
            "EXPIRED", "INVALID_NUMBER", "LOST", "STOLEN", "PICKUP", "FRAUD",
            "RESTRICTED", "REVOKED", "INVALID_ACCOUNT", "NOT_SUPPORTED", "RISKY",
        ]
        return any(kw in response_upper for kw in real_keywords)

    def mark_current_failed(self):
        current = self.get_current_site()
        if current:
            mark_site_failed(self.user_id, current.get("url", ""))

    def mark_current_success(self):
        current = self.get_current_site()
        if current:
            reset_site_fail_count(self.user_id, current.get("url", ""))

    def get_site_count(self) -> int:
        return len(self.sites)

    def get_sites_tried_count(self) -> int:
        return len(self.tried_sites)


def get_site_and_gateway(user_id: str) -> Tuple[Optional[str], Optional[str]]:
    site = get_primary_site(user_id)
    if site:
        return site.get("url"), site.get("gateway", "Unknown")
    return None, None


# Re-export store helpers so addurl/txturl etc. can keep importing from site_manager
__all__ = [
    "load_unified_sites",
    "save_unified_sites",
    "get_user_sites",
    "get_user_active_sites",
    "get_primary_site",
    "add_site_for_user",
    "add_sites_batch",
    "remove_site_for_user",
    "clear_user_sites",
    "mark_site_failed",
    "reset_site_fail_count",
    "SiteRotator",
    "SiteInfo",
    "get_site_and_gateway",
]
