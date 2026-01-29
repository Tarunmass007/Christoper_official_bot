from TOOLS.getbin import get_bin_details
from BOT.helper.start import load_users  # Load user database

def format_shopify_response(cc, mes, ano, cvv, raw_response, timet, profile):
    fullcc = f"{cc}|{mes}|{ano}|{cvv}"
    gateway = "Shopify Normal 1£"

    if raw_response is None:
        raw_response = "-"
    else:
        raw_response = str(raw_response)

    # Determine status
    if "ORDER_CONFIRMED" in raw_response:
        status_flag = "Charged 💎"
    elif any(x in raw_response for x in ["3DS", "INSUFFICIENT_FUNDS", "3DS_REQUIRED", "MISMATCHED", "MISMATCHED_BILLING", "INCORRECT", "INVALID"]):
        status_flag = "Approved ❎"
    else:
        status_flag = "Declined ❌"

    response_status = raw_response if raw_response else "No response received"

    # BIN Details
    bin_details = get_bin_details(cc[:6])
    bin_info = bin_details if bin_details else {"bin": cc[:6], "country": "Unknown", "flag": "🏳️", "vendor": "Unknown", "type": "Unknown", "level": "Unknown", "bank": "Unknown"}

    # Extract user_id from profile HTML
    try:
        user_id = profile.split("id=")[-1].split("'")[0]
        users = load_users()
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")
    except Exception:
        plan = "Unknown"
        badge = "❔"

    # Final formatted message
    formatted = f"""
<b>[$cmd → /sho] | Sync</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card</b>- <code>{fullcc}</code>
<b>[•] Gateway</b> - <b>{gateway}</b>
<b>[•] Status</b>- <code>{status_flag}</code>
<b>[•] Response</b>- <code>{response_status}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] Bin</b>: <code>{bin_info['bin']}</code>  
<b>[+] Info</b>: <code>{bin_info['vendor']} - {bin_info['type']} - {bin_info['level']}</code> 
<b>[+] Bank</b>: <code>{bin_info['bank']}</code> 🏦
<b>[+] Country</b>: <code>{bin_info['country']} - [{bin_info['flag']}]</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By</b>: {profile} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev</b> ➺ <a href="https://t.me/Chr1shtopher" target="_blank">Christopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] T/t</b>: <code>[{timet} 𝐬]</code> <b>|P/x:</b> [<code>Live ⚡️</code>]
"""
    return status_flag, formatted

