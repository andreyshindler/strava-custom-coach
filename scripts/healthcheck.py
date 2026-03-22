#!/usr/bin/env python3
"""
healthcheck.py — Bot process + Docker container health monitor.

Checks:
  1. Native VPS bot process (telegram_bot.py --once loop)
  2. All strava-coach-* Docker containers
  3. Each container's bot process inside Docker

On failure:
  - Sends a Telegram alert to the owner
  - Attempts auto-restart
  - Sends a follow-up confirming restart succeeded or failed

Usage:
    # Run manually
    python3 scripts/healthcheck.py

    # Add to crontab — runs every 5 minutes
    */5 * * * * python3 /path/to/scripts/healthcheck.py >> ~/.config/strava/healthcheck.log 2>&1

    # Or use the install command:
    python3 scripts/healthcheck.py --install-cron
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


def _urlopen_with_retry(req, *, timeout=10, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_DIR  = Path.home() / ".config" / "strava"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE    = CONFIG_DIR / "healthcheck.log"

# Path to the native bot script on the VPS
#BOT_SCRIPT  = Path.home() / ".openclaw" / "workspace" / "skills" / "strava-custom-coach" / "scripts" / "telegram_bot.py"
BOT_SCRIPT  = Path.home() / "Projects" / "strava-staging" / "staging" / "scripts" / "telegram_bot.py"

# Docker container name prefix for customer containers
CONTAINER_PREFIX = "strava-coach-"

# How many seconds of silence before we consider the bot dead
# The bot runs every 5s, so if bot.log hasn't changed in 60s something is wrong
BOT_SILENCE_THRESHOLD = 60   # seconds


# ── Helpers ───────────────────────────────────────────────────────────────────

def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str):
    line = f"[{now()}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def send_telegram(msg: str, token: str = "", chat_id: str = ""):
    """Send a Telegram message. Falls back to config.json if not provided."""
    if not token or not chat_id:
        cfg = load_config()
        token   = token   or os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "") or cfg.get("telegram_bot_token", "")
        chat_id = chat_id or os.environ.get("STRAVA_TELEGRAM_CHAT_ID",   "") or str(cfg.get("telegram_chat_id", ""))
    if not token or not chat_id:
        log("⚠️  Cannot send Telegram alert — no token or chat_id configured")
        return False
    try:
        data = urllib.parse.urlencode({
            "chat_id":    chat_id,
            "text":       msg[:4000],
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, method="POST"
        )
        result = json.loads(_urlopen_with_retry(req, timeout=10))
        return result.get("ok", False)
    except Exception as e:
        log(f"⚠️  Telegram send failed: {e}")
        return False


# ── Check 1: Native VPS bot process ──────────────────────────────────────────

def check_native_bot() -> dict:
    """
    Checks two things:
      a) Is the wrapper loop (while true; do python3 telegram_bot.py --once) running?
      b) Has bot.log been updated recently (bot is actively processing)?
    Returns dict with 'ok', 'issue', 'action_taken'.
    """
    result = {"name": "Native VPS bot", "ok": True, "issue": "", "action_taken": ""}

    # a) Check process is running
    try:
        out = subprocess.run(
            ["pgrep", "-f", "telegram_bot.py"],
            capture_output=True, text=True
        )
        pids = [p.strip() for p in out.stdout.strip().split("\n") if p.strip()]
        if not pids:
            result["ok"]    = False
            result["issue"] = "No telegram_bot.py process found"
            return result
        result["pids"] = pids
    except Exception as e:
        result["ok"]    = False
        result["issue"] = f"pgrep failed: {e}"
        return result

    # b) Check bot.log was updated recently
    bot_log = CONFIG_DIR / "bot.log"
    if bot_log.exists():
        import time
        age = time.time() - bot_log.stat().st_mtime
        if age > BOT_SILENCE_THRESHOLD:
            result["ok"]    = False
            result["issue"] = f"bot.log not updated for {int(age)}s (threshold: {BOT_SILENCE_THRESHOLD}s)"
            return result

    return result


def restart_native_bot() -> bool:
    """Restart the native VPS bot loop using nohup."""
    try:
        # Kill existing processes
        subprocess.run(["pkill", "-f", "telegram_bot.py"], capture_output=True)
        import time
        time.sleep(2)

        if not BOT_SCRIPT.exists():
            log(f"⚠️  Bot script not found at {BOT_SCRIPT}")
            return False

        # Restart the loop detached — no shell=True to avoid injection
        log_file = open(CONFIG_DIR / "bot.log", "a")
        subprocess.Popen(
            [
                "nohup", "bash", "-c",
                f"while true; do python3 {BOT_SCRIPT} --once; sleep 5; done",
            ],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
        time.sleep(3)

        # Verify it started
        out = subprocess.run(["pgrep", "-f", "telegram_bot.py"], capture_output=True, text=True)
        return bool(out.stdout.strip())
    except Exception as e:
        log(f"⚠️  Restart failed: {e}")
        return False


# ── Check 2: Docker containers ────────────────────────────────────────────────

def get_strava_containers() -> list[dict]:
    """List all strava-coach-* containers and their status."""
    try:
        out = subprocess.run(
            ["docker", "ps", "-a",
             "--filter", f"name={CONTAINER_PREFIX}",
             "--format", "{{.Names}}\t{{.Status}}\t{{.State}}"],
            capture_output=True, text=True
        )
        containers = []
        for line in out.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                containers.append({
                    "name":   parts[0].strip(),
                    "status": parts[1].strip(),
                    "state":  parts[2].strip(),
                })
        return containers
    except Exception as e:
        log(f"⚠️  Docker ps failed: {e}")
        return []


def check_container(container: dict) -> dict:
    """
    Check a single Docker container:
      a) Is it running?
      b) Is the bot process alive inside it?
      c) Has the container restarted recently (crash loop)?
    """
    name   = container["name"]
    result = {"name": name, "ok": True, "issue": "", "action_taken": ""}

    # a) Is it running?
    if container["state"] != "running":
        result["ok"]    = False
        result["issue"] = f"Container state is '{container['state']}' (expected: running)"
        return result

    # b) Check bot process inside container
    try:
        out = subprocess.run(
            ["docker", "exec", name, "pgrep", "-f", "telegram_bot.py"],
            capture_output=True, text=True, timeout=10
        )
        if not out.stdout.strip():
            result["ok"]    = False
            result["issue"] = "No telegram_bot.py process running inside container"
            return result
    except subprocess.TimeoutExpired:
        result["ok"]    = False
        result["issue"] = "docker exec timed out — container may be frozen"
        return result
    except Exception as e:
        result["ok"]    = False
        result["issue"] = f"docker exec failed: {e}"
        return result

    # c) Check restart count — flag if restarted more than 3 times recently
    try:
        out = subprocess.run(
            ["docker", "inspect",
             "--format", "{{.RestartCount}}",
             name],
            capture_output=True, text=True
        )
        restart_count = int(out.stdout.strip() or "0")
        if restart_count > 3:
            result["warning"] = f"Container has restarted {restart_count} times"
    except Exception:
        pass

    return result


def restart_container(name: str) -> bool:
    """Restart a Docker container."""
    try:
        subprocess.run(["docker", "restart", name], capture_output=True, timeout=30)
        import time
        time.sleep(5)
        # Verify it's running
        out = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", name],
            capture_output=True, text=True
        )
        return out.stdout.strip() == "true"
    except Exception as e:
        log(f"⚠️  Container restart failed for {name}: {e}")
        return False


def restart_bot_in_container(name: str) -> bool:
    """Restart just the bot loop inside a running container."""
    try:
        # Kill existing bot process
        subprocess.run(
            ["docker", "exec", name, "pkill", "-f", "telegram_bot.py"],
            capture_output=True
        )
        import time
        time.sleep(2)
        # Start fresh loop detached
        subprocess.run([
            "docker", "exec", "-d", name,
            "bash", "-c",
            "while true; do python3 /workspace/scripts/telegram_bot.py --once; sleep 5; done"
        ], check=True)
        time.sleep(3)
        # Verify
        out = subprocess.run(
            ["docker", "exec", name, "pgrep", "-f", "telegram_bot.py"],
            capture_output=True, text=True
        )
        return bool(out.stdout.strip())
    except Exception as e:
        log(f"⚠️  Bot restart in container {name} failed: {e}")
        return False


# ── Get Telegram credentials for a container ─────────────────────────────────

def get_container_credentials(name: str) -> tuple[str, str]:
    """Read bot token and chat_id from a container's config.json."""
    try:
        out = subprocess.run(
            ["docker", "exec", name, "cat", "/root/.config/strava/config.json"],
            capture_output=True, text=True, timeout=5
        )
        cfg = json.loads(out.stdout)
        return cfg.get("telegram_bot_token", ""), str(cfg.get("telegram_chat_id", ""))
    except Exception:
        return "", ""


