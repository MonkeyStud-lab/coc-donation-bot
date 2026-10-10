#!/usr/bin/env bash
# One-shot: ensure Linux deps/venv exist, then launch the bot GUI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Setup checks its own fingerprint and skips unchanged installations.
bash "$ROOT/scripts/setup_linux.sh"

chmod +x "$ROOT/scripts/run_bot.sh" 2>/dev/null || true
exec "$ROOT/scripts/run_bot.sh" "$@"
