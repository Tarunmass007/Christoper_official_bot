"""
Stripe Auth (/au, /mau) gate selector.
Stores current gate per user: Gate-1 (primary) | Gate-2 (secondary)
No URLs are displayed to users - only gate numbers.
"""

import json
import os

DATA_DIR = "DATA"
AU_GATE_PATH = os.path.join(DATA_DIR, "au_gate.json")

# Gate key -> base URL (internal only, never shown to users)
AU_GATES = {
    "nomade": "https://shop.nomade-studio.be",
    "starr": "https://starr-shop.eu",
}

DEFAULT_GATE = "nomade"  # Gate-1 (primary)


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_store() -> dict:
    _ensure_data_dir()
    if not os.path.exists(AU_GATE_PATH):
        return {}
    try:
        with open(AU_GATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_store(data: dict) -> None:
    _ensure_data_dir()
    with open(AU_GATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_au_gate(user_id: str) -> str:
    """Current gate key for user. Default: nomade."""
    data = _load_store()
    gate = data.get(str(user_id), DEFAULT_GATE)
    if gate not in AU_GATES:
        return DEFAULT_GATE
    return gate


def set_au_gate(user_id: str, gate: str) -> bool:
    """Set gate for user. Returns True if valid."""
    if gate not in AU_GATES:
        return False
    data = _load_store()
    data[str(user_id)] = gate
    _save_store(data)
    return True


def get_au_gate_url(user_id: str) -> str:
    """Current gate URL for user."""
    return AU_GATES[get_au_gate(user_id)]


def toggle_au_gate(user_id: str) -> str:
    """Switch Gate-1 <-> Gate-2. Returns new gate key."""
    current = get_au_gate(user_id)
    new = "starr" if current == "nomade" else "nomade"
    set_au_gate(user_id, new)
    return new


def gate_display_name(gate_key: str) -> str:
    """Display name for UI - NO URLs shown, only gate numbers."""
    if gate_key == "nomade":
        return "Gate-1"
    if gate_key == "starr":
        return "Gate-2"
    return "Gate-1"  # Default
