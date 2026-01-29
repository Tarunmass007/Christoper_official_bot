import random
import asyncio
from typing import Optional
from BOT.Charge.Shopify.api_endpoints import AUTOSHOPIFY_BASE_URL
from BOT.Charge.Shopify.tls_session import TLSAsyncSession

# User agents for requests
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

# Fallback product URLs - Multiple working Shopify and other e-commerce stores
# Mix of domain-only and full product URLs for better compatibility
FALLBACK_PRODUCT_URLS = [
    "https://3duxdesign.myshopify.com",  # Primary fallback URL
    "https://www.bountifulbaby.com",  # Domain-only format
    "https://kettleandfire.myshopify.com/products/bone-broth",
    "https://kobo-us.myshopify.com/products/clara-2e",
    "https://habit-nest.myshopify.com/products/morning-sidekick-journal",
    "https://junk-brands.myshopify.com/products/headband",
    "https://confetti-usa.myshopify.com/products/confetti-system",
    "https://nixplay.myshopify.com/products/smart-photo-frame",
    "https://coyotevest.myshopify.com/products/coyote-vest",
]

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # Exponential backoff in seconds

async def _make_request(card_data: str, site: str, proxy: Optional[str], headers: dict) -> dict:
    """
    Internal function to make a single request to AutoShopify backend

    Returns:
        dict with response data or error information
    """
    params = {
        "cc": card_data,
        "site": site
    }

    if proxy:
        params["proxy"] = proxy

    async with TLSAsyncSession(timeout_seconds=90, follow_redirects=True) as client:
        response = await client.get(
            AUTOSHOPIFY_BASE_URL,
            params=params,
            headers=headers,
        )

        response_text = response.text
        response_json = None

        try:
            response_json = response.json()
        except:
            pass

        return {
            "status_code": response.status_code,
            "text": response_text,
            "json": response_json
        }


def _parse_response(response_data: dict) -> dict:
    """
    Parse and interpret the AutoShopify response

    Returns:
        dict with status, message, and response
    """
    status_code = response_data["status_code"]
    response_text = response_data["text"]
    response_json = response_data["json"]

    if status_code == 200:
        response_lower = response_text.lower()

        # Check for specific error cases first
        if "handle is empty" in response_lower:
            return {
                "status": "ERROR",
                "message": "Product handle error. The product URL is invalid or the product doesn't exist.",
                "response": response_json or response_text,
                "should_retry_with_fallback": True
            }

        if "proposal step failed" in response_lower:
            return {
                "status": "ERROR",
                "message": "Checkout failed. The store may be blocking requests or the product is unavailable.",
                "response": response_json or response_text,
                "should_retry_with_fallback": True
            }

        if "receipt id is empty" in response_lower:
            return {
                "status": "ERROR",
                "message": "Receipt ID error. The checkout process failed. Trying with fallback URLs.",
                "response": response_json or response_text,
                "should_retry_with_fallback": True
            }

        # Check for success/decline/ccn indicators
        if any(word in response_lower for word in ["approved", "success", "charged", "cvv match"]):
            return {
                "status": "APPROVED",
                "message": response_text[:500],
                "response": response_json or response_text,
                "should_retry_with_fallback": False
            }
        elif any(word in response_lower for word in ["declined", "insufficient", "card declined"]):
            return {
                "status": "DECLINED",
                "message": response_text[:500],
                "response": response_json or response_text,
                "should_retry_with_fallback": False
            }
        elif any(word in response_lower for word in ["incorrect", "invalid", "wrong cvv"]):
            return {
                "status": "CCN",
                "message": response_text[:500],
                "response": response_json or response_text,
                "should_retry_with_fallback": False
            }
        else:
            return {
                "status": "UNKNOWN",
                "message": response_text[:500],
                "response": response_json or response_text,
                "should_retry_with_fallback": False
            }

    elif status_code == 403:
        return {
            "status": "ERROR",
            "message": "Backend service access denied (403). Network or proxy configuration issue.",
            "response": response_text[:200],
            "should_retry_with_fallback": False
        }

    elif status_code == 502 or status_code == 503:
        return {
            "status": "ERROR",
            "message": f"Backend service unavailable (HTTP {status_code}). Service may be down.",
            "response": response_text[:200],
            "should_retry_with_fallback": False
        }

    else:
        return {
            "status": "ERROR",
            "message": f"HTTP {status_code}: {response_text[:200]}",
            "response": response_text,
            "should_retry_with_fallback": False
        }


async def check_autoshopify(card_data: str, site: str = None, proxy: str = None) -> dict:
    """
    Check a card using the autoshopify service with retry and fallback logic

    Args:
        card_data: Card in format cc|mm|yy|cvv
        site: Optional site URL with product (defaults to fallback URLs)
        proxy: Optional proxy string

    Returns:
        dict with status, message, and response data
    """
    try:
        # Parse card data
        parts = card_data.split("|")
        if len(parts) != 4:
            return {
                "status": "ERROR",
                "message": "Invalid card format. Use: cc|mm|yy|cvv",
                "response": None
            }

        cc, mm, yy, cvv = parts

        # Prepare sites to try
        sites_to_try = []
        if site:
            # User provided a custom site - try it first
            sites_to_try.append(site)
            # Add fallback URLs as backup
            sites_to_try.extend(FALLBACK_PRODUCT_URLS[:3])
        else:
            # Use all fallback URLs
            sites_to_try = FALLBACK_PRODUCT_URLS.copy()

        # Random user agent
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9"
        }

        last_error = None

        # Try each site
        for site_index, current_site in enumerate(sites_to_try):
            # Try with retries for network errors
            for attempt in range(MAX_RETRIES):
                try:
                    # Make request
                    response_data = await _make_request(card_data, current_site, proxy, headers)

                    # Parse response
                    result = _parse_response(response_data)

                    # If successful or definitive result, return it
                    if result["status"] in ["APPROVED", "DECLINED", "CCN"]:
                        return result

                    # If error but shouldn't retry with fallback, return error
                    if not result.get("should_retry_with_fallback", False):
                        last_error = result
                        # For network/backend errors, try retry
                        if "Backend service" in result["message"] or "HTTP" in result["message"]:
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAYS[attempt])
                                continue
                        return result

                    # Should retry with next site
                    last_error = result
                    break  # Break retry loop, try next site

                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])
                        continue
                    else:
                        last_error = {
                            "status": "ERROR",
                            "message": f"Error: {str(e)}",
                            "response": None
                        }
                        break

        # All sites and retries exhausted
        if last_error:
            last_error["message"] = f"{last_error['message']} (Tried {len(sites_to_try)} different stores)"
            return last_error

        return {
            "status": "ERROR",
            "message": "All attempts failed. Backend service may be unavailable.",
            "response": None
        }

    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Unexpected error: {str(e)}",
            "response": None
        }
