# PayPal Checkout Gate (Standalone)

Standalone PayPal donation checker for **GiveWP → PayPal Guest** flow (e.g. elemotion.org/donate).  
**Not linked to the bot.** Run from terminal; uses `cc.txt`, `proxy.txt`; writes hits to `results.txt`.

## Requirements

- Python 3.8+
- `pip install requests`
- Optional: `pip install cloudscraper` (for Cloudflare bypass on donate page)

## Files

| File        | Purpose |
|------------|---------|
| `cc.txt`   | One CC per line (see format below). |
| `proxy.txt`| One proxy per line: `http://user:pass@host:port` or `host:port`. |
| `results.txt` | Live CCs appended here (one per line). |

## CC format (`cc.txt`)

```
number|month|year|cvv
number|month|year|cvv|first|last|email
```

Examples:

```
4815820997382518|08|27|183
4833160289037902|08|27|350|Mass|TH|mass652004@gmail.com
```

## Proxy format (`proxy.txt`)

```
http://user:pass@host:port
host:port
```

One proxy per line; lines starting with `#` are ignored.

## Usage

From project root:

```bash
cd PAYPAL_GATE
python paypal_checkout.py
```

With custom paths:

```bash
python paypal_checkout.py --cc path/to/cc.txt --proxy path/to/proxy.txt --results path/to/results.txt
```

Options:

- `--cc`      Path to CC file (default: `cc.txt` in script dir).
- `--proxy`  Path to proxy file (default: `proxy.txt`).
- `--results` Path to results file (default: `results.txt`).
- `--site`   Donate page URL (default: `https://elemotion.org/donate/`).
- `--amount` Donation amount (default: `5.00`).

## Flow (what the script does)

1. **GiveWP**
   - GET donate page → parse `give_form_id`, `give-form-hash`, `give_form_id_prefix`.
   - POST `give_donation_form_reset_all_nonce`.
   - POST `give_load_gateway` (payment-mode=paypal) → get/refresh nonce.
   - POST `give_process_donation` (first, last, email, amount, paypal) → get redirect URL to PayPal.

2. **PayPal**
   - Extract `token` from redirect URL.
   - GET `paypal.com/donate/?token=...` (optional: parse CSRF).
   - POST `/US/welcome/donate` (guest account + card) or POST `getCardData` → get `encryptedAccountNumber` (and optional `shippingAddressId`).
   - POST `donate/guest/onboarding` with `encryptedAccountNumber`, CVV, token.
   - GET final `paypal.com/donate/?token=...&country.x=US&locale.x=US` → parse success/failure.

3. **Output**
   - Terminal: `LIVE` or `DEAD - <message>` per CC.
   - Live CCs (full `number|month|year|cvv`) appended to `results.txt`.

## Notes

- **Cloudflare / DataDome**: elemotion.org and PayPal use Cloudflare/DataDome. With no proxy or bad proxy you may get blocked. Use residential proxies in `proxy.txt` and install `cloudscraper` for better success on the donate page.
- **Cookies**: The script uses a single `requests.Session()` (or cloudscraper session) so cookies from GiveWP and PayPal are kept automatically. For local testing with browser cookies, you’d need to add optional cookie loading (not included here).
- **PayPal guest flow**: PayPal’s donate guest flow expects browser-like requests (CSRF, fingerprint, etc.). If you get “no encryptedAccountNumber” or repeated blocks, run once in a browser, solve any captcha, then consider using the same proxy/cookies or a stronger anti-detect setup.

## Example run

```
============================================================
PayPal Checkout Gate (standalone)
============================================================
CC file: PAYPAL_GATE\cc.txt (5 lines)
Proxy file: PAYPAL_GATE\proxy.txt (10 proxies)
Results: PAYPAL_GATE\results.txt
Site: https://elemotion.org/donate/  Amount: 5.00
============================================================
[1/5] Checking... DEAD - GiveWP: failed to load donate page
[2/5] Checking... DEAD - PayPal: no encryptedAccountNumber
[3/5] Checking... LIVE
...
============================================================
Done. Hits appended to PAYPAL_GATE\results.txt
```
