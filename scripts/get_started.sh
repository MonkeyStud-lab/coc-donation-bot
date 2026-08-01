#!/usr/bin/env bash
# One-shot: ensure Linux deps/venv exist, then launch the bot GUI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]] || [[ ! -f "$ROOT/.setup_linux_stamp" ]]; then
  echo "==> Running first-time setup (may ask for your password)…"
  chmod +x "$ROOT/scripts/setup_linux.sh"
  "$ROOT/scripts/setup_linux.sh"
fi

chmod +x "$ROOT/scripts/run_bot.sh" 2>/dev/null || true
exec "$ROOT/scripts/run_bot.sh"
