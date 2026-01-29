import time

def format_response(card_data: str, result: dict, start_time: float, user_info: dict = None) -> str:
    """
    Format the autoshopify check response for Telegram

    Args:
        card_data: Card in format cc|mm|yy|cvv
        result: Result dict from api.check_autoshopify
        start_time: Request start time
        user_info: Optional user information

    Returns:
        Formatted HTML message
    """
    elapsed = round(time.time() - start_time, 2)

    # Parse card for display
    parts = card_data.split("|")
    if len(parts) == 4:
        cc, mm, yy, cvv = parts
        card_display = f"{cc}|{mm}|{yy}|{cvv}"
    else:
        card_display = card_data

    # Status emoji
    status_emoji = {
        "APPROVED": "✅",
        "DECLINED": "❌",
        "CCN": "⚠️",
        "ERROR": "🚫",
        "UNKNOWN": "❓"
    }

    status = result.get("status", "UNKNOWN")
    emoji = status_emoji.get(status, "❓")
    message = result.get("message", "No message")

    # Build response
    response_text = f"""<b>AutoShopify Card Check</b>

{emoji} <b>Status:</b> {status}

<b>Card:</b> <code>{card_display}</code>

<b>Response:</b>
<pre>{message}</pre>

<b>Gateway:</b> AutoShopify
<b>Time:</b> {elapsed}s
"""

    if user_info:
        response_text += f"\n<b>Checked by:</b> {user_info.get('name', 'Unknown')} [{user_info.get('id', 'N/A')}]"

    return response_text


def format_mass_response(results: list, total_time: float, user_info: dict = None) -> str:
    """
    Format mass check results

    Args:
        results: List of (card_data, result) tuples
        total_time: Total execution time
        user_info: Optional user information

    Returns:
        Formatted HTML message
    """
    approved = sum(1 for _, r in results if r.get("status") == "APPROVED")
    declined = sum(1 for _, r in results if r.get("status") == "DECLINED")
    ccn = sum(1 for _, r in results if r.get("status") == "CCN")
    errors = sum(1 for _, r in results if r.get("status") == "ERROR")
    unknown = sum(1 for _, r in results if r.get("status") == "UNKNOWN")

    response_text = f"""<b>AutoShopify Mass Check Results</b>

<b>Total Cards:</b> {len(results)}
✅ <b>Approved:</b> {approved}
❌ <b>Declined:</b> {declined}
⚠️ <b>CCN:</b> {ccn}
🚫 <b>Errors:</b> {errors}
❓ <b>Unknown:</b> {unknown}

<b>Time:</b> {round(total_time, 2)}s
<b>Avg:</b> {round(total_time / len(results), 2)}s per card

<b>Detailed Results:</b>
"""

    for card_data, result in results:
        status = result.get("status", "UNKNOWN")
        emoji = {
            "APPROVED": "✅",
            "DECLINED": "❌",
            "CCN": "⚠️",
            "ERROR": "🚫",
            "UNKNOWN": "❓"
        }.get(status, "❓")

        # Truncate card for display
        card_short = card_data[:19] + "..." if len(card_data) > 22 else card_data
        msg = result.get("message", "No message")[:50]

        response_text += f"\n{emoji} <code>{card_short}</code> - {status}"

    if user_info:
        response_text += f"\n\n<b>Checked by:</b> {user_info.get('name', 'Unknown')} [{user_info.get('id', 'N/A')}]"

    return response_text
