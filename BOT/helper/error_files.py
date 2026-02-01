"""
Mass check error CCs storage and retrieval.
One file per user per gate; cleared when user starts a new check for that gate.
Gate types: mau (Stripe Auth), mstarr (Auto Stripe Auth), shopify (/msh and /tsh share one).
"""

import os
import json
import random
import string
from pathlib import Path
from typing import List, Optional

# DATA/errors/<gate>/<user_id>.txt and <user_id>_meta.json (repo root = BOT's parent)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ERRORS_BASE = _REPO_ROOT / "DATA" / "errors"
VALID_GATES = ("mau", "mstarr", "shopify")


def _gate_dir(gate: str) -> Path:
    if gate not in VALID_GATES:
        raise ValueError(f"Invalid gate: {gate}. Use one of: {VALID_GATES}")
    d = ERRORS_BASE / gate
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_check_id() -> str:
    """Return a unique check id like #a1b2c3d4 (8 alphanumeric)."""
    chars = string.ascii_lowercase + string.digits
    return "#" + "".join(random.choices(chars, k=8))


def clear_error_file(user_id: str, gate: str) -> bool:
    """
    Clear saved error CCs for this user+gate (call when starting a new mass check).
    Returns True if a previous file was cleared, False otherwise.
    """
    cleared = False
    try:
        d = _gate_dir(gate)
        txt_path = d / f"{user_id}.txt"
        meta_path = d / f"{user_id}_meta.json"
        if txt_path.exists():
            txt_path.unlink()
            cleared = True
        if meta_path.exists():
            meta_path.unlink()
    except Exception:
        pass
    return cleared


def save_error_ccs(
    user_id: str, gate: str, cc_lines: List[str], check_id: Optional[str] = None
) -> Optional[str]:
    """
    Save error/captcha CCs (one per line) for this user+gate.
    If check_id is provided (from start of check), use it; else generate one.
    Returns the check_id for display in processing/completion messages.
    """
    if not cc_lines:
        return None
    try:
        d = _gate_dir(gate)
        cid = check_id if check_id else generate_check_id()
        txt_path = d / f"{user_id}.txt"
        meta_path = d / f"{user_id}_meta.json"
        with open(txt_path, "w", encoding="utf-8") as f:
            for line in cc_lines:
                s = (line or "").strip()
                if s:
                    f.write(s + "\n")
        meta = {"check_id": cid, "gate": gate, "user_id": user_id, "count": len(cc_lines)}
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        return cid
    except Exception:
        return None


def get_error_file_path(user_id: str, gate: str) -> Optional[Path]:
    """Return path to this user's error file for gate if it exists. Does not create dirs."""
    if gate not in VALID_GATES:
        return None
    try:
        txt_path = ERRORS_BASE / gate / f"{user_id}.txt"
        if txt_path.exists() and txt_path.is_file():
            return txt_path
    except Exception:
        pass
    return None


def get_check_id(user_id: str, gate: str) -> Optional[str]:
    """Return saved check_id for this user+gate (for display). Does not create dirs."""
    if gate not in VALID_GATES:
        return None
    try:
        meta_path = ERRORS_BASE / gate / f"{user_id}_meta.json"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("user_id") == user_id:
                return meta.get("check_id")
    except Exception:
        pass
    return None


def resolve_gate_for_command(cmd_arg: str) -> Optional[str]:
    """Map /geterrors <arg> to gate: mau, mstarr, msh -> mau/mstarr/shopify; tsh -> shopify."""
    a = (cmd_arg or "").strip().lower()
    if a in ("mau",):
        return "mau"
    if a in ("mstarr", "mstripeauto", "starr"):
        return "mstarr"
    if a in ("msh", "shopify", "tsh"):
        return "shopify"
    return None


# --- /geterrors command (send error CCs file for last mass check) ---
from pyrogram import Client, filters
from pyrogram.enums import ParseMode


@Client.on_message(filters.command("geterrors", prefixes="/") & filters.private)
async def geterrors_handler(client: Client, message):
    """Send the error CCs file for the user's last mass check (mau, mstarr, msh, tsh)."""
    if not message.from_user:
        return
    user_id = str(message.from_user.id)
    parts = (message.text or "").strip().split(maxsplit=1)
    arg = (parts[1] if len(parts) > 1 else "").strip().lower()
    gate = resolve_gate_for_command(arg)
    if not gate:
        await message.reply(
            "<pre>Get Error CCs</pre>\n━━━━━━━━━━━━━━━\n"
            "<b>Usage:</b> <code>/geterrors mau</code> | <code>/geterrors mstarr</code> | <code>/geterrors msh</code> | <code>/geterrors tsh</code>\n\n"
            "Sends the error + captcha CCs file from your <b>last</b> mass check for that gate.\n"
            "Run a mass check first; if it had errors, use this to get the CC list.",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
        return
    path = get_error_file_path(user_id, gate)
    if not path or not path.exists():
        gate_cmd = {"mau": "/mau", "mstarr": "/mstarr", "shopify": "/msh or /tsh"}.get(gate, "/mau")
        await message.reply(
            "<pre>No Error File</pre>\n━━━━━━━━━━━━━━━\n"
            "You have no saved error CCs for this gate.\n\n"
            "<b>When it clears:</b> The error file is <b>cleared</b> when you <b>start a new</b> mass check for this gate "
            f"(e.g. {gate_cmd}). So if you already started a new check, the previous file was removed.\n\n"
            "<b>When it stays:</b> After a check completes, the file <b>stays</b> until you run a new check for this gate.\n\n"
            f"Run a mass check first; then use <code>/geterrors &lt;gate&gt;</code> after it completes.",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        gate_cmd = {"mau": "/mau", "mstarr": "/mstarr", "shopify": "/msh or /tsh"}.get(gate, "/mau")
        caption = (
            f"Error CCs from your last <code>{gate}</code> check (one CC per line).\n\n"
            f"<b>When it stays:</b> This file stays until you start a new check for this gate.\n"
            f"<b>When it clears:</b> When you run a new mass check ({gate_cmd}), this file is cleared and replaced by the new check's errors (if any)."
        )
        await message.reply_document(
            document=str(path),
            caption=caption,
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply(
            f"<pre>Could not send file</pre>\n<code>{str(e)[:80]}</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
        )
