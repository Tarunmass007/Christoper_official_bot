"""Minimal test - just fetch low product API and run one autoshopify."""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

# Skip Playwright for speed
os.environ["SHOPIFY_SKIP_CAPTCHA_PLAYWRIGHT"] = "1"

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.slf.api import autoshopify
from BOT.Charge.Shopify.slf.addurl import TEST_CARD

async def main():
    url = "https://collagesoup.com"
    print(f"Minimal: {url} (no Playwright)")
    async with TLSAsyncSession(timeout_seconds=25, proxy=None) as session:
        res = await asyncio.wait_for(
            autoshopify(url, TEST_CARD, session, None),
            timeout=60.0
        )
    print(f"Response: {res.get('Response')}")
    print(f"ReceiptId: {res.get('ReceiptId')}")

if __name__ == "__main__":
    asyncio.run(main())
