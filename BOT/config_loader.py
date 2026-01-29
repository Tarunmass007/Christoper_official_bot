"""
Central config loader. All credentials from FILES/config.json.
DB connection (MongoDB) is separate: set MONGODB_URI or MONGO_URL in env only.
"""

import json
import os

_BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(_BASE, "FILES", "config.json")

_cached = None


def get_config() -> dict:
    """Load config from FILES/config.json only. Cached."""
    global _cached
    if _cached is not None:
        return _cached
    data = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    _cached = data
    return data
