"""
Quick test for captcha solver only - no full gate.
Run: python -m BOT.Charge.Shopify.slf.test_captcha_solver
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from BOT.helper.shopify_captcha_solver import _solve_hcaptcha_playwright


async def main():
    url = "https://stickerdad.com/checkout"
    print(f"Testing Playwright solver: {url}")
    print("(timeout 30s)...")
    try:
        result = await _solve_hcaptcha_playwright(
            url, timeout=50, proxy=None, page_html=None, headless=True
        )
        print(f"Success: {result.success}")
        print(f"Token: {(result.token[:60] + '...') if result.token and len(result.token) > 60 else result.token}")
        print(f"Method: {result.method}")
        print(f"Error: {result.error}")
    except Exception as e:
        print(f"Exception: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
