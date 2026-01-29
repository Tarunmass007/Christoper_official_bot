# Git Push Commands

## Step-by-Step Commands to Push All Changes

### 1. Navigate to Project Directory
```bash
cd c:\Users\shree\OneDrive\Desktop\Christoperbot
```

### 2. Check Current Status
```bash
git status
```

### 3. Add All Modified and New Files
```bash
git add .
```

Or add specific files:
```bash
git add BOT/Charge/Shopify/slf/tsh.py
git add BOT/tools/proxy.py
git add BOT/Charge/Shopify/slf/single.py
git add BOT/Charge/Shopify/slf/slf.py
git add BOT/Charge/Shopify/slf/mass.py
git add BOT/Charge/Shopify/slf/addurl.py
git add BOT/Charge/Shopify/slf/txturl.py
git add VPS_DEPLOY.md
git add .env.example
git add IMPROVEMENTS_SUMMARY.md
git add GIT_PUSH_COMMANDS.md
```

### 4. Commit Changes with Descriptive Message
```bash
git commit -m "feat: Enhanced throttle handling and multiple proxy support

- Implemented adaptive RateLimitedChecker with dynamic delay adjustment
- Added multiple proxy support per user with rotation
- Added /import_proxies command for bulk proxy import
- Updated all checker files to use get_rotating_proxy()
- Enhanced VPS deployment guide with Railway MongoDB support
- Created .env.example template
- Improved rate limiting to reduce 429 errors
- Better proxy distribution across requests"
```

### 5. Push to Remote Repository
```bash
git push origin main
```

Or if your branch is different:
```bash
git push origin master
```

### 6. If Push Fails (Force Push - Use with Caution)
```bash
# Only if you need to overwrite remote changes
git push origin main --force
```

---

## One-Liner Commands

### Quick Add, Commit, and Push:
```bash
git add . && git commit -m "feat: Enhanced throttle handling and multiple proxy support" && git push origin main
```

### With More Detailed Commit:
```bash
git add . && git commit -m "feat: Enhanced throttle handling and multiple proxy support

- Implemented adaptive RateLimitedChecker with dynamic delay adjustment
- Added multiple proxy support per user with rotation
- Added /import_proxies command for bulk proxy import
- Updated all checker files to use get_rotating_proxy()
- Enhanced VPS deployment guide with Railway MongoDB support
- Created .env.example template
- Improved rate limiting to reduce 429 errors
- Better proxy distribution across requests" && git push origin main
```

---

## Check What Will Be Pushed

### View Changes:
```bash
git diff --staged
```

### View Commit History:
```bash
git log --oneline -5
```

### View Remote Status:
```bash
git remote -v
```

---

## Troubleshooting

### If you get "Updates were rejected":
```bash
# Pull latest changes first
git pull origin main

# Resolve any conflicts, then:
git add .
git commit -m "Merge remote changes"
git push origin main
```

### If you need to set upstream:
```bash
git push -u origin main
```

### If you want to see what files changed:
```bash
git status --short
```

---

## Files Changed Summary

**Modified Files:**
- `BOT/Charge/Shopify/slf/tsh.py` - Enhanced throttle handling
- `BOT/tools/proxy.py` - Multiple proxy support
- `BOT/Charge/Shopify/slf/single.py` - Proxy rotation
- `BOT/Charge/Shopify/slf/slf.py` - Proxy rotation
- `BOT/Charge/Shopify/slf/mass.py` - Proxy rotation
- `BOT/Charge/Shopify/slf/addurl.py` - Proxy rotation
- `BOT/Charge/Shopify/slf/txturl.py` - Proxy rotation
- `VPS_DEPLOY.md` - Enhanced deployment guide

**New Files:**
- `.env.example` - Environment variable template
- `IMPROVEMENTS_SUMMARY.md` - Summary of all improvements
- `GIT_PUSH_COMMANDS.md` - This file

---

## Recommended Workflow

1. **Review changes:**
   ```bash
   git status
   git diff
   ```

2. **Stage changes:**
   ```bash
   git add .
   ```

3. **Commit:**
   ```bash
   git commit -m "Your commit message"
   ```

4. **Push:**
   ```bash
   git push origin main
   ```

5. **Verify:**
   ```bash
   git log --oneline -1
   ```

---

**Note:** Make sure you're on the correct branch before pushing!
