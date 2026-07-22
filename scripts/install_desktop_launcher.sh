#!/usr/bin/env bash
# Install a single clickable desktop icon that opens the bot control GUI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_SRC="$ROOT/desktop/coc-donation-bot.svg"
VENV_PY="$ROOT/.venv/bin/python"

chmod +x \
  "$ROOT/scripts/setup_linux.sh" \
  "$ROOT/scripts/start_bot_desktop.sh" \
  "$ROOT/scripts/stop_bot_desktop.sh" \
  "$ROOT/scripts/bot_gui.py" \
  "$ROOT/scripts/install_desktop_launcher.sh"

echo "==> Ensuring Linux dependencies are installed…"
"$ROOT/scripts/setup_linux.sh"

mkdir -p "$DESKTOP_DIR" "$APPS_DIR"

# Remove the old separate Stop icon if present.
rm -f \
  "$DESKTOP_DIR/coc-donation-bot-stop.desktop" \
  "$APPS_DIR/coc-donation-bot-stop.desktop"

write_desktop() {
  local out="$1"
  cat >"$out" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=CoC Donation Bot
Comment=Open the donation bot control window (start + shutoff)
Exec=$VENV_PY $ROOT/scripts/bot_gui.py
Icon=$ICON_SRC
Path=$ROOT
Terminal=false
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

echo "Installed launcher:"
echo "  $DESKTOP_DIR/coc-donation-bot.desktop"
echo
echo "Double-click \"CoC Donation Bot\" — a window opens with Shut off."
echo "If Ubuntu asks, choose \"Allow Launching\" / \"Trust and Launch\"."
echo "You can delete any leftover \"Stop CoC Donation Bot\" icon."
