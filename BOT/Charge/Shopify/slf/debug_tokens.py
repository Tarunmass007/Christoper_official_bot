"""
Debug token parsing - run: python -m BOT.Charge.Shopify.slf.debug_tokens stickerdad.com
Fetches checkout page via cloudscraper, saves raw HTML, runs token extraction, reports missing.
"""
import asyncio
import os
import re
import sys

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

try:
    import cloudscraper
    HAS_CS = True
except ImportError:
    HAS_CS = False

from BOT.Charge.Shopify.slf.api import (
    _fetch_low_product_api,
    _fetch_checkout_via_cloudscraper_full_flow_sync,
    _extract_checkout_tokens_robust,
    _extract_session_token,
    _extract_jwt_from_text,
    capture,
    _extract_tokens_from_page_json,
)
from BOT.Charge.Shopify.tls_session import TLSAsyncSession


def search_patterns(text: str) -> dict:
    """Search for token-like patterns in raw text."""
    out = {}
    if not text:
        return out
    # Session token patterns
    for name, pat in [
        ("serialized-sessionToken", "serialized-sessionToken"),
        ("serialized-session-token", "serialized-session-token"),
        ("serializedSessionToken", "serializedSessionToken"),
        ("sessionToken", "sessionToken"),
        ("session_token", "session_token"),
    ]:
        out[name] = pat in text
    # Source
    for name, pat in [
        ("serialized-sourceToken", "serialized-sourceToken"),
        ("serialized-source-token", "serialized-source-token"),
        ("serializedSourceToken", "serializedSourceToken"),
        ("sourceToken", "sourceToken"),
    ]:
        out[name] = pat in text
    # Queue/Stable
    out["queueToken"] = "queueToken" in text
    out["stableId"] = "stableId" in text
    # JWT
    jwt = re.search(r"eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", text)
    out["jwt_found"] = bool(jwt)
    if jwt:
        out["jwt_len"] = len(jwt.group(0))
    # /cn/ in URL
    out["cn_in_url"] = "/cn/" in text
    return out


def extract_snippets(text: str, markers: list) -> dict:
    """Extract 200-char snippets around each marker."""
    out = {}
    for m in markers:
        if m in text:
            idx = text.index(m)
            start = max(0, idx - 50)
            end = min(len(text), idx + 150)
            out[m] = text[start:end]
    return out


async def main(domain: str):
    domain = domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
    url = f"https://{domain}"
    print(f"\n{'='*60}")
    print(f"DEBUG TOKEN PARSING: {url}")
    print("=" * 60)

    product_id = None
    checkout_text = ""
    checkout_url = ""

    # 1) Low-product API
    print("\n[1] Low-product API...")
    async with TLSAsyncSession(timeout_seconds=25) as session:
        low = await _fetch_low_product_api(domain, session, None)
        if low and low.get("variantid"):
            product_id = low["variantid"]
            print(f"    OK: variant={product_id}, price={low.get('price')}, shipping={low.get('requires_shipping')}")
        else:
            print("    FAIL: no product")
            return

    # 2) Cloudscraper full flow
    print("\n[2] Cloudscraper full flow (cart/add + POST checkout)...")
    if not HAS_CS:
        print("    SKIP: cloudscraper not installed")
        return
    sc, checkout_text, checkout_url = await asyncio.to_thread(
        _fetch_checkout_via_cloudscraper_full_flow_sync, url, product_id, None
    )
    print(f"    status={sc}, len={len(checkout_text or '')}, url={checkout_url[:80] if checkout_url else 'N/A'}...")

    if not checkout_text or len(checkout_text) < 500:
        print("    FAIL: no checkout page body")
        return

    # 3) Save raw HTML
    os.makedirs("DATA", exist_ok=True)
    raw_path = os.path.join("DATA", f"checkout_{domain.replace('.', '_')}.html")
    with open(raw_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(checkout_text)
    print(f"\n[3] Raw HTML saved: {raw_path} ({len(checkout_text)} chars)")

    # 4) Pattern presence
    print("\n[4] Pattern presence in page:")
    pres = search_patterns(checkout_text)
    for k, v in pres.items():
        print(f"    {k}: {v}")

    # 5) Snippets around markers
    markers = [m for m, v in pres.items() if v and m not in ("jwt_found", "jwt_len", "cn_in_url")]
    if markers:
        print("\n[5] Snippets around markers:")
        snippets = extract_snippets(checkout_text, markers[:6])
        for k, v in snippets.items():
            print(f"    --- {k} ---")
            print(f"    {repr(v)[:200]}...")

    # 6) Robust extraction
    print("\n[6] _extract_checkout_tokens_robust():")
    robust = _extract_checkout_tokens_robust(checkout_text)
    for k, v in robust.items():
        if v:
            print(f"    {k}: len={len(v)}, first_60={repr(v[:60])}...")
        else:
            print(f"    {k}: MISSING")

    # 7) JSON extraction
    print("\n[7] _extract_tokens_from_page_json():")
    json_tok = _extract_tokens_from_page_json(checkout_text)
    for k, v in json_tok.items():
        if v:
            print(f"    {k}: len={len(v)}, first_60={repr(v[:60])}...")
        else:
            print(f"    {k}: MISSING")

    # 8) Session token specific
    print("\n[8] _extract_session_token():")
    sess = _extract_session_token(checkout_text)
    print(f"    result: {repr(sess[:80]) if sess else 'MISSING'}...")

    # 9) JWT fallback
    print("\n[9] _extract_jwt_from_text():")
    jwt = _extract_jwt_from_text(checkout_text)
    print(f"    result: {repr(jwt[:80]) if jwt else 'MISSING'}...")

    # 10) Capture tests (old api.py patterns)
    print("\n[10] capture() tests (old api.py):")
    for prefix, suffix in [
        ('serialized-session-token" content="&quot;', '&quot'),
        ('serialized-sessionToken" content="&quot;', '&quot;"/>'),
        ('serialized-source-token" content="&quot;', '&quot'),
        ('queueToken&quot;:&quot;', '&quot'),
        ('stableId&quot;:&quot;', '&quot'),
    ]:
        v = capture(checkout_text, prefix, suffix)
        print(f"    prefix={prefix[:35]}... suffix={suffix[:15]}")
        print(f"      -> {repr(v[:60]) if v else 'MISSING'}...")

    # Summary
    missing = [k for k, v in robust.items() if not v]
    print(f"\n{'='*60}")
    print(f"SUMMARY: Missing tokens: {missing if missing else 'NONE'}")
    print("=" * 60)


if __name__ == "__main__":
    dom = sys.argv[1] if len(sys.argv) > 1 else "stickerdad.com"
    asyncio.run(main(dom))