# ── Main health check run ─────────────────────────────────────────────────────

def run_healthcheck(dry_run: bool = False):
    log("=" * 55)
    log("Health check started")

    issues   = []
    warnings = []

    # ── 1. Check native VPS bot ───────────────────────────────────────────────
    log("Checking native VPS bot...")
    native = check_native_bot()

    if not native["ok"]:
        log(f"❌ Native bot DOWN: {native['issue']}")
        issues.append(native)

        if not dry_run:
            log("   Attempting restart...")
            restarted = restart_native_bot()
            native["action_taken"] = "restarted ✅" if restarted else "restart FAILED ❌"
            log(f"   Restart result: {native['action_taken']}")

            # Alert owner via their own bot
            status_emoji = "✅" if restarted else "❌"
            send_telegram(
                f"🚨 *Native Bot Alert*\n\n"
                f"*Issue:* {native['issue']}\n"
                f"*Restart:* {native['action_taken']}\n"
                f"*Time:* {now()}"
            )
    else:
        pids = native.get("pids", [])
        log(f"✅ Native bot OK (PID: {', '.join(pids)})")

    # ── 2. Check Docker containers ────────────────────────────────────────────
    containers = get_strava_containers()

    if not containers:
        log("ℹ️  No strava-coach-* Docker containers found")
    else:
        log(f"Checking {len(containers)} Docker container(s)...")

    for container in containers:
        name   = container["name"]
        result = check_container(container)

        if "warning" in result:
            log(f"⚠️  {name}: {result['warning']}")
            warnings.append(result)

        if not result["ok"]:
            log(f"❌ {name} DOWN: {result['issue']}")
            issues.append(result)

            if not dry_run:
                # Get this customer's Telegram credentials
                token, chat_id = get_container_credentials(name)

                # Try restarting just the bot loop first
                log(f"   Attempting bot loop restart in {name}...")
                restarted = restart_bot_in_container(name)

                if not restarted:
                    # If that fails, restart the whole container
                    log(f"   Bot loop restart failed — restarting container {name}...")
                    restarted = restart_container(name)

                result["action_taken"] = "restarted ✅" if restarted else "restart FAILED ❌"
                log(f"   Result: {result['action_taken']}")

                # Alert the customer via their own bot
                if token and chat_id:
                    send_telegram(
                        f"🚨 *Your Coach Bot was down*\n\n"
                        f"*Issue:* {result['issue']}\n"
                        f"*Status:* {result['action_taken']}\n"
                        f"*Time:* {now()}\n\n"
                        f"_Your bot has been automatically restarted._",
                        token=token,
                        chat_id=chat_id,
                    )

                # Also alert you (owner) via your native bot
                send_telegram(
                    f"🚨 *Container Alert*\n\n"
                    f"*Container:* `{name}`\n"
                    f"*Issue:* {result['issue']}\n"
                    f"*Action:* {result['action_taken']}\n"
                    f"*Time:* {now()}"
                )
        else:
            log(f"✅ {name} OK")

    # ── Summary ───────────────────────────────────────────────────────────────
    total    = 1 + len(containers)   # native + containers
    failures = len(issues)
    log(f"Health check done — {total} checked, {failures} issue(s), {len(warnings)} warning(s)")
    log("=" * 55)

    return failures == 0


