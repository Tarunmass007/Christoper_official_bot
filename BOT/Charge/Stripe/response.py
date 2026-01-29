"""
Stripe Charge Response Formatter
Professional response formatting for Stripe $20 Charge results.
"""

from datetime import datetime
from time import time

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None


def format_stripe_charge_response(card_data: str, result: dict, start_time: float, user_info: dict = None) -> str:
    """
    Format the Stripe $20 Charge response.

    Args:
        card_data: Full card details (cc|mm|yy|cvv)
        result: Result dictionary from check_stripe_charge
        start_time: Start time of the check
        user_info: User information dict

    Returns:
        Formatted HTML message string
    """
    end_time = time()
    time_taken = round(end_time - start_time, 2)

    # Parse card data
    card_parts = card_data.split('|')
    card_number = card_parts[0] if len(card_parts) > 0 else "Unknown"
    bin_number = card_number[:6]

    # Determine status emoji and message
    status = result.get("status", "error")
    message = result.get("response", "UNKNOWN_ERROR")

    if status == "charged":
        status_text = "Charged 💎"
        header = "CHARGED"
    elif status == "approved":
        status_text = "Approved ✅"
        header = "CCN LIVE"
    elif status == "declined":
        status_text = "Declined ❌"
        header = "DECLINED"
    else:
        status_text = "Error ⚠️"
        header = "ERROR"

    # Get user info
    plan = user_info.get("plan", "Free") if user_info else "Free"
    badge = user_info.get("badge", "🎟️") if user_info else "🎟️"
    checked_by = user_info.get("checked_by", "Unknown") if user_info else "Unknown"

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
    response = f"""<b>[#Stripe] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card_data}</code>
<b>[•] Gateway:</b> <code>Stripe Balliante $20</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{message}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_number}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code> | <b>Proxy:</b> <code>Live ⚡️</code>"""

    return response
