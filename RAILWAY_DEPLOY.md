# Deploy Christopher Bot on Railway with MongoDB

Step-by-step guide to run the bot on **Railway** and connect it to **MongoDB**.  
**Only DB connection is set manually** (env). All other credentials are **read from your existing code** (`FILES/config.json`).

---

## Quick steps (overview)

1. **New Project** on Railway → Deploy from GitHub (this repo).
2. **+ New** → **Database** → **Add MongoDB**.
3. In the **bot service** → **Variables**, add **only**:
   - **`MONGODB_URI`** = `${{MongoDB.MONGO_URL}}`  
     (or **`MONGO_URL`** if Railway injects it; replace `MongoDB` with your MongoDB service name if different.)
4. Ensure **`FILES/config.json`** exists in your project with `BOT_TOKEN`, `API_ID`, `API_HASH`, `OWNER`, `FEEDBACK` (see `FILES/config.json.example`).
5. **Procfile** already sets `web: python main.py`. Deploy.
6. Check logs for `✅ MongoDB connected and ready.` and `✅ Bot is running...`.

---

## Credentials: config vs DB

| Source | What |
|--------|-----|
| **`FILES/config.json`** | `BOT_TOKEN`, `API_ID`, `API_HASH`, `OWNER`, `FEEDBACK` — **fetched from existing code**. |
| **Env (Variables)** | **DB only:** `MONGODB_URI` or `MONGO_URL`. **This is the only value you add manually** for MongoDB. |

No need to duplicate bot credentials in Railway Variables. The app loads them from `config.json`.

---

## 1. Create a new Railway project

1. Go to [railway.app](https://railway.app) → **Login** (e.g. GitHub).
2. **New Project** → **Deploy from GitHub repo**.
3. Connect GitHub and select the **Christoperbot** repo (or the repo containing this bot).
4. Railway adds a **service** for the app.

---

## 2. Add MongoDB

1. In the same **Project**, click **+ New** → **Database** → **Add MongoDB**.
2. Railway provisions MongoDB and exposes **`MONGO_URL`** (and optionally **`MONGO_PRIVATE_URL`**).

---

## 3. Add only DB connection (manual)

1. Select your **bot service**.
2. Open **Variables**.
3. Add **one** variable:
   - **Name:** `MONGODB_URI`
   - **Value:** `${{MongoDB.MONGO_URL}}`  
     (Use Railway’s reference syntax; replace `MongoDB` with your MongoDB service name if it differs.)
4. Alternatively, if Railway injects **`MONGO_URL`** into the bot service (e.g. via service linking), you can use that as-is. The bot accepts either **`MONGODB_URI`** or **`MONGO_URL`**.

**Do not** add `BOT_TOKEN`, `API_ID`, `API_HASH`, or `OWNER` here. Those come from `config.json`.

---

## 4. Ensure `FILES/config.json` exists

All bot credentials are **read from** `FILES/config.json`:

- `BOT_TOKEN` — Telegram bot token
- `API_ID` — Telegram API ID
- `API_HASH` — Telegram API hash
- `OWNER` — Your Telegram user ID
- `FEEDBACK` — Feedback handle (optional)

Use **`FILES/config.json.example`** as a template: copy to `FILES/config.json`, fill in real values, and ensure **`config.json` is part of your deployment** (e.g. in repo or added via your deploy process).  
If `config.json` is gitignored, you must provide it another way (e.g. secret file, build step) so it exists at runtime.

---

## 5. Port and Procfile

- The app uses **`PORT`** from the environment for the Flask health endpoint. Railway sets this automatically.
- **Procfile:** `web: python main.py`. No change needed.

---

## 6. Deploy

1. Push to the connected branch (e.g. `main`). Railway builds and deploys.
2. In **Deployments** → **View Logs**, confirm:
   - `✅ MongoDB connected and ready.`
   - `✅ Bot is running...`

If MongoDB init fails, the app falls back to JSON storage (not suitable on Railway due to ephemeral filesystem). Fix **`MONGODB_URI`** / **`MONGO_URL`** and redeploy.

---

## 7. Troubleshooting

| Issue | What to do |
|-------|------------|
| **Build fails** | Ensure `requirements.txt` includes `pymongo>=4.0`. Run `pip install -r requirements.txt` locally to verify. |
| **App crashes on start** | Check `FILES/config.json` exists and has `BOT_TOKEN`, `API_ID`, `API_HASH`, `OWNER`. See `config.json.example`. |
| **MongoDB connection error** | Set **`MONGODB_URI`** or **`MONGO_URL`** in Variables. Use `${{MongoDB.MONGO_URL}}` when using Railway’s MongoDB. Ensure bot and MongoDB are in the same project. |
| **Users not persisting** | Verify logs show `✅ MongoDB connected and ready.` |

---

## 8. Summary checklist

- [ ] Railway project created; bot service deployed from repo.
- [ ] **MongoDB** added (`+ New` → **Database** → **MongoDB**).
- [ ] **Variables:** only **`MONGODB_URI`** = `${{MongoDB.MONGO_URL}}` (or **`MONGO_URL`**).
- [ ] **`FILES/config.json`** present with bot credentials (see `config.json.example`).
- [ ] **Procfile** used: `web: python main.py`.
- [ ] Deploy successful; logs show MongoDB connected and bot running.

**Only DB info is added manually.** All other credentials are loaded from your existing `config.json`.
