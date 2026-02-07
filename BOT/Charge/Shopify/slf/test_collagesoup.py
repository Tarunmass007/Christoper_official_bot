"""
Test full autoshopify flow for collagesoup.com - simulates addurl validation.
Run: python -m BOT.Charge.Shopify.slf.test_collagesoup
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.slf.api import autoshopify_with_captcha_retry
from BOT.Charge.Shopify.slf.addurl import test_site_with_card, TEST_CARD


async def main():
    url = "https://collagesoup.com"
    print(f"\n{'='*60}")
    print(f"FULL GATE TEST: {url}")
    print("=" * 60)
    print(f"\nTest card: {TEST_CARD}")
    print("\n[1] Running autoshopify_with_captcha_retry (same as addurl)...")
    try:
        async with TLSAsyncSession(timeout_seconds=30, proxy=None) as session:
            res = await autoshopify_with_captcha_retry(
                url, TEST_CARD, session, max_captcha_retries=2, proxy=None
            )
        print(f"\n[2] Result:")
        print(f"    Response: {res.get('Response')}")
        print(f"    Status: {res.get('Status')}")
        print(f"    ReceiptId: {res.get('ReceiptId')}")
        print(f"    Price: {res.get('Price')}")
        print(f"    Gateway: {res.get('Gateway')}")
        if res.get("ReceiptId"):
            print("\n[OK] SUCCESS - Site would be saved by addurl")
        else:
            print("\n[FAIL] Gate error (no receipt)")
    except Exception as e:
        print(f"\n[EXCEPTION] {e}")
        import traceback
        traceback.print_exc()

    print("\n[3] Running test_site_with_card (addurl validation)...")
    has_receipt, result = await test_site_with_card(url, proxy=None, max_retries=1)
    print(f"    has_receipt: {has_receipt}")
    print(f"    Response: {result.get('Response')}")
    if has_receipt:
        print("\n[OK] addurl would SAVE this site")
    else:
        print("\n[FAIL] addurl would NOT save (no receipt)")


if __name__ == "__main__":
    asyncio.run(main())
