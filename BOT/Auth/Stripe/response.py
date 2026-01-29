"""
Stripe Auth Response Formatter
Professional response formatting for Stripe Auth results.
"""

from datetime import datetime

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None


def format_stripe_response(card, mes, ano, cvv, result, timetaken, gateway="Stripe Auth"):
    """
    Format Stripe Auth response for Telegram.

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV code
        result: Result dict from stripe auth
        timetaken: Time taken in seconds
        gateway: Gateway name

    Returns:
        Formatted string for Telegram
    """
    fullcc = f"{card}|{mes}|{ano}|{cvv}"
    bin_number = card[:6]

    status = result.get("status", "error")
    response = result.get("response", "Unknown error")

    # Status emojis and text
    if status == "approved":
        if "AUTH_SUCCESS" in response or "CARD_ADDED" in response:
            status_text = "Approved ✅"
            header = "APPROVED"
        else:
            status_text = "CCN Live ✅"
            header = "CCN LIVE"
    elif status == "declined":
        status_text = "Declined ❌"
        header = "DECLINED"
    else:
        status_text = "Error ⚠️"
        header = "ERROR"

    # BIN lookup
    bin_data = get_bin_details(bin_number) if get_bin_details else None
    if bin_data:
        vendor = bin_data.get('vendor', 'N/A')
        card_type = bin_data.get('type', 'N/A')
        level = bin_data.get('level', 'N/A')
        bank = bin_data.get('bank', 'N/A')
        country = bin_data.get('country', 'N/A')
        country_flag = bin_data.get('flag', '🏳️')
    else:
        vendor = "N/A"
        card_type = "N/A"
        level = "N/A"
        bank = "N/A"
        country = "N/A"
        country_flag = "🏳️"

    # Format response in original style
    formatted = f"""<b>[#StripeAuth] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>{gateway}</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{response}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_number}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{timetaken}s</code> | <b>Proxy:</b> <code>Live ⚡️</code>"""

    return formatted
