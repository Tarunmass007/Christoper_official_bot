"""
Unified store: MongoDB or JSON fallback.
Users, proxies, sites, au_gate, plan_requests, redeems, groups, credits.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Union

import pytz
from datetime import datetime

# ---------------------------------------------------------------------------
# Config & paths
# ---------------------------------------------------------------------------

BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(BASE, "DATA")
CONFIG_PATH = os.path.join(BASE, "FILES", "config.json")

USERS_FILE = os.path.join(DATA_DIR, "users.json")
PROXY_FILE = os.path.join(DATA_DIR, "proxy.json")
USER_SITES_FILE = os.path.join(DATA_DIR, "user_sites.json")
AU_GATE_FILE = os.path.join(DATA_DIR, "au_gate.json")
PLAN_REQUESTS_FILE = os.path.join(DATA_DIR, "plan_requests.json")
REDEEMS_FILE = os.path.join(DATA_DIR, "redeems.json")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
STRIPE_AUTH_SITES_FILE = os.path.join(DATA_DIR, "stripe_auth_sites.json")


def _ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_config() -> dict:
    try:
        from BOT.config_loader import get_config
        return get_config()
    except Exception:
        return {}


def load_owner_id():
    return _load_config().get("OWNER")


def is_owner(user_id) -> bool:
    """
    Check if user_id is the configured owner (full admin access).
    Only returns True when OWNER is explicitly set in config and matches.
    """
    own = load_owner_id()
    if own is None or str(own).strip() == "":
        return False
    return str(user_id).strip() == str(own).strip()


def get_checked_by_plan_display(user_id: str, user_data: dict) -> str:
    """
    Get plan display for check results. Owner shows "Owner 🎭", others show "Plan Badge".
    """
    if is_owner(user_id):
        return "Owner 🎭"
    plan_info = user_data.get("plan", {})
    plan = plan_info.get("plan", "Free")
    badge = plan_info.get("badge", "🎟️")
    return f"{plan} {badge}"


def get_effective_mlimit(user_id: str, plan_info: dict) -> Optional[int]:
    """
    Get effective mass limit. Owner = unlimited (None), others use plan mlimit.
    Returns None for unlimited, int for limit.
    """
    if is_owner(user_id):
        return None  # Unlimited
    mlimit = plan_info.get("mlimit")
    if mlimit is None or str(mlimit).lower() in ["null", "none"]:
        return 10_000  # Fallback for VIP etc
    try:
        return int(mlimit)
    except (TypeError, ValueError):
        return 10_000


def get_ist_time() -> str:
    return datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# MongoDB helpers (used only when use_mongo)
# ---------------------------------------------------------------------------

def _mongo():
    from BOT.db.mongo import use_mongo, get_db
    if not use_mongo():
        return None
    return get_db()


def _use_mongo() -> bool:
    from BOT.db.mongo import use_mongo
    return use_mongo()


def _users_coll():
    m = _mongo()
    return m.users if m is not None else None


def _proxies_coll():
    m = _mongo()
    return m.proxies if m is not None else None


def _sites_coll():
    m = _mongo()
    return m.user_sites if m is not None else None


def _au_gates_coll():
    m = _mongo()
    return m.au_gates if m is not None else None


def _plan_requests_coll():
    m = _mongo()
    return m.plan_requests if m is not None else None


def _redeems_coll():
    m = _mongo()
    return m.redeems if m is not None else None


def _groups_coll():
    m = _mongo()
    return m.groups if m is not None else None


def _stripe_auth_sites_coll():
    m = _mongo()
    return m.stripe_auth_sites if m is not None else None


# ---------------------------------------------------------------------------
# Default plan (mirrors start.default_plan)
# ---------------------------------------------------------------------------

def default_plan(user_id: str) -> dict:
    own = load_owner_id()
    if str(user_id) == str(own):
        return {
            "plan": "Owner",
            "activated_at": get_ist_time(),
            "expires_at": None,
            "antispam": None,
            "mlimit": None,
            "credits": "∞",
            "badge": "🎭",
            "private": "on",
            "keyredeem": 0,
        }
    return {
        "plan": "Free",
        "activated_at": get_ist_time(),
        "expires_at": None,
        "antispam": 15,
        "mlimit": 5,
        "credits": 100,
        "badge": "🧿",
        "private": "off",
        "keyredeem": 0,
    }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def load_users() -> dict:
    if _use_mongo():
        c = _users_coll()
        out = {}
        for doc in c.find({}):
            uid = str(doc["_id"])
            d = {k: v for k, v in doc.items() if k != "_id"}
            out[uid] = d
        return out
    _ensure_data()
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users: dict) -> None:
    if _use_mongo():
        c = _users_coll()
        for uid, doc in users.items():
            uid = str(uid)
            payload = {"_id": uid, **{k: v for k, v in doc.items()}}
            c.replace_one({"_id": uid}, payload, upsert=True)
        return
    _ensure_data()
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)


def get_user(user_id: str) -> Optional[dict]:
    users = load_users()
    return users.get(str(user_id))


def update_user(user_id: str, data: dict) -> None:
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        return
    users[uid].update(data)
    save_users(users)


# ---------------------------------------------------------------------------
# Credits (atomic when Mongo)
# ---------------------------------------------------------------------------

def has_credits(user_id: str) -> bool:
    if is_owner(str(user_id)):
        return True
    u = get_user(str(user_id))
    if not u:
        return False
    c = u.get("plan", {}).get("credits", 0)
    if c == "∞":
        return True
    try:
        return int(c) > 0
    except Exception:
        return False


def deduct_credit(user_id: str) -> tuple[bool, str]:
    if is_owner(str(user_id)):
        return True, "Owner has infinite credits, no deduction necessary."
    if _use_mongo():
        c = _users_coll()
        try:
            doc = c.find_one({"_id": str(user_id)})
            if not doc:
                return False, "User not found."
            credits = doc.get("plan", {}).get("credits", 0)
            if credits == "∞":
                return True, "Owner has infinite credits, no deduction necessary."
            try:
                n = int(credits)
            except Exception:
                return False, "Invalid credit format."
            if n <= 0:
                return False, "Insufficient credits."
            c.update_one({"_id": str(user_id)}, {"$set": {"plan.credits": str(n - 1)}})
            return True, "Credit deducted successfully."
        except Exception as e:
            print(f"[deduct_credit error] {e}")
            return False, "An error occurred while deducting credits."
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        u = users.get(str(user_id))
        if not u:
            return False, "User not found."
        credits = u.get("plan", {}).get("credits", 0)
        if credits == "∞":
            return True, "Owner has infinite credits, no deduction necessary."
        n = int(credits)
        if n <= 0:
            return False, "Insufficient credits."
        u["plan"]["credits"] = str(n - 1)
        users[str(user_id)] = u
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=4)
        return True, "Credit deducted successfully."
    except Exception as e:
        print(f"[deduct_credit error] {e}")
        return False, "An error occurred while deducting credits."


def deduct_credit_bulk(user_id: str, amount: int) -> tuple[bool, str]:
    if is_owner(str(user_id)):
        return True, "Owner has infinite credits, no deduction needed."
    if _use_mongo():
        c = _users_coll()
        try:
            doc = c.find_one({"_id": str(user_id)})
            if not doc:
                return False, "User not found."
            credits = doc.get("plan", {}).get("credits", 0)
            if isinstance(credits, str) and credits.strip() == "∞":
                return True, "Infinite credits, no deduction needed."
            try:
                n = int(credits)
            except Exception:
                return False, "Invalid credit format."
            if n < amount:
                return False, "Insufficient credits."
            c.update_one(
                {"_id": str(user_id)},
                {"$set": {"plan.credits": str(n - amount)}}
            )
            return True, f"Deducted {amount} credits successfully."
        except Exception as e:
            print(f"[deduct_credit_bulk error] {e}")
            return False, "Error during bulk deduction."
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        u = users.get(str(user_id))
        if not u:
            return False, "User not found."
        credits = u.get("plan", {}).get("credits", 0)
        if isinstance(credits, str) and credits.strip() == "∞":
            return True, "Infinite credits, no deduction needed."
        n = int(credits)
        if n < amount:
            return False, "Insufficient credits."
        u["plan"]["credits"] = str(n - amount)
        users[str(user_id)] = u
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=4)
        return True, f"Deducted {amount} credits successfully."
    except Exception as e:
        print(f"[deduct_credit_bulk error] {e}")
        return False, "Error during bulk deduction."


def resolve_user_id(identifier: str) -> Optional[str]:
    """
    Resolve username or user_id to user_id. Returns user_id if found, else None.
    identifier: numeric string (user_id), or @username, or username (no @).
    """
    if not identifier:
        return None
    identifier = str(identifier).strip().lstrip("@")
    users = load_users()
    if not users:
        return None
    if identifier.isdigit():
        return identifier if identifier in users else None
    want = identifier.lower()
    for uid, doc in users.items():
        uname = doc.get("username")
        if uname is None:
            continue
        if str(uname).strip().lower() == want:
            return uid
    return None


def add_credits(user_id: str, amount: int) -> tuple[bool, str]:
    """
    Add credits to a user's plan. Same storage as plans (MongoDB or JSON).
    Returns (success, message). Does not reduce below 0; owner's ∞ stays ∞.
    """
    if amount <= 0:
        return False, "Amount must be a positive number."
    uid = str(user_id)
    if _use_mongo():
        c = _users_coll()
        try:
            doc = c.find_one({"_id": uid})
            if not doc:
                return False, "User not found."
            credits = doc.get("plan", {}).get("credits", 0)
            if isinstance(credits, str) and credits.strip() == "∞":
                return True, "Owner has infinite credits; no change applied."
            try:
                n = int(credits)
            except Exception:
                n = 0
            new_val = n + amount
            c.update_one({"_id": uid}, {"$set": {"plan.credits": str(new_val)}})
            return True, f"Added {amount} credits. New balance: {new_val}."
        except Exception as e:
            print(f"[add_credits error] {e}")
            return False, "Failed to add credits."
    try:
        users = load_users()
        u = users.get(uid)
        if not u:
            return False, "User not found."
        credits = u.get("plan", {}).get("credits", 0)
        if isinstance(credits, str) and credits.strip() == "∞":
            return True, "Owner has infinite credits; no change applied."
        try:
            n = int(credits)
        except Exception:
            n = 0
        new_val = n + amount
        u["plan"]["credits"] = str(new_val)
        users[uid] = u
        save_users(users)
        return True, f"Added {amount} credits. New balance: {new_val}."
    except Exception as e:
        print(f"[add_credits error] {e}")
        return False, "Failed to add credits."


# ---------------------------------------------------------------------------
# Proxies
# ---------------------------------------------------------------------------

def load_proxies() -> dict:
    """Returns {uid: [proxy1, proxy2, ...]}."""
    if _use_mongo():
        coll = _proxies_coll()
        out = {}
        for d in coll.find({}):
            try:
                uid = str(d["_id"])
                # Try new format first (proxies list)
                raw = d.get("proxies")
                if raw is not None and isinstance(raw, list):
                    out[uid] = [str(p) for p in raw if p]
                # Fallback to old format (single proxy)
                elif d.get("proxy") is not None:
                    out[uid] = [str(d["proxy"])]
                else:
                    out[uid] = []
            except (KeyError, TypeError, AttributeError) as e:
                # Skip malformed documents
                continue
        return out
    _ensure_data()
    if not os.path.exists(PROXY_FILE):
        return {}
    try:
        with open(PROXY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in list(data.items()):
            if isinstance(v, str):
                data[k] = [v]
            elif not isinstance(v, list):
                data[k] = []
        return data
    except Exception:
        return {}


def save_proxies(data: dict) -> None:
    if _use_mongo():
        coll = _proxies_coll()
        for uid, proxy_list in data.items():
            if not isinstance(proxy_list, list):
                proxy_list = [proxy_list] if proxy_list else []
            coll.replace_one(
                {"_id": str(uid)},
                {"_id": str(uid), "proxies": proxy_list},
                upsert=True,
            )
        return
    _ensure_data()
    with open(PROXY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_proxy(user_id: int | str) -> list:
    """Return list of proxies for user. Empty list if none."""
    data = load_proxies()
    proxies = data.get(str(user_id), [])
    if isinstance(proxies, str):
        return [proxies]
    return list(proxies) if proxies else []


def set_proxy(user_id: str, proxy: str) -> None:
    """Overwrite user's proxy list with a single proxy."""
    data = load_proxies()
    data[str(user_id)] = [proxy]
    save_proxies(data)


