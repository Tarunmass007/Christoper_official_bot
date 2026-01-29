"""
Safe Message Editing with FloodWait Handling
============================================
Professional helper for editing Telegram messages with automatic FloodWait retry.
"""

import asyncio
from typing import Optional
from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError


async def safe_edit_message(
    client: Client,
    message: Message,
    text: str,
    reply_markup=None,
    parse_mode=None,
    disable_web_page_preview: bool = False,
    max_retries: int = 3,
    **kwargs
) -> bool:
    """
    Safely edit a message with automatic FloodWait handling.
    
    Args:
        client: Pyrogram client
        message: Message to edit
        text: New text content
        reply_markup: Optional inline keyboard
        parse_mode: Optional parse mode
        disable_web_page_preview: Disable web page preview
        max_retries: Maximum retry attempts
        **kwargs: Additional arguments for edit_text
        
    Returns:
        bool: True if successful, False otherwise
    """
    for attempt in range(max_retries):
        try:
            await message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                **kwargs
            )
            return True
        except FloodWait as e:
            wait_time = e.value
            if attempt < max_retries - 1:
                # Wait for the required time plus a small buffer
                await asyncio.sleep(wait_time + 1)
                continue
            else:
                # Last attempt failed, return False
                return False
        except (RPCError, Exception) as e:
            # For other errors, log and return False
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                continue
            return False
    
    return False


async def safe_edit_with_throttle(
    client: Client,
    message: Message,
    text: str,
    last_edit_time: float,
    throttle_seconds: float = 0.5,
    reply_markup=None,
    parse_mode=None,
    disable_web_page_preview: bool = False,
    force: bool = False,
    **kwargs
) -> tuple[bool, float]:
    """
    Edit message with throttling and FloodWait handling.
    
    Args:
        client: Pyrogram client
        message: Message to edit
        text: New text content
        last_edit_time: Last edit timestamp (for throttling)
        throttle_seconds: Minimum seconds between edits
        reply_markup: Optional inline keyboard
        parse_mode: Optional parse mode
        disable_web_page_preview: Disable web page preview
        force: Force edit even if throttled
        **kwargs: Additional arguments for edit_text
        
    Returns:
        tuple: (success: bool, new_last_edit_time: float)
    """
    import time
    
    current_time = time.time()
    
    # Check throttle unless forced
    if not force and (current_time - last_edit_time) < throttle_seconds:
        return False, last_edit_time
    
    success = await safe_edit_message(
        client=client,
        message=message,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
        **kwargs
    )
    
    if success:
        return True, current_time
    return False, last_edit_time
