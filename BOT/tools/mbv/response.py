def format_mbv_response(card, mes, ano, cvv, result, timetaken, gateway="MBV Checker"):
    """
    Format MBV response for Telegram

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV code
        result: Result dict from MBV check
        timetaken: Time taken in seconds
        gateway: Gateway name

    Returns:
        Formatted string for Telegram
    """
    fullcc = f"{card}|{mes}|{ano}|{cvv}"

    status = result.get("status", "error")
    response = result.get("response", "Unknown error")

    # Status emojis
    if status == "approved":
        status_emoji = "✅"
        status_text = "MBV Passed"
    elif status == "declined":
        status_emoji = "❌"
        status_text = "MBV Failed"
    else:
        status_emoji = "⚠️"
        status_text = "Error"

    formatted = f"""<pre>━━━━━ MBV Checker ━━━━━</pre>
<b>Card:</b> <code>{fullcc}</code>
<b>Status:</b> <code>{status_text} {status_emoji}</code>
<b>Response:</b> <code>{response}</code>
━━━━━━━━━━━━━━━
<b>⏱️ Time:</b> <code>{timetaken}s</code>
<b>Gateway:</b> <code>{gateway}</code>"""

    return formatted
