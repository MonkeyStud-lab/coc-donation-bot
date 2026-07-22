#!/usr/bin/env bash
# Stop the donation bot (and optionally force-stop Clash of Clans).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COC_PKG="com.supercell.clashofclans"

notify() {
  local msg="$1"
  echo "==> $msg"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -a "CoC Donation Bot" "CoC Donation Bot" "$msg" || true
  fi
}

# Stop only the donation loop — do not kill the control GUI (bot_gui.py).
pkill -f "python -m coc_bot.main" 2>/dev/null || true
pkill -f "[Pp]ython .*-m coc_bot.main" 2>/dev/null || true
sleep 0.3
pkill -9 -f "python -m coc_bot.main" 2>/dev/null || true

# Also stop systemd user service if enabled.
if systemctl --user is-active --quiet coc-donation-bot.service 2>/dev/null; then
  systemctl --user stop coc-donation-bot.service || true
fi

if [[ "${1:-}" == "--stop-game" ]]; then
  ADB_DEVICE="${ADB_DEVICE:-}"
  if [[ -z "$ADB_DEVICE" && -x "$ROOT/.venv/bin/python" ]]; then
    ADB_DEVICE="$(
      ROOT="$ROOT" "$ROOT/.venv/bin/python" - <<'PY'
from pathlib import Path
import os, yaml
root = Path(os.environ["ROOT"])
for rel in ("data/calibrated.yaml", "config/default.yaml"):
    path = root / rel
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        device = (data.get("adb") or {}).get("device")
        if device:
            print(device)
            break
PY
    )"
  fi
  ADB_DEVICE="${ADB_DEVICE:-192.168.240.112:5555}"
  adb -s "$ADB_DEVICE" shell "am force-stop $COC_PKG" >/dev/null 2>&1 || true
  notify "Bot stopped and Clash of Clans force-stopped"
else
  notify "Bot stopped (game left running)"
fi
