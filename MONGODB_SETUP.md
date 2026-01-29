# MongoDB Setup for Christopher Bot

This guide explains how to configure MongoDB so the bot persists **users**, **proxies**, **sites/URLs**, **subscriptions**, **plan requests**, **redeems**, **groups**, and **Stripe Auth gate** (nomade-studio.be/grownetics.com).  
With MongoDB enabled, **no re-registration** is needed on redeploy—all data survives restarts.

---

## 1. Install MongoDB

### Option A: Local (Windows / Linux / macOS)

- **Windows:** [MongoDB Community Download](https://www.mongodb.com/try/download/community) → install → ensure service is running.
- **Linux (Ubuntu/Debian):**
  ```bash
  sudo apt update && sudo apt install -y mongodb
  sudo systemctl start mongod
  sudo systemctl enable mongod
  ```
- **macOS:** `brew install mongodb-community` then `brew services start mongodb-community`.

### Option B: MongoDB Atlas (cloud)

1. Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas).
2. Create a free cluster.
3. **Database Access** → Add user (username + password).
4. **Network Access** → Add IP (e.g. `0.0.0.0` for anywhere, or your server IP).
5. **Connect** → **Connect your application** → copy the connection string, e.g.:
   ```
   mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```

---

## 2. Set MongoDB connection (env only)

**DB connection is configured via environment variables only.** Do not put `MONGODB_URI` in `FILES/config.json`.  
All other credentials (BOT_TOKEN, API_ID, API_HASH, OWNER, FEEDBACK) come from `FILES/config.json`.

Set **one** of:

- **`MONGODB_URI`** — preferred.
- **`MONGO_URL`** — e.g. Railway MongoDB plugin.

**Examples:**

- **Local MongoDB (default port):**
  ```bash
  export MONGODB_URI="mongodb://localhost:27017"
  ```
- **Local with auth:**
  ```bash
  export MONGODB_URI="mongodb://username:password@localhost:27017"
  ```
- **Atlas:**
  ```bash
  export MONGODB_URI="mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
  ```

Use a **.env** file or your host’s env settings (Docker, systemd, Railway Variables, etc.) as needed.

---

## 3. Install Python dependency

```bash
pip install pymongo>=4.0
```

Or, from project root:

```bash
pip install -r requirements.txt
```

---

## 4. Run the bot

```bash
python main.py
```

- If `MONGODB_URI` is set and MongoDB is reachable:
  - You’ll see: `✅ MongoDB connected and ready.`
  - All storage uses MongoDB.
- If **not** set or MongoDB is down:
  - Bot still runs using **JSON files** in `DATA/` (legacy behavior).

---

## 5. One-time migration from JSON → MongoDB

On **first run** with MongoDB enabled, the bot automatically migrates existing data **if** the DB collections are empty:

- `DATA/users.json` → `users`
- `DATA/proxy.json` → `proxies`
- `DATA/user_sites.json` → `user_sites`
- `DATA/au_gate.json` → `au_gates`
- `DATA/plan_requests.json` → `plan_requests`
- `DATA/redeems.json` → `redeems`
- `DATA/groups.json` → `groups`

Migration runs only when each target collection is empty.  
**Back up** your `DATA/` folder before first Mongo run if you care about existing JSON data.

---

## 6. What is stored in MongoDB?

| Collection     | Purpose                                      |
|----------------|----------------------------------------------|
| `users`        | Registration, plans, credits, expiry         |
| `proxies`      | User proxies (`/setpx`, `/getpx`, `/delpx`)  |
| `user_sites`   | Shopify URLs from `/addurl`, `/txturl`       |
| `au_gates`     | Stripe Auth gate: epicalarc vs shavercity    |
| `plan_requests`| Plan requests and approval state             |
| `redeems`      | Redeem codes and usage                       |
| `groups`       | Allowed groups (`/add`, `/rmv`)              |

Database name: **`christopher_bot`**.

---

## 7. Troubleshooting

| Issue | What to do |
|-------|------------|
| `MongoDB not configured` | Set `MONGODB_URI` or `MONGO_URL` in env. |
| `pymongo not installed` | `pip install pymongo>=4.0` (or `pip install -r requirements.txt`). |
| `MongoDB init failed` / connection errors | Check MongoDB is running; verify URI (host, port, user, password); for Atlas, check IP allowlist and network access. |
| Still using JSON | Ensure `MONGODB_URI` is set **before** the bot starts and that no init error is logged. |

---

## 8. Stripe Auth gate (`/au`, `/mau`)

- **Change gate** button toggles between **epicalarc.com** and **shavercity.com.au**.
- Current gate is stored **per user** in `au_gates`.
- With MongoDB, gate choice persists across restarts.

---

**Summary:** Set `MONGODB_URI` (or `MONGO_URL`) in **env only** → install `pymongo` → run `python main.py`.  
Users, proxies, URLs, subscriptions, and gate choice are then stored in MongoDB and persist across redeploys.
