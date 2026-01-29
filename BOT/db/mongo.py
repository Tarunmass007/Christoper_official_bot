"""
MongoDB client and database setup.
Uses pymongo (sync). Connection via env only: MONGODB_URI or MONGO_URL.
"""

import json
import os

try:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
    PYMONGO_AVAILABLE = True
except ImportError:
    PYMONGO_AVAILABLE = False
    MongoClient = None
    PyMongoError = Exception

_BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(_BASE, "DATA")
DB_NAME = "christopher_bot"

_client = None
_db = None
_use_mongo = None


def get_mongo_uri() -> str:
    """MongoDB URI from env only. Add MONGODB_URI or MONGO_URL manually (e.g. Railway Variables)."""
    uri = (
        os.environ.get("MONGODB_URI", "").strip()
        or os.environ.get("MONGO_URL", "").strip()
    )
    return uri or ""


def use_mongo() -> bool:
    """True if MongoDB is configured and available."""
    global _use_mongo
    if _use_mongo is not None:
        return _use_mongo
    if not PYMONGO_AVAILABLE:
        _use_mongo = False
        return False
    uri = get_mongo_uri()
    _use_mongo = bool(uri)
    return _use_mongo


def get_client():
    """Get or create MongoClient. Raises if MongoDB not configured."""
    global _client
    if _client is not None:
        return _client
    if not PYMONGO_AVAILABLE:
        raise RuntimeError("pymongo not installed. Add 'pymongo' to requirements.txt and install.")
    uri = get_mongo_uri()
    if not uri:
        raise RuntimeError(
            "MongoDB not configured. Set MONGODB_URI or MONGO_URL in env (e.g. Railway Variables)."
        )
    _client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    return _client


def get_db():
    """Get database instance."""
    global _db
    if _db is not None:
        return _db
    _db = get_client()[DB_NAME]
    return _db


def _coll(name):
    return get_db()[name]


def init_db() -> bool:
    """Connect and verify MongoDB. Create indexes. Return True if using MongoDB."""
    if not use_mongo():
        return False
    try:
        get_client().admin.command("ping")
    except Exception as e:
        print(f"[MongoDB] Ping failed: {e}")
        raise
    ensure_indexes()
    return True


def close_db():
    """Close MongoDB connection."""
    global _client, _db
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None
    _db = None


def ensure_indexes():
    """Create indexes; _id is unique by default. Extra indexes only if needed."""
    get_db().users.create_index("_id")
    get_db().proxies.create_index("_id")
    get_db().user_sites.create_index("_id")
    get_db().au_gates.create_index("_id")
    get_db().redeems.create_index("_id")
    get_db().plan_requests.create_index("_id")
    get_db().groups.create_index("_id")


def migrate_json_to_mongo():
    """
    One-time migration: if MongoDB collections are empty, load from DATA/*.json
    and insert. Safe to call on every startup.
    """
    if not use_mongo():
        return
    db = get_db()

    # Users
    users_path = os.path.join(DATA_DIR, "users.json")
    if os.path.exists(users_path) and db.users.count_documents({}) == 0:
        try:
            with open(users_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                for uid, doc in data.items():
                    doc["_id"] = str(uid)
                    doc["user_id"] = doc.get("user_id") or int(uid)
                    try:
                        db.users.insert_one(doc)
                    except Exception:
                        pass
                print("[MongoDB] Migrated users from users.json")
        except Exception as e:
            print(f"[MongoDB] Users migration failed: {e}")

    # Proxies
    proxy_path = os.path.join(DATA_DIR, "proxy.json")
    if os.path.exists(proxy_path) and db.proxies.count_documents({}) == 0:
        try:
            with open(proxy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                for uid, proxy_val in data.items():
                    try:
                        if isinstance(proxy_val, list):
                            proxies_list = [str(p) for p in proxy_val if p]
                        else:
                            proxies_list = [str(proxy_val)] if proxy_val else []
                        db.proxies.insert_one({"_id": str(uid), "proxies": proxies_list})
                    except Exception:
                        pass
                print("[MongoDB] Migrated proxies from proxy.json")
        except Exception as e:
            print(f"[MongoDB] Proxies migration failed: {e}")

    # User sites (unified)
    sites_path = os.path.join(DATA_DIR, "user_sites.json")
    if os.path.exists(sites_path) and db.user_sites.count_documents({}) == 0:
        try:
            with open(sites_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                for uid, sites in data.items():
                    if not isinstance(sites, list):
                        continue
                    try:
                        db.user_sites.insert_one({"_id": str(uid), "sites": sites})
                    except Exception:
                        pass
                print("[MongoDB] Migrated user_sites from user_sites.json")
        except Exception as e:
            print(f"[MongoDB] User sites migration failed: {e}")

    # AU gate
    au_gate_path = os.path.join(DATA_DIR, "au_gate.json")
    if os.path.exists(au_gate_path) and db.au_gates.count_documents({}) == 0:
        try:
            with open(au_gate_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                for uid, gate in data.items():
                    try:
                        db.au_gates.insert_one({"_id": str(uid), "gate": str(gate)})
                    except Exception:
                        pass
                print("[MongoDB] Migrated au_gate from au_gate.json")
        except Exception as e:
            print(f"[MongoDB] AU gate migration failed: {e}")

    # Plan requests
    pr_path = os.path.join(DATA_DIR, "plan_requests.json")
    if os.path.exists(pr_path) and db.plan_requests.count_documents({}) == 0:
        try:
            with open(pr_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                for uid, doc in data.items():
                    payload = {"_id": str(uid), **(doc or {})}
                    payload["user_id"] = payload.get("user_id") or int(uid)
                    try:
                        db.plan_requests.insert_one(payload)
                    except Exception:
                        pass
                print("[MongoDB] Migrated plan_requests from plan_requests.json")
        except Exception as e:
            print(f"[MongoDB] Plan requests migration failed: {e}")

    # Redeems: stored as {code: {used, used_by, used_at}}
    redeems_path = os.path.join(DATA_DIR, "redeems.json")
    if os.path.exists(redeems_path) and db.redeems.count_documents({}) == 0:
        try:
            with open(redeems_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                for code, doc in data.items():
                    try:
                        db.redeems.insert_one({"_id": code, "used": doc.get("used", False), "used_by": doc.get("used_by"), "used_at": doc.get("used_at")})
                    except Exception:
                        pass
                print("[MongoDB] Migrated redeems from redeems.json")
        except Exception as e:
            print(f"[MongoDB] Redeems migration failed: {e}")

    # Groups
    groups_path = os.path.join(DATA_DIR, "groups.json")
    if os.path.exists(groups_path) and db.groups.count_documents({}) == 0:
        try:
            with open(groups_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            grp = data if isinstance(data, list) else []
            try:
                db.groups.insert_one({"_id": "allowed", "groups": grp})
                print("[MongoDB] Migrated groups from groups.json")
            except Exception:
                pass
        except Exception as e:
            print(f"[MongoDB] Groups migration failed: {e}")
