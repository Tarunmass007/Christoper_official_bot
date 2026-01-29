# A–Z Deploy & Run on VPS (GitHub + MongoDB)

Step-by-step commands to deploy and run **Christopher Bot** on a **Linux VPS** from **GitHub**, with **MongoDB** installed and running on the same VPS.

**Assumptions:** Ubuntu 22.04 LTS (or 20.04). Root or sudo access. Your bot repo is on GitHub.

---

## 1. SSH into the VPS

```bash
ssh root@YOUR_VPS_IP
# Or: ssh ubuntu@YOUR_VPS_IP
```

Replace `YOUR_VPS_IP` with your server IP.

---

## 2. Update system and install base packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl software-properties-common build-essential
```

---

## 3. Install Python 3.11

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

Check:

```bash
python3.11 --version
# Should show Python 3.11.x
```

---

## 4. Install and run MongoDB

**Ubuntu 22.04:** use `jammy` below. **Ubuntu 20.04:** use `focal` instead of `jammy`.

```bash
# Import MongoDB GPG key and add repo
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor

echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

sudo apt update
sudo apt install -y mongodb-org

# Start and enable MongoDB
sudo systemctl start mongod
sudo systemctl enable mongod
```

Verify MongoDB is running:

```bash
sudo systemctl status mongod
# Should show "active (running)"
```

**Local connection string (no auth):**  
`mongodb://localhost:27017`

---

## 5. (Optional) Create MongoDB user and use auth

If you want a dedicated user and password:

```bash
mongosh
```

In `mongosh`:

```javascript
use admin
db.createUser({
  user: "botuser",
  pwd: "YOUR_STRONG_PASSWORD",
  roles: [ { role: "readWrite", db: "christopher_bot" } ]
})
exit
```

Then enable auth:

```bash
sudo nano /etc/mongod.conf
```

Under `security:` add:

```yaml
security:
  authorization: enabled
```

Restart MongoDB:

```bash
sudo systemctl restart mongod
```

Use this URI (replace password):

```text
mongodb://botuser:YOUR_STRONG_PASSWORD@localhost:27017/christopher_bot
```

---

## 6. Create app user and project directory

```bash
sudo useradd -m -s /bin/bash botapp
sudo usermod -aG sudo botapp
sudo su - botapp
```

From here on, commands run as `botapp` unless noted.

---

## 7. Clone repo from GitHub

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/Christoperbot.git
cd Christoperbot
```

Replace `YOUR_USERNAME/Christoperbot` with your actual GitHub repo (e.g. `Tarunmass007/Christoperbot`).

If the repo is **private**, use a **Personal Access Token**:

```bash
git clone https://YOUR_TOKEN@github.com/YOUR_USERNAME/Christoperbot.git
cd Christoperbot
```

---

## 8. Python virtual environment and dependencies

```bash
cd ~/Christoperbot
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 9. Create `FILES/config.json`

```bash
mkdir -p FILES
cp FILES/config.json.example FILES/config.json
nano FILES/config.json
```

Fill in (adjust values):

```json
{
  "BOT_TOKEN": "123456:ABC-DEF...",
  "API_ID": "12345678",
  "API_HASH": "abcdef1234567890...",
  "OWNER": "123456789",
  "FEEDBACK": "@YourHandle"
}
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

---

## 10. Set MongoDB URI (environment)

Create `.env` file:

```bash
nano .env
```

Add **ONE** of the following options:

**Option A – Railway MongoDB (Recommended for production):**

```env
MONGODB_URI=mongodb://mongo:YOUR_PASSWORD@containers-us-west-XXX.railway.app:XXXXX
```

Replace with your actual Railway MongoDB connection string. You can find it in Railway dashboard → Your MongoDB service → Variables → `MONGO_URL` or `MONGODB_URI`.

**Option B – Local MongoDB (No auth):**

```env
MONGODB_URI=mongodb://localhost:27017
```

**Option C – Local MongoDB (With auth, from step 5):**

```env
MONGODB_URI=mongodb://botuser:YOUR_STRONG_PASSWORD@localhost:27017/christopher_bot
```

**Option D – Railway MongoDB (Alternative format):**

If Railway provides `MONGO_URL` instead, you can use:

```env
MONGO_URL=mongodb://mongo:YOUR_PASSWORD@containers-us-west-XXX.railway.app:XXXXX
```

The bot supports both `MONGODB_URI` and `MONGO_URL` environment variables.

**Example Railway MongoDB URI format:**
```
mongodb://mongo:password123@containers-us-west-123.railway.app:6543
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

---

## 11. Create `DATA` directory (optional)

Used for JSON fallback or migration:

```bash
mkdir -p DATA
```

---

## 12. Test run (foreground)

```bash
cd ~/Christoperbot
source venv/bin/activate
python main.py
```

You should see:

- `✅ MongoDB connected and ready.` (if using MongoDB)
- `✅ Bot is running...`
- `✅ Bot commands registered for autocomplete`

Stop with `Ctrl+C`.

**Note:** If you see `⚠️ MongoDB init failed`, the bot will fall back to JSON storage in the `DATA/` directory. This is fine for testing, but for production use MongoDB (Railway or local).

---

## 13. Run as a systemd service (always-on)

Exit `botapp` shell if you’re in it:

```bash
exit
```

Create the service file:

```bash
sudo nano /etc/systemd/system/christopher-bot.service
```

Paste (adjust paths if you use a different user/repo):

