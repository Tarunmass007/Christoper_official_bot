#!/usr/bin/env python3
"""
Full end-to-end test of Shopify gate API.
Runs diagnostic + full checkout flow step-by-step for debugging.
Usage: python test_shopify_gate_full.py [URL]
Default URL: https://tiefossi.com (or stickerdad.com)
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test sites: tiefossi.com was failing with CHECKOUT_TOKENS_MISSING
TEST_URLS = ["https://tiefossi.com", "https://stickerdad.com"]
TEST_CARD = "4111111111111111|12|2026|123"


async def run_diagnostic(url: str, proxy=None):
    """Step 1: Run full diagnostic (products -> cart -> checkout -> token parsing)."""
    print("\n" + "=" * 70)
    print(f"DIAGNOSTIC: {url}")
    print("=" * 70)

    from BOT.Charge.Shopify.bulletproof_session import BulletproofSession
    from BOT.Charge.Shopify.slf.api import run_shopify_checkout_diagnostic

    try:
        async with BulletproofSession(timeout_seconds=90, proxy=proxy, use_playwright=False) as session:
            data = await run_shopify_checkout_diagnostic(url, session, proxy)
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

    # Step 1: Low-product API
    s1 = data.get("step1_low_product") or {}
    print("\n[STEP 1] Low-product API:")
    for k, v in s1.items():
        print(f"  {k}: {v}")

    # Step 2: Products
    s2 = data.get("step2_products") or {}
    print("\n[STEP 2] Products:")
    for k, v in s2.items():
        print(f"  {k}: {v}")

    # Step 3: Cart add
    s3 = data.get("step3_cart_add") or {}
    print("\n[STEP 3] Cart add:")
    for k, v in s3.items():
        print(f"  {k}: {v}")

    # Step 4: Checkout URL
    print(f"\n[STEP 4] Checkout URL: {data.get('step4_checkout_url', 'N/A')}")

    # Step 5: Checkout page
    s5 = data.get("step5_checkout_page") or {}
    print("\n[STEP 5] Checkout page:")
    print(f"  status: {s5.get('status')}")
    print(f"  text_length: {data.get('checkout_text_length', 0)}")
    if s5.get("snippet_meta_session"):
        print(f"  meta_session snippet: {s5['snippet_meta_session'][:200]}...")

    # Step 6: Token presence
    s6 = data.get("step6_token_presence") or {}
    print("\n[STEP 6] Token presence in page:")
    for k, v in s6.items():
        print(f"  {k}: {v}")

    # Step 7: Robust tokens
    s7 = data.get("step7_robust_tokens") or {}
    print("\n[STEP 7] _extract_checkout_tokens_robust():")
    for k, v in s7.items():
        if v and isinstance(v, dict):
            ln = v.get("len", 0)
            first = v.get("first_80", "")[:50]
            status = "OK" if ln > 10 else "MISSING"
            print(f"  {k}: len={ln} {status} first50={first!r}")
        else:
            print(f"  {k}: None (MISSING)")

    # Step 8-10: Capture tests
    for step, key in [("8", "step8_regex_session_tests"), ("9", "step9_capture_session_tests"), ("10", "step10_capture_source_tests")]:
        items = data.get(key) or []
        print(f"\n[STEP {step}] {key}:")
        for i, t in enumerate(items[:4]):
            if "matched" in t:
                print(f"  {i+1}. {t.get('name','')}: matched={t.get('matched')} len={t.get('group1_len',0)}")
            else:
                print(f"  {i+1}. prefix={str(t.get('prefix',''))[:35]!r} -> len={t.get('result_len',0)}")

    return data


async def run_full_checkout(url: str, proxy=None):
    """Step 2: Run full autoshopify checkout with test card."""
    print("\n" + "=" * 70)
    print(f"FULL CHECKOUT: {url}")
    print("=" * 70)

    from BOT.Charge.Shopify.bulletproof_session import BulletproofSession
    from BOT.Charge.Shopify.slf.api import autoshopify_with_captcha_retry

    try:
        async with BulletproofSession(timeout_seconds=90, proxy=proxy, use_playwright=False) as session:
            out = await autoshopify_with_captcha_retry(url, TEST_CARD, session, max_captcha_retries=2, proxy=proxy)
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None

    print("\n[RESULT]")
    print(f"  Response: {out.get('Response', 'N/A')[:100]}")
    print(f"  Status: {out.get('Status')}")
    print(f"  ReceiptId: {out.get('ReceiptId')}")
    print(f"  Price: {out.get('Price')}")
    print(f"  Gateway: {out.get('Gateway')}")

    if out.get("ReceiptId"):
        print("\n  [OK] SUCCESS: Receipt generated")
    else:
        print("\n  [FAIL] No receipt (CHECKOUT_TOKENS_MISSING or other gate error)")

    return out


async def test_old_capture_patterns(checkout_text: str):
    """Test old api.py capture patterns on raw checkout text."""
    if not checkout_text or len(checkout_text) < 500:
        print("\n[OLD CAPTURE TEST] No checkout text to test")
        return

    from BOT.Charge.Shopify.slf.api import capture, _capture_multi

    print("\n" + "=" * 70)
    print("OLD API.PY CAPTURE PATTERNS TEST")
    print("=" * 70)

    # Session token - old: serialized-session-token" content="&quot;" -> &quot
    pairs = [
        ('serialized-session-token" content="&quot;', '&quot'),
        ('serialized-sessionToken" content="&quot;', '&quot;"/>'),
    ]
    for prefix, suffix in pairs:
        try:
            v = capture(checkout_text, prefix, suffix)
            ln = len(v) if v else 0
            first = (v or "")[:60]
            print(f"  session [{prefix[:30]}...] -> [{suffix}]: len={ln} first60={first!r}")
        except Exception as e:
            print(f"  session [{prefix[:30]}...]: ERROR {e}")

    # Source token
    pairs = [
        ('serialized-source-token" content="&quot;', '&quot'),
        ('serialized-sourceToken" content="&quot;', '&quot;"/>'),
    ]
    for prefix, suffix in pairs:
        try:
            v = capture(checkout_text, prefix, suffix)
            ln = len(v) if v else 0
            first = (v or "")[:60]
            print(f"  source [{prefix[:30]}...] -> [{suffix}]: len={ln} first60={first!r}")
        except Exception as e:
            print(f"  source [{prefix[:30]}...]: ERROR {e}")

    # Queue token
    try:
        v = capture(checkout_text, 'queueToken&quot;:&quot;', '&quot')
        print(f"  queue [queueToken&quot;:&quot;] -> [&quot]: len={len(v) if v else 0} val={str(v)[:50]!r}")
    except Exception as e:
        print(f"  queue: ERROR {e}")

    # Stable ID
    try:
        v = capture(checkout_text, 'stableId&quot;:&quot;', '&quot')
        print(f"  stableId [stableId&quot;:&quot;] -> [&quot]: len={len(v) if v else 0} val={str(v)[:50]!r}")
    except Exception as e:
        print(f"  stableId: ERROR {e}")


async def main():
    url = (sys.argv[1] if len(sys.argv) > 1 else TEST_URLS[0]).strip()
    if not url.startswith("http"):
        url = "https://" + url

    proxy = None
    try:
        from BOT.tools.proxy import get_rotating_proxy
        proxy = get_rotating_proxy("0")
    except Exception:
        pass

    print("\n" + "#" * 70)
    print("# SHOPIFY GATE FULL END-TO-END TEST")
    print(f"# URL: {url}")
    print(f"# Proxy: {'Yes' if proxy else 'No'}")
    print("#" * 70)

    # 1. Diagnostic
    data = await run_diagnostic(url, proxy)
    full_text = (data or {}).get("checkout_text_full") or ""
    if full_text and len(full_text) > 500:
        await test_old_capture_patterns(full_text)

    # 2. Full checkout
    await run_full_checkout(url, proxy)

    print("\n" + "#" * 70)
    print("# TEST COMPLETE")
    print("#" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
