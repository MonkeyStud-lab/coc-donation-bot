#!/usr/bin/env bash
# Bootstrap everything the bot needs on Ubuntu/Debian Linux:
# apt packages, Python venv + deps, unit data, and troop/spell icons.
#
# Usage:
#   ./scripts/setup_linux.sh           # idempotent; skips work already done
#   ./scripts/setup_linux.sh --force   # reinstall/redownload everything
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FORCE=0
SKIP_ICONS=0
SKIP_APT=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --skip-icons) SKIP_ICONS=1 ;;
    --skip-apt) SKIP_APT=1 ;;
    -h|--help)
      echo "Usage: $0 [--force] [--skip-icons] [--skip-apt]"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

STAMP="$ROOT/.setup_linux_stamp"
VENV_PY="$ROOT/.venv/bin/python"
ICONS_DIR="$ROOT/data/icons"

log() { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This setup script is for Linux (Ubuntu/Debian) hosts." >&2
  exit 1
fi

if [[ ! -f /etc/debian_version ]] && [[ ! -f /etc/lsb-release ]]; then
  warn "Non-Debian Linux detected — apt package install may fail; continuing best-effort."
fi

need_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    return 1
  fi
  return 0
}

run_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Need root to install packages, but sudo is unavailable." >&2
    exit 1
  fi
}

APT_PACKAGES=(
  android-tools-adb
  curl
  libgl1
  libglib2.0-0
  libnotify-bin
  python3
  python3-pip
  python3-tk
  python3-venv
  tesseract-ocr
)

stamp_fingerprint() {
  # Rebuild if pyproject or setup script changes.
  local pyproject_hash setup_hash
  pyproject_hash="$(cksum "$ROOT/pyproject.toml" 2>/dev/null | awk '{print $1}')"
  setup_hash="$(cksum "$ROOT/scripts/setup_linux.sh" 2>/dev/null | awk '{print $1}')"
  printf 'pyproject=%s setup=%s\n' "$pyproject_hash" "$setup_hash"
}

setup_complete() {
  [[ "$FORCE" -eq 1 ]] && return 1
  [[ -x "$VENV_PY" ]] || return 1
  [[ -f "$STAMP" ]] || return 1
  [[ "$(cat "$STAMP" 2>/dev/null || true)" == "$(stamp_fingerprint)" ]] || return 1
  # Icons are optional for basic donate, but we treat them as part of full setup.
  if [[ "$SKIP_ICONS" -eq 0 ]]; then
    [[ -d "$ICONS_DIR" ]] || return 1
    local icon_count
    icon_count="$(find "$ICONS_DIR" -type f \( -name '*.webp' -o -name '*.png' \) 2>/dev/null | wc -l | tr -d ' ')"
    [[ "${icon_count:-0}" -gt 0 ]]
  fi
}

if setup_complete; then
  log "Linux setup already complete — skipping (use --force to redo)"
  exit 0
fi

# --- apt packages ---
if [[ "$SKIP_APT" -eq 0 ]]; then
  log "Installing system packages (may ask for your password)…"
  export DEBIAN_FRONTEND=noninteractive
  run_root apt-get update -y
  run_root apt-get install -y "${APT_PACKAGES[@]}"
else
  log "Skipping apt packages (--skip-apt)"
fi

command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required but not installed." >&2
  exit 1
}
command -v adb >/dev/null 2>&1 || warn "adb still missing after apt install"

# --- Python venv + project deps ---
if [[ "$FORCE" -eq 1 ]] || [[ ! -x "$VENV_PY" ]]; then
  log "Creating Python virtualenv…"
  python3 -m venv "$ROOT/.venv"
fi

log "Installing Python packages into .venv (EasyOCR/torch can take several minutes)…"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e "$ROOT"

# Warm EasyOCR model download so first bot run is not stuck downloading quietly.
log "Preloading EasyOCR English model (first time can take 1–3 minutes)…"
python - <<'PY' || warn "EasyOCR preload failed — bot can still run; capacity OCR may download later"
import easyocr
easyocr.Reader(["en"], gpu=False, verbose=False)
print("EasyOCR model ready")
PY

# --- Game data + icons ---
log "Syncing unit housing data…"
if ! python "$ROOT/scripts/sync_game_data.py" --force; then
  warn "Unit data sync had warnings — bundled seed in data/game/units.yaml will be used if present"
fi

if [[ "$SKIP_ICONS" -eq 0 ]]; then
  log "Downloading unit icons…"
  if ! python "$ROOT/scripts/sync_game_data.py" --icons-only --force; then
    warn "Icon download had issues — open-request icon matching may be limited"
  fi
else
  log "Skipping icon download (--skip-icons)"
fi

stamp_fingerprint >"$STAMP"
log "Linux setup finished."
log "Next: calibrate once if needed, then install the desktop icon:"
log "  python scripts/calibrate.py"
log "  ./scripts/install_desktop_launcher.sh"
echo
log "Note: Waydroid + Clash of Clans must already be installed separately."