# ── Cron installer ────────────────────────────────────────────────────────────

def install_cron():
    """Add healthcheck.py to crontab to run every 5 minutes."""
    script_path = Path(__file__).resolve()
    python_path = sys.executable
    log_path    = CONFIG_DIR / "healthcheck.log"

    cron_line = (
        f"*/5 * * * * {python_path} {script_path} "
        f">> {log_path} 2>&1"
    )

    # Read existing crontab
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    if str(script_path) in existing:
        print("✅ Healthcheck cron job already installed:")
        for line in existing.split("\n"):
            if str(script_path) in line:
                print(f"   {line}")
        return

    # Append and write back
    new_crontab = existing.rstrip("\n") + "\n" + cron_line + "\n"
    proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True)

    if proc.returncode == 0:
        print(f"✅ Cron job installed:\n   {cron_line}")
    else:
        print(f"❌ Failed to install cron job. Add this manually:\n   {cron_line}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Strava Coach Bot health monitor")
    parser.add_argument("--dry-run",      action="store_true", help="Check only, no restarts or alerts")
    parser.add_argument("--install-cron", action="store_true", help="Install cron job to run every 5 minutes")
    args = parser.parse_args()

    if args.install_cron:
        install_cron()
        return

    ok = run_healthcheck(dry_run=args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
