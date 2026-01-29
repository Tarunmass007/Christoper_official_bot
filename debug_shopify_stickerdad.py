#!/usr/bin/env python3
"""
Debug script for Shopify gate (stickerdad.com).
Runs the full flow step-by-step and prints results for debugging addurl/API issues.
Uses same flow as /addurl: cloudscraper-first for products, captcha retry for gate.
Usage: python debug_shopify_stickerdad.py
"""
import asyncio
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

URL = "https://stickerdad.com"
TEST_CARD = "4111111111111111|12|2026|123"


async def main():
    from BOT.Charge.Shopify.tls_session import TLSAsyncSession
    from BOT.Charge.Shopify.slf.api import (
        autoshopify,
        autoshopify_with_captcha_retry,
        _get_checkout_url_from_cart_response,
    )
    from BOT.Charge.Shopify.slf.addurl import (
        normalize_url,
        fetch_products_json,
        find_lowest_variant_from_products,
        validate_and_parse_site,
        test_site_with_card,
    )

    print("=== Shopify Gate Debug: stickerdad.com ===\n")

    # 1. Normalize URL
    norm = normalize_url(URL)
    print(f"[1] Normalized URL: {norm}")

    # 2. Fetch products.json
    print("\n[2] Fetching /products.json ...")
    async with TLSAsyncSession(timeout_seconds=30) as session:
        products = await fetch_products_json(session, norm, proxy=None)
    if not products:
        print("    FAIL: No products returned (not Shopify or blocked)")
        return
    print(f"    OK: {len(products)} products")

    # 3. Lowest variant
    lowest = find_lowest_variant_from_products(products)
    if not lowest:
        print("    FAIL: No parseable variants")
        return
    print(f"    Lowest: ${lowest['price']:.2f} (variant id: {lowest['variant'].get('id')})")

    # 4. Validate site (full parse)
    print("\n[3] validate_and_parse_site ...")
    async with TLSAsyncSession(timeout_seconds=30) as session:
        result = await validate_and_parse_site(URL, session, proxy=None)
    if not result.get("valid"):
        print(f"    FAIL: {result.get('error', 'Unknown')}")
        return
    print(f"    OK: price={result.get('price')}, product_id={result.get('product_id')}")

    # 5. Full gate test (autoshopify_with_captcha_retry = same as /addurl)
    print("\n[4] Full gate test (autoshopify_with_captcha_retry with test card) ...")
    async with TLSAsyncSession(timeout_seconds=60) as session:
        out = await autoshopify_with_captcha_retry(URL, TEST_CARD, session, max_captcha_retries=3, proxy=None)
    resp = out.get("Response", "")
    rid = out.get("ReceiptId")
    print(f"    Response: {resp[:80]}")
    print(f"    ReceiptId: {rid}")
    if rid:
        print("    OK: Gate returned receipt (site is valid for addurl)")
    else:
        print("    FAIL: No receipt (check Response above for token/API errors)")

    # 6. addurl test_site_with_card wrapper
    print("\n[5] test_site_with_card (addurl wrapper) ...")
    has_rec, res = await test_site_with_card(URL, None, max_retries=2)
    print(f"    has_receipt: {has_rec}")
    print(f"    Response: {(res.get('Response') or '')[:80]}")
    print(f"    ReceiptId: {res.get('ReceiptId')}")

    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
