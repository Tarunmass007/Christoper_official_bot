import requests
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=10)

# VBV API configuration
VBV_API_BASE_URL = "https://api.voidapi.xyz/v2/vbv"
VBV_API_KEY = "VDX-SHA2X-NZ0RS-O7HAM"

# Successful VBV authentication responses
VBV_SUCCESS_RESPONSES = [
    "authenticate_successful",
    "authenticate_attempt_successful",
    "authenticate_passed",
    "authenticate_approved",
    "authenticate_verified"
]


def check_vbv(card, mes, ano, cvv):
    """
    Check VBV (Verified by Visa) status using voidapi.xyz

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year (2 or 4 digits)
        cvv: CVV code

    Returns:
        dict with status and response
    """
    try:
        # Normalize year format to 4 digits
        if len(ano) == 2:
            ano = f"20{ano}"

        # Format card data as required by API: card|mm|yyyy|cvv
        card_string = f"{card}|{mes}|{ano}|{cvv}"

        # Build API URL with parameters
        params = {
            "key": VBV_API_KEY,
            "card": card_string
        }

        # Make request to VBV API
        response = requests.get(
            VBV_API_BASE_URL,
            params=params,
            timeout=30
        )

        # Check response status
        if response.status_code != 200:
            return {
                "status": "error",
                "response": f"API Error: HTTP {response.status_code}"
            }

        # Parse response
        try:
            data = response.json()
        except:
            # If not JSON, treat as text response
            response_text = response.text.strip().lower()

            # Check if response contains any success indicator
            for success_response in VBV_SUCCESS_RESPONSES:
                if success_response.lower() in response_text:
                    return {
                        "status": "approved",
                        "response": f"VBV Authenticated ✓ - {success_response}"
                    }

            return {
                "status": "declined",
                "response": response_text or "VBV Authentication Failed"
            }

        # Handle JSON response
        if isinstance(data, dict):
            # Check for status field
            if "status" in data:
                status_value = str(data.get("status", "")).lower()

                # Check if status indicates success
                for success_response in VBV_SUCCESS_RESPONSES:
                    if success_response.lower() in status_value:
                        return {
                            "status": "approved",
                            "response": f"VBV Authenticated ✓ - {data.get('status')}"
                        }

                return {
                    "status": "declined",
                    "response": data.get("message", data.get("status", "VBV Failed"))
                }

            # Check for message field
            if "message" in data:
                message_value = str(data.get("message", "")).lower()

                for success_response in VBV_SUCCESS_RESPONSES:
                    if success_response.lower() in message_value:
                        return {
                            "status": "approved",
                            "response": f"VBV Authenticated ✓ - {data.get('message')}"
                        }

                return {
                    "status": "declined",
                    "response": data.get("message", "VBV Authentication Failed")
                }

            # Check for response field
            if "response" in data:
                response_value = str(data.get("response", "")).lower()

                for success_response in VBV_SUCCESS_RESPONSES:
                    if success_response.lower() in response_value:
                        return {
                            "status": "approved",
                            "response": f"VBV Authenticated ✓ - {data.get('response')}"
                        }

                return {
                    "status": "declined",
                    "response": data.get("response", "VBV Failed")
                }

            # No recognized fields, check entire response
            response_str = str(data).lower()
            for success_response in VBV_SUCCESS_RESPONSES:
                if success_response.lower() in response_str:
                    return {
                        "status": "approved",
                        "response": f"VBV Authenticated ✓"
                    }

            return {
                "status": "declined",
                "response": str(data)
            }

        # Handle non-dict JSON response
        response_str = str(data).lower()
        for success_response in VBV_SUCCESS_RESPONSES:
            if success_response.lower() in response_str:
                return {
                    "status": "approved",
                    "response": f"VBV Authenticated ✓ - {data}"
                }

        return {
            "status": "declined",
            "response": str(data)
        }

    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "response": "Request timeout - API took too long to respond"
        }
    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "response": "Connection error - Unable to reach VBV API"
        }
    except Exception as e:
        return {
            "status": "error",
            "response": f"Error: {str(e)}"
        }


async def async_check_vbv(card, mes, ano, cvv):
    """
    Async wrapper for VBV checking

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV code

    Returns:
        dict with status and response
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, check_vbv, card, mes, ano, cvv)
