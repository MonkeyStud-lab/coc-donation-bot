#!/usr/bin/env bash
# Open from a desktop shortcut or run: ./scripts/run_bot.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Missing .venv — run: ./scripts/setup_linux.sh"
  read -r -p "Press Enter to close…"
  exit 1
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
exec python -m coc_bot.main
