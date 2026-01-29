# Telegram Bot Setup Guide

This guide will help you set up and run the Telegram bot using Supervisor for process management.

## Prerequisites

- Python 3.7 or higher
- pip (Python package installer)
- Root or sudo access

## Installation Steps

### 1. Install Python Dependencies

```bash
cd /home/user/bot
pip3 install -r FILES/requirements.txt
```

### 2. Configure Bot Credentials

Edit the `FILES/config.json` file with your Telegram bot credentials:

```json
{
    "API_ID": "your_api_id",
    "API_HASH": "your_api_hash",
    "BOT_TOKEN": "your_bot_token"
}
```

### 3. Install Supervisor

Supervisor is a process control system that will keep your bot running and automatically restart it if it crashes.

#### For Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install supervisor -y
```

#### For CentOS/RHEL:
```bash
sudo yum install supervisor -y
sudo systemctl enable supervisord
sudo systemctl start supervisord
```

#### For Fedora:
```bash
sudo dnf install supervisor -y
sudo systemctl enable supervisord
sudo systemctl start supervisord
```

### 4. Configure Supervisor for the Bot

Copy the supervisor configuration file to the appropriate directory:

```bash
sudo cp telegram_bot.conf /etc/supervisor/conf.d/
```

### 5. Update Supervisor Configuration

After copying the configuration file, update supervisor to load the new configuration:

```bash
sudo supervisorctl reread
sudo supervisorctl update
```

## Managing the Bot

### Start the Bot
```bash
sudo supervisorctl start telegram_bot
```

### Stop the Bot
```bash
sudo supervisorctl stop telegram_bot
```

### Restart the Bot
```bash
sudo supervisorctl restart telegram_bot
```

### Check Bot Status
```bash
sudo supervisorctl status telegram_bot
```

### View Bot Logs

Output logs:
```bash
sudo tail -f /var/log/telegram_bot.out.log
```

Error logs:
```bash
sudo tail -f /var/log/telegram_bot.err.log
```

## Troubleshooting

### Supervisor command not found

If you get the error `sudo: supervisorctl: command not found`, it means Supervisor is not installed. Follow step 3 above to install it.

### Bot won't start

1. Check the logs for errors:
   ```bash
   sudo tail -n 50 /var/log/telegram_bot.err.log
   ```

2. Verify your config.json has the correct credentials

3. Make sure all Python dependencies are installed:
   ```bash
   pip3 install -r FILES/requirements.txt
   ```

### Permission issues

If you encounter permission issues, make sure:
- The bot directory and files are accessible
- The user specified in the supervisor config has appropriate permissions

### Check Supervisor Status

To verify supervisor itself is running:
```bash
sudo systemctl status supervisor
```

or

```bash
sudo service supervisor status
```

## Auto-start on System Boot

Supervisor will automatically start your bot when the system boots, as long as:
1. Supervisor service is enabled (it should be by default after installation)
2. The `autostart=true` setting is in the configuration file (already set)

## Manual Running (Without Supervisor)

If you prefer to run the bot manually without supervisor:

```bash
cd /home/user/bot
python3 main.py
```

Note: This will not auto-restart the bot if it crashes, and will stop when you close the terminal.
