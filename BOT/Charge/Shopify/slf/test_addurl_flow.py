"""
Test addurl flow end-to-end - simulates /addurl for collagesoup.com
Captures exact flow and errors for debugging.
Run: python -m BOT.Charge.Shopify.slf.test_addurl_flow
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.slf.addurl import validate_and_parse_site, test_site_with_card, TEST_CARD


async def main():
    url = "https://collagesoup.com"
    print(f"\n{'='*60}")
    print(f"ADDURL FLOW TEST: {url}")
    print("="*60)

    # Step 1: validate_and_parse_site
    print("\n[1] validate_and_parse_site...")
    try:
        async with TLSAsyncSession(timeout_seconds=25, proxy=None) as session:
            result = await validate_and_parse_site(url, session, None)
        print(f"    valid: {result.get('valid')}")
        print(f"    price: {result.get('price')}")
        print(f"    error: {result.get('error')}")
        if not result.get("valid"):
            print("    SKIP - site not valid")
            return
    except Exception as e:
        print(f"    Exception: {e}")
        return

    # Step 2: test_site_with_card (1 attempt, 10 captcha retries inside)
    print("\n[2] test_site_with_card (1 attempt, 10 captcha retries)...")
    try:
        has_rec, test_res = await asyncio.wait_for(
            test_site_with_card(url, proxy=None, max_retries=1),
            timeout=180.0
        )
    except asyncio.TimeoutError:
        print("    TIMEOUT after 180s")
        return
    print(f"    has_receipt: {has_rec}")
    print(f"    Response: {test_res.get('Response')}")
    print(f"    ReceiptId: {test_res.get('ReceiptId')}")
    print(f"    Price: {test_res.get('Price')}")

    if has_rec:
        print("\n[OK] Site would be SAVED by addurl")
    else:
        err = (test_res.get("Response") or "NO_RECEIPT").strip()
        print(f"\n[FAIL] Gate error: {err}")
        if "CAPTCHA" in err.upper():
            print("    -> CAPTCHA_REQUIRED: captcha solver did not produce valid token")


if __name__ == "__main__":
    asyncio.run(main())
