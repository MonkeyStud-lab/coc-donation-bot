#!/usr/bin/env bash
# Install clickable Start/Stop icons on the Ubuntu desktop + app menu.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_SRC="$ROOT/desktop/coc-donation-bot.svg"

chmod +x \
  "$ROOT/scripts/setup_linux.sh" \
  "$ROOT/scripts/start_bot_desktop.sh" \
  "$ROOT/scripts/stop_bot_desktop.sh" \
  "$ROOT/scripts/install_desktop_launcher.sh"

echo "==> Ensuring Linux dependencies are installed…"
"$ROOT/scripts/setup_linux.sh"

mkdir -p "$DESKTOP_DIR" "$APPS_DIR"

write_desktop() {
  local out="$1"
  local name="$2"
  local comment="$3"
  local exec_cmd="$4"
  local terminal="$5"
  cat >"$out" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$name
Comment=$comment
Exec=$exec_cmd
Icon=$ICON_SRC
Terminal=$terminal
Categories=Game;Utility;
StartupNotify=true
EOF
  chmod +x "$out"
  # GNOME marks downloaded/copied launchers untrusted until this is set.
  if command -v gio >/dev/null 2>&1; then
    gio set -t string "$out" metadata::trusted true 2>/dev/null || true
  fi
}

START_EXEC="/bin/bash \"$ROOT/scripts/start_bot_desktop.sh\""
STOP_EXEC="/bin/bash \"$ROOT/scripts/stop_bot_desktop.sh\""

write_desktop \
  "$DESKTOP_DIR/coc-donation-bot.desktop" \
  "CoC Donation Bot" \
  "Start Waydroid, Clash of Clans, and the donation bot" \
  "$START_EXEC" \
  true

write_desktop \
  "$DESKTOP_DIR/coc-donation-bot-stop.desktop" \
  "Stop CoC Donation Bot" \
  "Stop the donation bot (leaves the game running)" \
  "$STOP_EXEC" \
  false

write_desktop \
  "$APPS_DIR/coc-donation-bot.desktop" \
  "CoC Donation Bot" \
  "Start Waydroid, Clash of Clans, and the donation bot" \
  "$START_EXEC" \
  true

write_desktop \
  "$APPS_DIR/coc-donation-bot-stop.desktop" \
  "Stop CoC Donation Bot" \
  "Stop the donation bot (leaves the game running)" \
  "$STOP_EXEC" \
  false

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

echo "Installed launchers:"
echo "  $DESKTOP_DIR/coc-donation-bot.desktop"
echo "  $DESKTOP_DIR/coc-donation-bot-stop.desktop"
echo "  $APPS_DIR/coc-donation-bot.desktop"
echo
echo "Double-click \"CoC Donation Bot\" on the desktop to start."
echo "If Ubuntu asks, choose \"Allow Launching\" / \"Trust and Launch\"."
