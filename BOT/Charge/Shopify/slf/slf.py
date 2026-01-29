"""
Shopify SLF Module
Uses the complete autoshopify checkout flow for real card checking.
Sites and proxy from store (MongoDB or JSON).
"""

from typing import Optional, Dict, Any

from BOT.Charge.Shopify.slf.api import autoshopify
from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.tools.proxy import get_rotating_proxy
from BOT.Charge.Shopify.slf.site_manager import get_primary_site


def get_site(user_id: str) -> Optional[str]:
    """Get user's saved primary site from store (user_sites)."""
    site = get_primary_site(str(user_id))
    return (site.get("url") or None) if site else None


def get_site_info(user_id: str) -> Optional[Dict[str, str]]:
    """Get user's full site info (site + gateway) from store."""
    site = get_primary_site(str(user_id))
    if not site:
        return None
    return {
        "site": site.get("url"),
        "gateway": site.get("gateway", "Unknown"),
        "price": site.get("price", "N/A"),
    }


# Maximum retries for CAPTCHA
MAX_CAPTCHA_RETRIES = 3


async def check_card(user_id: str, cc: str, site: Optional[str] = None) -> str:
    """
    Check a card on user's saved Shopify site.
    Uses the full autoshopify checkout flow for real results.
    Includes CAPTCHA retry logic.
    
    Args:
        user_id: User ID to look up site
        cc: Card in format cc|mm|yy|cvv
        site: Optional site URL (uses user's saved site if not provided)
    
    Returns:
        Response string (e.g., "ORDER_PLACED", "CARD_DECLINED", "3DS_REQUIRED")
    """
    import asyncio
    
    # Get site if not provided
    if not site:
        site = get_site(user_id)
    
    if not site:
        return "SITE_NOT_FOUND"
    
    # Get user's proxy
    try:
        user_proxy = get_rotating_proxy(int(user_id))
    except:
        user_proxy = None
    
    retry_count = 0
    response = "UNKNOWN_ERROR"
    
    while retry_count < MAX_CAPTCHA_RETRIES:
        try:
            async with TLSAsyncSession(timeout_seconds=120, proxy=user_proxy) as session:
                result = await autoshopify(site, cc, session)
            
            # Return the response string from the full checkout
            response = result.get("Response", "UNKNOWN_ERROR")
            
            # Check if CAPTCHA - retry if so
            response_upper = response.upper()
            if any(x in response_upper for x in ["CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE"]):
                retry_count += 1
                if retry_count < MAX_CAPTCHA_RETRIES:
                    await asyncio.sleep(2)  # Brief pause before retry
                    continue
            
            return response
            
        except Exception as e:
            error_msg = str(e)[:80]
            if "timeout" in error_msg.lower():
                return "TIMEOUT"
            elif "connection" in error_msg.lower():
                return "CONNECTION_ERROR"
            return f"ERROR: {error_msg}"
    
    return response  # Return last response after all retries


async def check_card_full(user_id: str, cc: str, site: Optional[str] = None) -> Dict[str, Any]:
    """
    Check a card and return full result dictionary.
    Uses the full autoshopify checkout flow.
    Includes CAPTCHA retry logic.
    
    Args:
        user_id: User ID to look up site
        cc: Card in format cc|mm|yy|cvv
        site: Optional site URL
    
    Returns:
        Full result dictionary with Response, Status, Gateway, Price, cc
    """
    import asyncio
    
    # Get site if not provided
    if not site:
        site = get_site(user_id)
    
    if not site:
        return {
            "Response": "SITE_NOT_FOUND",
            "Status": False,
            "Gateway": "Unknown",
            "Price": "0.00",
            "cc": cc
        }
    
    # Get user's proxy
    try:
        user_proxy = get_rotating_proxy(int(user_id))
    except:
        user_proxy = None
    
    retry_count = 0
    result = None
    
    while retry_count < MAX_CAPTCHA_RETRIES:
        try:
            async with TLSAsyncSession(timeout_seconds=120, proxy=user_proxy) as session:
                result = await autoshopify(site, cc, session)
            
            # Check if CAPTCHA - retry if so
            response_upper = str(result.get("Response", "")).upper()
            if any(x in response_upper for x in ["CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE"]):
                retry_count += 1
                if retry_count < MAX_CAPTCHA_RETRIES:
                    await asyncio.sleep(2)
                    continue
            
            # Ensure all required fields are present
            return {
                "Response": result.get("Response", "UNKNOWN_ERROR"),
                "Status": result.get("Status", False),
                "Gateway": result.get("Gateway", "Unknown"),
                "Price": result.get("Price", "0.00"),
                "cc": result.get("cc", cc),
                "ReceiptId": result.get("ReceiptId")
            }
            
        except Exception as e:
            return {
                "Response": str(e)[:80],
                "Status": False,
                "Gateway": "Unknown",
                "Price": "0.00",
                "cc": cc
            }
    
    # Return last result after all retries
    if result:
        return {
            "Response": result.get("Response", "MAX_RETRIES_EXCEEDED"),
            "Status": result.get("Status", False),
            "Gateway": result.get("Gateway", "Unknown"),
            "Price": result.get("Price", "0.00"),
            "cc": result.get("cc", cc),
            "ReceiptId": result.get("ReceiptId")
        }
    
    return {
        "Response": "MAX_RETRIES_EXCEEDED",
        "Status": False,
        "Gateway": "Unknown",
        "Price": "0.00",
        "cc": cc
    }
