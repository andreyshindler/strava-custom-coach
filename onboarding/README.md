# Strava Custom Coach — Onboarding Web App

A zero-code customer onboarding flow. Customers fill in a web form, authorize Strava, and their personal AI coaching bot spins up automatically in its own Docker container.

## How it works

1. Customer opens your web page
2. Fills in name, FTP, weight, Telegram bot token, Strava API credentials
3. Redirected to Strava OAuth → authorizes access
4. Server saves their config, exchanges Strava tokens, spins up Docker container
5. Customer lands on success page with link to their Telegram bot

## Setup on your VPS

### 1. Directory structure

```
~/strava-coach/
├── code/                  ← your scripts (mounted read-only into every container)
│   └── scripts/
│       ├── telegram_bot.py
│       ├── strava_api.py
│       └── ...
├── users/                 ← auto-created per customer
│   ├── john/config/
│   └── sarah/config/
└── onboarding/            ← this web app
    ├── app.py
    ├── templates/
    └── requirements.txt
```

### 2. Copy your scripts

```bash
mkdir -p ~/strava-coach/code/scripts
cp /path/to/your/scripts/*.py ~/strava-coach/code/scripts/
```

### 3. Install dependencies

```bash
pip install flask --break-system-packages
# or in a virtualenv:
python3 -m venv venv && source venv/bin/activate && pip install flask
```

### 4. Configure environment

```bash
export PUBLIC_URL="https://yourserver.com"           # Your public URL (for Strava OAuth callback)
export FLASK_SECRET="your-random-secret-here"        # Any random string
export ANTHROPIC_API_KEY="sk-ant-..."                # Shared Claude API key for all users
export WEBHOOK_VERIFY_TOKEN="your-verify-token"      # Strava webhook token
export USERS_BASE_DIR="/home/laptop1/strava-coach/users"
export CODE_DIR="/home/laptop1/strava-coach/code"
```

### 5. Run the app

```bash
python3 app.py
```

For production, use gunicorn:
```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

Or run as a systemd service:
```bash
# /etc/systemd/system/strava-coach-onboarding.service
[Unit]
Description=Strava Coach Onboarding
After=network.target docker.service

[Service]
User=laptop1
WorkingDirectory=/home/laptop1/strava-coach/onboarding
Environment=PUBLIC_URL=https://yourserver.com
Environment=FLASK_SECRET=changeme
Environment=ANTHROPIC_API_KEY=sk-ant-...
Environment=USERS_BASE_DIR=/home/laptop1/strava-coach/users
Environment=CODE_DIR=/home/laptop1/strava-coach/code
ExecStart=/usr/bin/python3 app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable strava-coach-onboarding
sudo systemctl start strava-coach-onboarding
```

### 6. Open firewall port

```bash
sudo ufw allow 5000
```

## Important: Strava OAuth Callback

In your Strava API settings (strava.com/settings/api), set the **Authorization Callback Domain** to your server domain (e.g. `yourserver.com`).

The callback URL will be: `https://yourserver.com/strava/callback`

## Routes

| Route | Description |
|-------|-------------|
| `GET /` | Onboarding form |
| `POST /onboard` | Form submission → Strava redirect |
| `GET /strava/callback` | Strava OAuth callback → spins up container |
| `GET /status/<username>` | JSON status of a user's container |
| `GET /admin` | Admin overview of all users |

## Per-customer container

Each customer gets:
- Docker container named `strava-coach-{username}`
- Config at `~/strava-coach/users/{username}/config/`
  - `config.json` — their Telegram token, Strava credentials, FTP, weight
  - `tokens.json` — their Strava OAuth tokens (auto-saved)
  - `training_plan.json` — auto-created when they use `/plan`
- Bot loop: polls Telegram every 5 seconds via `telegram_bot.py --once`

## Removing a customer

```bash
docker rm -f strava-coach-{username}
rm -rf ~/strava-coach/users/{username}
```
