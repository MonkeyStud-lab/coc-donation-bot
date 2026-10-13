#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
docker build -f "$root/packaging/casaos/Dockerfile" -t "${COC_IMAGE:-coc-bot-casaos:local}" "$root"
