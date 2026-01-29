"""
Ultimate Peaceful Async Request Layer for Shopify Gates
========================================================
Provides browser-like headers and request jitter for asyncio HTTP requests
to avoid captcha and HTTPS restriction flags. Used only inside TLSAsyncSession;
does not change any command names, sh/msh/tsh retries, thread counts, or other logic.
"""

import asyncio
import random
import time
from typing import Optional, Dict, Any

# Default minimum/maximum delay (seconds) before each request to avoid burst detection
PEACEFUL_DELAY_MIN = 0.12
PEACEFUL_DELAY_MAX = 0.32

# Browser-like User-Agents (Chrome/Firefox/Safari, desktop + mobile)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
]

# sec-ch-ua values matching Chrome 120
SEC_CH_UA = '"Chromium";v="120", "Google Chrome";v="120", "Not_A Brand";v="24"'
SEC_CH_UA_MOBILE = "?0"
SEC_CH_UA_PLATFORM = '"Windows"'


def get_random_user_agent() -> str:
    """Return a random browser User-Agent."""
    return random.choice(USER_AGENTS)


def _platform_from_ua(ua: str) -> str:
    if not ua:
        return "Windows"
    ua_lower = ua.lower()
    if "android" in ua_lower:
        return "Android"
    if "iphone" in ua_lower or "ipad" in ua_lower:
        return "iOS"
    if "macintosh" in ua_lower or "mac os" in ua_lower:
        return "macOS"
    if "windows" in ua_lower:
        return "Windows"
    if "linux" in ua_lower:
        return "Linux"
    return "Windows"


def get_browser_headers(
    user_agent: Optional[str] = None,
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    accept_language: str = "en-US,en;q=0.9",
    accept_encoding: str = "gzip, deflate, br",
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    Build a full set of browser-like headers to avoid captcha and restriction flags.
    Use for GET/POST to store pages, products.json, checkout, and GraphQL.
    """
    ua = user_agent or get_random_user_agent()
    platform = _platform_from_ua(ua)
    mobile = "?1" if any(x in ua.lower() for x in ["android", "iphone", "ipad", "mobile"]) else "?0"
    # Use empty/cors by default so both page loads and API (products.json, GraphQL) work without triggering strict checks
    headers = {
        "User-Agent": ua,
        "Accept": accept,
        "Accept-Language": accept_language,
        "Accept-Encoding": accept_encoding,
        "Connection": "keep-alive",
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": mobile,
        "sec-ch-ua-platform": f'"{platform}"',
        "Cache-Control": "max-age=0",
    }
    if extra:
        headers.update(extra)
    return headers


def get_json_headers(user_agent: Optional[str] = None, origin: Optional[str] = None, referer: Optional[str] = None) -> Dict[str, str]:
    """Headers for JSON/API requests (products.json, GraphQL)."""
    ua = user_agent or get_random_user_agent()
    platform = _platform_from_ua(ua)
    mobile = "?1" if any(x in ua.lower() for x in ["android", "iphone", "ipad", "mobile"]) else "?0"
    h = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": mobile,
        "sec-ch-ua-platform": f'"{platform}"',
    }
    if origin:
        h["Origin"] = origin
    if referer:
        h["Referer"] = referer
    return h


async def peaceful_delay(
    min_sec: Optional[float] = None,
    max_sec: Optional[float] = None,
) -> None:
    """
    Short async delay with jitter before a request to avoid burst detection
    and rate limits. Call before session.get() or session.post().
    """
    lo = min_sec if min_sec is not None else PEACEFUL_DELAY_MIN
    hi = max_sec if max_sec is not None else PEACEFUL_DELAY_MAX
    delay = random.uniform(lo, hi)
    await asyncio.sleep(delay)


# Optional: per-host last-request time for stricter rate limiting (not used by default)
_last_request_time: Dict[str, float] = {}
_lock = asyncio.Lock()


async def peaceful_delay_per_host(host: str, min_sec: float = 0.15, max_sec: float = 0.35) -> None:
    """
    Delay so that we don't hit the same host too fast (optional stricter rate limit).
    """
    async with _lock:
        now = time.monotonic()
        last = _last_request_time.get(host, 0)
        elapsed = now - last
        need = random.uniform(min_sec, max_sec)
        if elapsed < need:
            await asyncio.sleep(need - elapsed)
        _last_request_time[host] = time.monotonic()


def merge_peaceful_headers(caller_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Merge default browser headers with caller headers (caller wins).
    Use this when you have partial headers from the caller.
    """
    base = get_browser_headers()
    if caller_headers:
        base.update(caller_headers)
    return base
