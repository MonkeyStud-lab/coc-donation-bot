#!/usr/bin/env bash
# Start Waydroid (if needed), Clash of Clans, then the donation bot.
# Intended for a clickable Ubuntu desktop launcher.
# Usage:
#   ./scripts/start_bot_desktop.sh              # prepare + run bot (terminal mode)
#   ./scripts/start_bot_desktop.sh --prepare-only  # Waydroid/ADB/CoC only (for GUI)
set -euo pipefail

PREPARE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --prepare-only) PREPARE_ONLY=1 ;;
    -h|--help)
      echo "Usage: $0 [--prepare-only]"
      exit 0
      ;;
  esac
done

# Desktop .desktop launches often have a tiny PATH — include normal system bins.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

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
    sleep 12
  fi
  exit 1
}

dump_waydroid_diagnostics() {
  echo "---- diagnostics ----"
  echo "PATH=$PATH"
  command -v waydroid >/dev/null 2>&1 && echo "waydroid=$(command -v waydroid)" || echo "waydroid=NOT FOUND"
  command -v adb >/dev/null 2>&1 && echo "adb=$(command -v adb)" || echo "adb=NOT FOUND"
  echo "systemctl waydroid-container: $(systemctl is-active waydroid-container 2>&1 || true)"
  if command -v waydroid >/dev/null 2>&1; then
    echo "waydroid status:"
    waydroid status 2>&1 || true
  fi
  echo "--------------------"
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

adb_ready() {
  command -v adb >/dev/null 2>&1 || return 1
  adb connect "$ADB_DEVICE" >/dev/null 2>&1 || true
  adb -s "$ADB_DEVICE" get-state 2>/dev/null | grep -qx device
}

container_up() {
  # Some Waydroid builds omit the Container line when the session is stopped.
  if systemctl is-active --quiet waydroid-container 2>/dev/null; then
    return 0
  fi
  command -v waydroid >/dev/null 2>&1 || return 1
  local status
  status="$(waydroid status 2>/dev/null || true)"
  echo "$status" | grep -qiE 'Container:[[:space:]]*RUNNING' && return 0
  return 1
}

session_up() {
  command -v waydroid >/dev/null 2>&1 || return 1
  waydroid status 2>/dev/null | grep -qiE 'Session:[[:space:]]*RUNNING'
}

start_waydroid_container() {
  if systemctl is-active --quiet waydroid-container 2>/dev/null; then
    echo "waydroid-container service already active"
    return 0
  fi
  if systemctl start waydroid-container 2>/dev/null; then
    return 0
  fi
  if sudo -n systemctl start waydroid-container 2>/dev/null; then
    return 0
  fi
  if command -v waydroid >/dev/null 2>&1 && sudo -n waydroid container start 2>/dev/null; then
    return 0
  fi
  # Interactive sudo (desktop Terminal=true gives a TTY).
  if [[ -t 0 ]] || [[ -t 1 ]]; then
    notify "Need your password to start Waydroid…"
    if sudo systemctl start waydroid-container; then
      return 0
    fi
    if command -v waydroid >/dev/null 2>&1 && sudo waydroid container start; then
      return 0
    fi
  fi
  return 1
}

# Always bring Waydroid up first, then Clash of Clans (even if ADB already works).
if ! command -v waydroid >/dev/null 2>&1; then
  dump_waydroid_diagnostics
  die "waydroid command not found. Install Waydroid, then retry."
fi

if ! container_up; then
  notify "Starting Waydroid container…"
  if ! start_waydroid_container; then
    dump_waydroid_diagnostics
    die "Could not start Waydroid container. In a terminal run: sudo systemctl start waydroid-container"
  fi
  for _ in $(seq 1 45); do
    container_up && break
    sleep 1
  done
  if ! container_up; then
    dump_waydroid_diagnostics
    die "Waydroid container did not become ready. Try: sudo systemctl restart waydroid-container && waydroid status"
  fi
fi

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
  if ! session_up; then
    dump_waydroid_diagnostics
    die "Waydroid session did not become ready. Try: waydroid session start"
  fi
fi

notify "Opening Waydroid…"
# Full Android UI first (what you see as "opening Waydroid").
nohup waydroid show-full-ui >>"$LOG_DIR/waydroid-ui.log" 2>&1 &
sleep 3

notify "Connecting ADB ($ADB_DEVICE)…"
command -v adb >/dev/null 2>&1 || die "adb not found — run: ./scripts/setup_linux.sh"
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
if [[ "$ready" -ne 1 ]]; then
  dump_waydroid_diagnostics
  die "ADB device $ADB_DEVICE not ready. Start Waydroid manually, then: adb connect $ADB_DEVICE"
fi

coc_running() {
  adb -s "$ADB_DEVICE" shell "pidof $COC_PKG" 2>/dev/null | grep -Eq '[0-9]'
}

notify "Opening Clash of Clans…"
if coc_running; then
  echo "Clash of Clans already running — bringing it to the front"
fi
# Launch CoC after Waydroid UI is up (single launch path; monkey is fallback).
if ! waydroid app launch "$COC_PKG" 2>/dev/null; then
  adb -s "$ADB_DEVICE" shell monkey -p "$COC_PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
fi

notify "Waiting for game to load…"
for _ in $(seq 1 20); do
  coc_running && break
  sleep 1
done
sleep 8

if [[ ! -f "$COC_BOT_CONFIG" ]]; then
  die "Missing calibration file: $COC_BOT_CONFIG — run: python scripts/calibrate.py"
fi

if [[ "$PREPARE_ONLY" -eq 1 ]]; then
  notify "Ready — Waydroid + Clash of Clans should be open"
  echo "PREPARE_OK"
  exit 0
fi

notify "Bot running — close this window or Ctrl+C to stop"
echo "Log file: $LOG_FILE"
echo

exec "$VENV_PY" -m coc_bot.main