def add_proxies(user_id: str, new_proxies: list) -> int:
    """Add multiple proxies (unique only). Returns count added."""
    data = load_proxies()
    uid = str(user_id)
    current = data.get(uid, [])
    if isinstance(current, str):
        current = [current]
    existing = set(current)
    added = 0
    for p in new_proxies:
        if p and p not in existing:
            current.append(p)
            existing.add(p)
            added += 1
    data[uid] = current
    save_proxies(data)
    return added


def delete_proxy(user_id: str) -> None:
    data = load_proxies()
    uid = str(user_id)
    if uid in data:
        del data[uid]
        save_proxies(data)


# ---------------------------------------------------------------------------
# User sites (unified)
# ---------------------------------------------------------------------------
# IMPORTANT: No default sites for admin/owner.
# All users (including admin/owner) must add sites manually.
# No automatic initialization of default sites for any user.

def load_unified_sites() -> dict:
    if _use_mongo():
        coll = _sites_coll()
        return {str(d["_id"]): d.get("sites", []) for d in coll.find({})}
    _ensure_data()
    if not os.path.exists(USER_SITES_FILE):
        return {}
    try:
        with open(USER_SITES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_unified_sites(data: dict) -> None:
    if _use_mongo():
        coll = _sites_coll()
        for uid, sites in data.items():
            coll.replace_one({"_id": str(uid)}, {"_id": str(uid), "sites": sites or []}, upsert=True)
        return
    _ensure_data()
    with open(USER_SITES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_user_sites(user_id: str) -> list:
    """
    Get sites for any user (regular user or admin/owner).
    No default sites are returned - only sites manually added by the user.
    """
    data = load_unified_sites()
    return data.get(str(user_id), [])


def get_user_active_sites(user_id: str) -> list:
    sites = get_user_sites(user_id)
    return [s for s in sites if s.get("active", True)]


def get_primary_site(user_id: str) -> Optional[dict]:
    sites = get_user_sites(user_id)
    if not sites:
        return None
    for s in sites:
        if s.get("is_primary"):
            return s
    return sites[0]


def add_site_for_user(user_id: str, url: str, gateway: str, price: str = "N/A", set_primary: bool = False) -> bool:
    """
    Add a site for any user (regular user or admin/owner).
    No special handling for admin/owner - everyone is treated the same.
    All users must add sites manually using /addurl or /txturl commands.
    No default sites are automatically added for any user.
    
    This function works identically for all users, including owners.
    Owners must add sites manually just like regular users.
    """
    try:
        data = load_unified_sites()
        uid = str(user_id)
        if uid not in data:
            data[uid] = []
        existing = {s.get("url", "").lower().rstrip("/") for s in data[uid]}
        u = url.lower().rstrip("/")
        if u in existing:
            if set_primary:
                for s in data[uid]:
                    s["is_primary"] = (s.get("url", "").lower().rstrip("/") == u)
                save_unified_sites(data)
            return True
        is_first = len(data[uid]) == 0
        entry = {"url": url, "gateway": gateway, "price": price, "active": True, "fail_count": 0, "is_primary": set_primary or is_first}
        if set_primary:
            for s in data[uid]:
                s["is_primary"] = False
            data[uid].insert(0, entry)
        else:
            data[uid].append(entry)
        save_unified_sites(data)
        return True
    except Exception:
        return False


def add_sites_batch(user_id: str, sites: list) -> int:
    """
    Add multiple sites for a user (regular user or admin/owner).
    Works identically for all users - no special handling.
    No default sites are automatically added for any user.
    """
    try:
        data = load_unified_sites()
        uid = str(user_id)
        if uid not in data:
            data[uid] = []
        existing = {s.get("url", "").lower().rstrip("/") for s in data[uid]}
        added = 0
        for info in sites:
            url = (info.get("url") or "").rstrip("/")
            if not url or url.lower() in existing:
                continue
            is_first = len(data[uid]) == 0
            entry = {"url": url, "gateway": info.get("gateway", "Unknown"), "price": info.get("price", "N/A"), "active": True, "fail_count": 0, "is_primary": is_first}
            data[uid].append(entry)
            existing.add(url.lower())
            added += 1
        if added:
            save_unified_sites(data)
        return added
    except Exception:
        return 0


def remove_site_for_user(user_id: str, url: str) -> bool:
    """
    Remove a specific site for a user (regular user or admin/owner).
    Works identically for all users - no special handling.
    Owners use the same function as regular users.
    """
    try:
        data = load_unified_sites()
        uid = str(user_id)
        if uid not in data:
            return False
        u = url.lower().rstrip("/")
        prev = len(data[uid])
        data[uid] = [s for s in data[uid] if (s.get("url") or "").lower().rstrip("/") != u]
        if len(data[uid]) < prev:
            if data[uid] and not any(s.get("is_primary") for s in data[uid]):
                data[uid][0]["is_primary"] = True
            save_unified_sites(data)
            return True
        return False
    except Exception:
        return False


def clear_user_sites(user_id: str) -> int:
    """
    Clear all sites for a user (regular user or admin/owner).
    Works identically for all users - no special handling.
    Owners use the same function as regular users.
    Returns the number of sites cleared.
    Properly flushes from MongoDB or JSON storage.
    """
    try:
        uid = str(user_id)
        
        if _use_mongo():
            # Direct MongoDB deletion - more efficient and reliable
            coll = _sites_coll()
            doc = coll.find_one({"_id": uid})
            if not doc:
                return 0
            n = len(doc.get("sites", []))
            # Delete the entire document to flush all sites
            coll.delete_one({"_id": uid})
            return n
        else:
            # JSON file approach
            data = load_unified_sites()
            if uid not in data:
                return 0
            n = len(data[uid])
            del data[uid]
            save_unified_sites(data)
            return n
    except Exception as e:
        print(f"[clear_user_sites error] {e}")
        return 0


def mark_site_failed(user_id: str, url: str) -> None:
    try:
        data = load_unified_sites()
        uid = str(user_id)
        if uid not in data:
            return
        u = url.lower().rstrip("/")
        for s in data[uid]:
            if (s.get("url") or "").lower().rstrip("/") == u:
                s["fail_count"] = s.get("fail_count", 0) + 1
                if s["fail_count"] >= 5:
                    s["active"] = False
                break
        save_unified_sites(data)
    except Exception:
        pass


def update_site_fail_count(user_id: str, url: str) -> None:
    mark_site_failed(user_id, url)


def reset_site_fail_count(user_id: str, url: str) -> None:
    try:
        data = load_unified_sites()
        uid = str(user_id)
        if uid not in data:
            return
        u = url.lower().rstrip("/")
        for s in data[uid]:
            if (s.get("url") or "").lower().rstrip("/") == u:
                s["fail_count"] = 0
                s["active"] = True
                break
        save_unified_sites(data)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Stripe Auto Auth sites (for /sturl, /murl, /starr, /mstarr)
# ---------------------------------------------------------------------------

def load_stripe_auth_sites() -> dict:
    """Load stripe_auth_sites: { user_id: [ { url, gateway, is_primary }, ... ] }."""
    if _use_mongo():
        coll = _stripe_auth_sites_coll()
        if coll is None:
            return {}
        data = {}
        for doc in coll.find({}):
            uid = doc.get("_id")
            if uid:
                data[str(uid)] = doc.get("sites", [])
        return data
    _ensure_data()
    if not os.path.exists(STRIPE_AUTH_SITES_FILE):
        return {}
    try:
        with open(STRIPE_AUTH_SITES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_stripe_auth_sites(data: dict) -> None:
    if _use_mongo():
        coll = _stripe_auth_sites_coll()
        if coll is None:
            return
        for uid, sites in data.items():
            coll.replace_one({"_id": str(uid)}, {"_id": str(uid), "sites": sites or []}, upsert=True)
        return
    _ensure_data()
    with open(STRIPE_AUTH_SITES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_stripe_auth_sites(user_id: str) -> list:
    """Return list of site dicts with 'url' for /starr and /mstarr. Normalized for consistent use."""
    data = load_stripe_auth_sites()
    raw = data.get(str(user_id), [])
    if not raw:
        return []
    out = []
    for s in raw:
        if isinstance(s, dict) and s.get("url"):
            out.append({
                "url": str(s["url"]).strip().rstrip("/"),
                "gateway": s.get("gateway", "Stripe Auth"),
                "active": s.get("active", True),
                "is_primary": bool(s.get("is_primary")),
            })
        elif isinstance(s, dict):
            continue
        else:
            url = str(s).strip().rstrip("/")
            if url:
                out.append({"url": url, "gateway": "Stripe Auth", "active": True, "is_primary": False})
    return out


def get_primary_stripe_auth_site(user_id: str) -> Optional[dict]:
    sites = get_stripe_auth_sites(user_id)
    if not sites:
        return None
    for s in sites:
        if s.get("is_primary"):
            return s
    return sites[0]


def add_stripe_auth_site(user_id: str, url: str, set_primary: bool = False) -> bool:
    """Add site. Rotation-only: set_primary=False so no site is primary."""
    try:
        data = load_stripe_auth_sites()
        uid = str(user_id)
        if uid not in data:
            data[uid] = []
        u = url.lower().rstrip("/")
        existing = {s.get("url", "").lower().rstrip("/") for s in data[uid] if isinstance(s, dict)}
        if u in existing:
            save_stripe_auth_sites(data)
            return True
        entry = {"url": url.rstrip("/"), "gateway": "Stripe Auth", "active": True, "is_primary": False}
        data[uid].append(entry)
        save_stripe_auth_sites(data)
        return True
    except Exception:
        return False


def remove_stripe_auth_site(user_id: str, site_url_or_index: str) -> Optional[str]:
    """
    Remove one Stripe Auth site by URL (substring match) or 1-based index.
    Returns removed URL if found, None otherwise.
    """
    try:
        data = load_stripe_auth_sites()
        uid = str(user_id)
        if uid not in data or not data[uid]:
            return None
        raw = data[uid]
        # Try as 1-based index first
        try:
            idx = int(site_url_or_index.strip())
            if 1 <= idx <= len(raw):
                removed = raw[idx - 1]
                url_removed = removed.get("url", str(removed)) if isinstance(removed, dict) else str(removed)
                raw.pop(idx - 1)
                save_stripe_auth_sites(data)
                return url_removed
        except (ValueError, TypeError):
            pass
        # Match by URL (exact or substring)
        key_lower = site_url_or_index.strip().lower().rstrip("/")
        for i, s in enumerate(raw):
            u = (s.get("url", "") if isinstance(s, dict) else str(s)).lower().rstrip("/")
            if key_lower == u or key_lower in u or u in key_lower:
                url_removed = s.get("url", str(s)) if isinstance(s, dict) else str(s)
                raw.pop(i)
                save_stripe_auth_sites(data)
                return url_removed
        return None
    except Exception:
        return None


def clear_stripe_auth_sites(user_id: str) -> int:
    try:
        data = load_stripe_auth_sites()
        uid = str(user_id)
        if uid not in data:
            return 0
        n = len(data[uid])
        del data[uid]
        save_stripe_auth_sites(data)
        return n
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# AU gate (Stripe Auth)
# ---------------------------------------------------------------------------

AU_GATES = {"nomade": "https://shop.nomade-studio.be", "starr": "https://starr-shop.eu"}
DEFAULT_AU_GATE = "nomade"  # Gate-1 (primary)


def get_au_gate(user_id: str) -> str:
    if _use_mongo():
        coll = _au_gates_coll()
        d = coll.find_one({"_id": str(user_id)})
        g = (d or {}).get("gate", DEFAULT_AU_GATE)
        return g if g in AU_GATES else DEFAULT_AU_GATE
    _ensure_data()
    if not os.path.exists(AU_GATE_FILE):
        return DEFAULT_AU_GATE
    try:
        with open(AU_GATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        g = data.get(str(user_id), DEFAULT_AU_GATE)
        return g if g in AU_GATES else DEFAULT_AU_GATE
    except Exception:
        return DEFAULT_AU_GATE


def set_au_gate(user_id: str, gate: str) -> bool:
    if gate not in AU_GATES:
        return False
    if _use_mongo():
        coll = _au_gates_coll()
        coll.replace_one({"_id": str(user_id)}, {"_id": str(user_id), "gate": gate}, upsert=True)
        return True
    _ensure_data()
    data = {}
    if os.path.exists(AU_GATE_FILE):
        try:
            with open(AU_GATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data[str(user_id)] = gate
    with open(AU_GATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return True


def get_au_gate_url(user_id: str) -> str:
    return AU_GATES[get_au_gate(user_id)]


def toggle_au_gate(user_id: str) -> str:
    cur = get_au_gate(user_id)
    new = "starr" if cur == "nomade" else "nomade"
    set_au_gate(user_id, new)
    return new


def gate_display_name(gate_key: str) -> str:
    """Display name for UI - NO URLs shown, only gate numbers."""
    if gate_key == "nomade":
        return "Gate-1"
    if gate_key == "starr":
        return "Gate-2"
    return "Gate-1"  # Default


# ---------------------------------------------------------------------------
# Plan requests
# ---------------------------------------------------------------------------

def load_plan_requests() -> dict:
    if _use_mongo():
        coll = _plan_requests_coll()
        return {str(d["_id"]): {k: v for k, v in d.items() if k != "_id"} for d in coll.find({})}
    _ensure_data()
    if not os.path.exists(PLAN_REQUESTS_FILE):
        return {}
    try:
        with open(PLAN_REQUESTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_plan_requests(requests: dict) -> None:
    if _use_mongo():
        coll = _plan_requests_coll()
        for uid, doc in requests.items():
            payload = {"_id": str(uid), **doc}
            coll.replace_one({"_id": str(uid)}, payload, upsert=True)
        return
    _ensure_data()
    with open(PLAN_REQUESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(requests, f, indent=4)


# ---------------------------------------------------------------------------
# Redeems
# ---------------------------------------------------------------------------

def load_redeems() -> dict:
    if _use_mongo():
        coll = _redeems_coll()
        return {d["_id"]: {"used": d.get("used", False), "used_by": d.get("used_by"), "used_at": d.get("used_at")} for d in coll.find({})}
    _ensure_data()
    if not os.path.exists(REDEEMS_FILE):
        return {}
    try:
        with open(REDEEMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_redeems(data: dict) -> None:
    if _use_mongo():
        coll = _redeems_coll()
        coll.delete_many({})
        for code, doc in data.items():
            coll.insert_one({"_id": code, "used": doc.get("used", False), "used_by": doc.get("used_by"), "used_at": doc.get("used_at")})
        return
    _ensure_data()
    with open(REDEEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def load_allowed_groups() -> list:
    if _use_mongo():
        coll = _groups_coll()
        d = coll.find_one({"_id": "allowed"})
        return (d or {}).get("groups", [])
    _ensure_data()
    if not os.path.exists(GROUPS_FILE):
        return []
    try:
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            x = json.load(f)
        return x if isinstance(x, list) else []
    except Exception:
        return []


def save_allowed_groups(groups: list) -> None:
    if _use_mongo():
        coll = _groups_coll()
        coll.replace_one({"_id": "allowed"}, {"_id": "allowed", "groups": list(groups)}, upsert=True)
        return
    _ensure_data()
    with open(GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(groups, f)