```ini
[Unit]
Description=Christopher Bot (Telegram)
After=network.target mongod.service

[Service]
Type=simple
User=botapp
Group=botapp
WorkingDirectory=/home/botapp/Christoperbot
Environment="PATH=/home/botapp/Christoperbot/venv/bin"
EnvironmentFile=/home/botapp/Christoperbot/.env
ExecStart=/home/botapp/Christoperbot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save and exit.

If you prefer to **not** use `.env`, remove the `EnvironmentFile` line and add:

```ini
Environment="MONGODB_URI=mongodb://localhost:27017"
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable christopher-bot
sudo systemctl start christopher-bot
sudo systemctl status christopher-bot
```

---

## 14. Useful run/management commands

| Task | Command |
|------|---------|
| **View logs** | `sudo journalctl -u christopher-bot -f` |
| **Stop bot** | `sudo systemctl stop christopher-bot` |
| **Start bot** | `sudo systemctl start christopher-bot` |
| **Restart bot** | `sudo systemctl restart christopher-bot` |
| **Disable on boot** | `sudo systemctl disable christopher-bot` |

---

## 15. Deploy updates from GitHub

```bash
sudo systemctl stop christopher-bot
sudo su - botapp
cd ~/Christoperbot
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
exit
sudo systemctl start christopher-bot
```

One-liner (run as root or with sudo):

```bash
sudo systemctl stop christopher-bot && sudo -u botapp bash -c 'cd /home/botapp/Christoperbot && git pull origin main && source venv/bin/activate && pip install -r requirements.txt' && sudo systemctl start christopher-bot
```

---

## 16. Optional: Flask / health-check port

The app runs a small Flask server (default port `3000`). To use a different port:

```bash
# In .env
echo 'PORT=8080' >> /home/botapp/Christoperbot/.env
```

Or add to the systemd unit:

```ini
Environment="PORT=8080"
```

---

## 17. Optional: Firewall

```bash
sudo ufw allow 22
sudo ufw allow 3000
sudo ufw enable
sudo ufw status
```

---

## 18. Checklist

- [ ] VPS updated; Python 3.11 and Git installed  
- [ ] MongoDB installed, running, and (optional) user created  
- [ ] Repo cloned from GitHub  
- [ ] `venv` created; `pip install -r requirements.txt`  
- [ ] `FILES/config.json` created with `BOT_TOKEN`, `API_ID`, `API_HASH`, `OWNER`  
- [ ] `.env` (or systemd `Environment`) has `MONGODB_URI`  
- [ ] `python main.py` runs and shows MongoDB + bot OK  
- [ ] `christopher-bot` systemd service enabled and started  
- [ ] `journalctl -u christopher-bot -f` shows logs  

---

## 19. Troubleshooting

| Issue | Fix |
|-------|-----|
| **`MongoDB not configured`** | Set `MONGODB_URI` or `MONGO_URL` in `.env` or systemd `Environment`. |
| **`MongoDB init failed`** | Check URI format (Railway or local). For Railway: ensure connection string includes password and port. For local: `sudo systemctl status mongod`; verify URI (host, port, user, password). |
| **`BOT_TOKEN` / config error** | Ensure `FILES/config.json` exists and has correct keys (`BOT_TOKEN`, `API_ID`, `API_HASH`, `OWNER`). |
| **Module not found** | `source venv/bin/activate` then `pip install -r requirements.txt`. |
| **Permission denied** | Service runs as `botapp`; check ownership: `sudo chown -R botapp:botapp /home/botapp/Christoperbot`. |
| **Port in use** | Change `PORT` in `.env` or systemd and restart. |
| **Railway connection timeout** | Check firewall rules, ensure Railway MongoDB is accessible from your VPS IP. Railway may require IP whitelisting. |
| **Bot not responding** | Check logs: `sudo journalctl -u christopher-bot -f`. Verify bot token is correct in `FILES/config.json`. |

---

## 20. Summary

1. **SSH** → VPS  
2. **Install** Python 3.11, Git, MongoDB (optional if using Railway)  
3. **Start** MongoDB (`systemctl`) - Skip if using Railway  
4. **Clone** repo from GitHub  
5. **venv** + `pip install -r requirements.txt`  
6. **Create** `FILES/config.json` with bot credentials  
7. **Create** `.env` with `MONGODB_URI` (Railway or local)  
8. **Test** `python main.py`  
9. **Enable** `christopher-bot` systemd service  
10. **Update** later with `git pull` + `pip install -r requirements.txt` + `systemctl restart christopher-bot`

**MongoDB Options:**
- **Railway (Recommended):** `MONGODB_URI=mongodb://mongo:PASSWORD@containers-us-west-XXX.railway.app:XXXXX` in `.env`
- **Local VPS:** `MONGODB_URI=mongodb://localhost:27017` (or with user/pass if auth enabled)

**Bot config:** `FILES/config.json` (BOT_TOKEN, API_ID, API_HASH, OWNER)  
**Database:** `MONGODB_URI` or `MONGO_URL` in `.env`

## 21. Quick Start Commands (After Initial Setup)

**Start the bot:**
```bash
sudo systemctl start christopher-bot
```

**Stop the bot:**
```bash
sudo systemctl stop christopher-bot
```

**Restart the bot:**
```bash
sudo systemctl restart christopher-bot
```

**View live logs:**
```bash
sudo journalctl -u christopher-bot -f
```

**Update and restart:**
```bash
sudo systemctl stop christopher-bot && sudo -u botapp bash -c 'cd /home/botapp/Christoperbot && git pull origin main && source venv/bin/activate && pip install -r requirements.txt' && sudo systemctl start christopher-bot
```

**Check status:**
```bash
sudo systemctl status christopher-bot
```
