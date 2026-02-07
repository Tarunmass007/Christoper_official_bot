"""Test just the low product API fetch."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.slf.api import _fetch_low_product_api

async def main():
    domain = "collagesoup.com"
    print(f"Fetching low product API for {domain}...")
    async with TLSAsyncSession(timeout_seconds=15, proxy=None) as session:
        result = await asyncio.wait_for(
            _fetch_low_product_api(domain, session, None),
            timeout=30.0
        )
    print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
