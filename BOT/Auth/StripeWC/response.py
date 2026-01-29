"""
Response formatter for Stripe WooCommerce Auth
"""

def format_stripe_wc_response(card, mes, ano, cvv, status, response, timetaken, gateway, user_name, user_id, plan, badge):
    """
    Format Stripe WooCommerce Auth response message

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV
        status: approved/declined/error
        response: Response message
        timetaken: Time taken in seconds
        gateway: Gateway name
        user_name: User's first name
        user_id: User's Telegram ID
        plan: User's plan
        badge: User's badge

    Returns:
        Formatted HTML message string
    """
    fullcc = f"{card}|{mes}|{ano}|{cvv}"

    # Status emoji
    if status == "approved":
        status_emoji = "✅"
        status_text = "Approved"
    elif status == "declined":
        status_emoji = "❌"
        status_text = "Declined"
    else:
        status_emoji = "⚠️"
        status_text = "Error"

    from datetime import datetime
    current_time = datetime.now().strftime("%I:%M %p")

    checked_by = f"<a href='tg://user?id={user_id}'>{user_name}</a>"

    message = f"""<pre>━━━ Stripe WooCommerce Auth ━━━</pre>
<b>Card:</b> <code>{fullcc}</code>
<b>Status:</b> <code>{status_text} {status_emoji}</code>
<b>Response:</b> <code>{response}</code>
━━━━━━━━━━━━━━━
<b>⏱️ Time:</b> <code>{timetaken}s</code>
<b>Gateway:</b> <code>{gateway}</code>
<b>Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>"""

    return message
