#!/usr/bin/env bash
# Install a single desktop shortcut that opens a terminal and starts the bot GUI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
SCRIPT="$ROOT/scripts/run_bot.sh"

chmod +x "$SCRIPT" "$ROOT/scripts/install_run_shortcut.sh"
mkdir -p "$DESKTOP_DIR" "$APPS_DIR"

write_desktop() {
  local out="$1"
  cat >"$out" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=CoC Donation Bot
Comment=Open a terminal and run the donation bot
Exec=/bin/bash -lc 'cd "$ROOT" && ./scripts/run_bot.sh; echo; read -r -p "Press Enter to close…"'
Path=$ROOT
Terminal=true
Categories=Game;Utility;
StartupNotify=true
EOF
  chmod +x "$out"
  if command -v gio >/dev/null 2>&1; then
    gio set -t string "$out" metadata::trusted true 2>/dev/null || true
  fi
}

write_desktop "$DESKTOP_DIR/coc-donation-bot.desktop"
write_desktop "$APPS_DIR/coc-donation-bot.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

echo "Installed shortcut:"
echo "  $DESKTOP_DIR/coc-donation-bot.desktop"
echo
echo "Double-click it (Allow Launching if Ubuntu asks)."
echo "It opens a terminal, activates .venv, and runs: python -m coc_bot.main"
