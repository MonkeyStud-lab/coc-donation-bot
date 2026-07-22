#!/usr/bin/env bash
# Start Waydroid (if needed), Clash of Clans, then the donation bot.
# Intended for a clickable Ubuntu desktop launcher.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/desktop-start-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

notify() {
  local msg="$1"
  echo "==> $msg"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -a "CoC Donation Bot" "CoC Donation Bot" "$msg" || true
  fi
}

die() {
  notify "Failed: $1"
  echo "ERROR: $1" >&2
  echo "Log: $LOG_FILE" >&2
  if [[ -t 0 ]]; then
    read -r -p "Press Enter to close..."
  else
    sleep 8
  fi
  exit 1
}

COC_PKG="com.supercell.clashofclans"
VENV_PY="$ROOT/.venv/bin/python"
SETUP_SCRIPT="$ROOT/scripts/setup_linux.sh"

if [[ ! -x "$SETUP_SCRIPT" ]]; then
  chmod +x "$SETUP_SCRIPT" 2>/dev/null || true
fi

if [[ ! -x "$VENV_PY" ]] || [[ ! -f "$ROOT/.setup_linux_stamp" ]]; then
  notify "First run — installing dependencies (may take several minutes)…"
  bash "$SETUP_SCRIPT" || die "Automatic setup failed — run: ./scripts/setup_linux.sh"
fi

if [[ ! -x "$VENV_PY" ]]; then
  die "Missing venv at $VENV_PY — run: ./scripts/setup_linux.sh"
fi

resolve_adb_device() {
  if [[ -n "${ADB_DEVICE:-}" ]]; then
    printf '%s\n' "$ADB_DEVICE"
    return
  fi
  ROOT="$ROOT" "$VENV_PY" - <<'PY'
from pathlib import Path
import os
import yaml

root = Path(os.environ["ROOT"])
for rel in ("data/calibrated.yaml", "config/default.yaml"):
    path = root / rel
    if not path.exists():
        continue
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    device = (data.get("adb") or {}).get("device")
    if device:
        print(device)
        break
PY
}

ADB_DEVICE="$(resolve_adb_device | tail -n1)"
ADB_DEVICE="${ADB_DEVICE:-192.168.240.112:5555}"
export ADB_DEVICE
export COC_BOT_CONFIG="${COC_BOT_CONFIG:-$ROOT/data/calibrated.yaml}"
export PYTHONUNBUFFERED=1

notify "Starting… (device $ADB_DEVICE)"

container_up() {
  waydroid status 2>/dev/null | grep -qiE 'Container:[[:space:]]*RUNNING'
}

if ! container_up; then
  notify "Starting Waydroid container…"
  if systemctl is-active --quiet waydroid-container 2>/dev/null; then
    :
  elif systemctl start waydroid-container 2>/dev/null; then
    :
  elif sudo -n systemctl start waydroid-container 2>/dev/null; then
    :
  else
    die "Waydroid container is not running. Start it once with: sudo systemctl start waydroid-container"
  fi
  for _ in $(seq 1 30); do
    container_up && break
    sleep 1
  done
  container_up || die "Waydroid container did not become ready"
fi

session_up() {
  waydroid status 2>/dev/null | grep -qiE 'Session:[[:space:]]*RUNNING'
}

if ! session_up; then
  notify "Starting Waydroid session…"
  if systemctl --user start waydroid-session.service 2>/dev/null; then
    :
  else
    nohup waydroid session start >>"$LOG_DIR/waydroid-session.log" 2>&1 &
  fi
  for _ in $(seq 1 60); do
    session_up && break
    sleep 1
  done
  session_up || die "Waydroid session did not become ready (is a Wayland desktop session active?)"
fi

notify "Connecting ADB ($ADB_DEVICE)…"
command -v adb >/dev/null 2>&1 || die "adb not found — install: sudo apt install android-tools-adb"
adb connect "$ADB_DEVICE" >/dev/null || true
ready=0
for _ in $(seq 1 30); do
  if adb -s "$ADB_DEVICE" get-state 2>/dev/null | grep -qx device; then
    ready=1
    break
  fi
  adb connect "$ADB_DEVICE" >/dev/null || true
  sleep 1
done
[[ "$ready" -eq 1 ]] || die "ADB device $ADB_DEVICE not ready"

notify "Launching Clash of Clans…"
if command -v waydroid >/dev/null 2>&1; then
  waydroid app launch "$COC_PKG" >/dev/null 2>&1 || true
fi
adb -s "$ADB_DEVICE" shell monkey -p "$COC_PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true

notify "Waiting for game to load…"
sleep 12

if [[ ! -f "$COC_BOT_CONFIG" ]]; then
  die "Missing calibration file: $COC_BOT_CONFIG — run: python scripts/calibrate.py"
fi

notify "Bot running — close this window or Ctrl+C to stop"
echo "Log file: $LOG_FILE"
echo

exec "$VENV_PY" -m coc_bot.main
