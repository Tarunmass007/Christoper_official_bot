"""
Quick addurl test - single attempt, minimal retries.
Run: python -m BOT.Charge.Shopify.slf.test_addurl_quick
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.slf.api import autoshopify_with_captcha_retry
from BOT.Charge.Shopify.slf.addurl import TEST_CARD


async def main():
    # Try different stores - some may have lighter captcha or complete faster
    urls_to_try = ["https://collagesoup.com", "https://stickerdad.com"]
    url = urls_to_try[0]
    print(f"Quick test: {url}")
    print("Running autoshopify_with_captcha_retry (max_captcha_retries=1)...")
    try:
        async with TLSAsyncSession(timeout_seconds=30, proxy=None) as session:
            res = await asyncio.wait_for(
                autoshopify_with_captcha_retry(url, TEST_CARD, session, max_captcha_retries=1, proxy=None),
                timeout=300.0
            )
        print(f"Response: {res.get('Response')}")
        print(f"Status: {res.get('Status')}")
        print(f"ReceiptId: {res.get('ReceiptId')}")
    except asyncio.TimeoutError:
        print("TIMEOUT")
    except Exception as e:
        print(f"Exception: {e}")


if __name__ == "__main__":
    asyncio.run(main())
