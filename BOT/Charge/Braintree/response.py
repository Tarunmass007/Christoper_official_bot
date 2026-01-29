from datetime import datetime


def format_response(card_data: str, result: dict, start_time: float, user_info: dict = None) -> str:
    """
    Format the Braintree check response

    Args:
        card_data: Full card details (cc|mm|yy|cvv)
        result: Result dictionary from check_braintree
        start_time: Start time of the check
        user_info: User information dict with plan, badge, etc.

    Returns:
        Formatted HTML message string
    """
    from time import time

    end_time = time()
    time_taken = round(end_time - start_time, 2)

    # Parse card data
    card_parts = card_data.split('|')
    card_number = card_parts[0]
    bin_number = card_number[:6]
    last4 = card_number[-4:]

    # Determine status emoji and message
    status = result.get("status", "error")
    message = result.get("message", "UNKNOWN_ERROR")

    if status == "approved":
        status_emoji = "✅"
        status_text = "Approved"
    elif status == "declined":
        status_emoji = "❌"
        status_text = "Declined"
    else:
        status_emoji = "⚠️"
        status_text = "Error"

    # Get user info
    plan = user_info.get("plan", "Free") if user_info else "Free"
    badge = user_info.get("badge", "🎟️") if user_info else "🎟️"
    checked_by = user_info.get("checked_by", "Unknown") if user_info else "Unknown"

    # Current time
    current_time = datetime.now().strftime("%I:%M %p")

    # Format response
    response = f"""<pre>✦ Braintree Checker</pre>
━━━━━━━━━━━━━━━
<b>Card:</b> <code>{card_data}</code>
<b>Status:</b> <code>{status_text} {status_emoji}</code>
<b>Response:</b> <code>{message}</code>
━━━━━━━━━━━━━━━
<b>BIN:</b> <code>{bin_number}xxxxxx{last4}</code>
<b>Gateway:</b> <code>Braintree - Pixorize</code>
<b>Time:</b> <code>{time_taken}s</code>
━━━━━━━━━━━━━━━
<b>Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>
━━━━━━━━━━━━━━━"""

    return response
