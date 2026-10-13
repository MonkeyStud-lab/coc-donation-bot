#!/bin/sh
set -eu
# This one-shot service is the only container with host setup privileges.
# It never receives browser commands and exits after installation.
if [ "${COC_SKIP_HOST_SETUP:-0}" = "1" ]; then
    echo "Host setup skipped; existing helper is required."
    exit 0
fi
if [ ! -d /host/run/systemd/system ]; then
    echo "A systemd Linux host is required." >&2
    exit 1
fi
mkdir -p /host/opt/coc-casaos-installer
cp /app/packaging/casaos/install_host.py /host/opt/coc-casaos-installer/
cp /app/packaging/casaos/host_agent.py /host/opt/coc-casaos-installer/
if [ ! -x /host/usr/bin/python3 ]; then
    chroot /host /usr/bin/apt-get update
    chroot /host /usr/bin/apt-get install -y python3
fi
set -- /usr/bin/python3 /opt/coc-casaos-installer/install_host.py
if [ -n "${COC_ADOPT_USER:-}" ]; then
    set -- "$@" --adopt-user "$COC_ADOPT_USER" --display "${COC_WAYLAND_DISPLAY:-wayland-0}"
fi
if [ -n "${COC_IMPORT_PROFILE:-}" ]; then
    set -- "$@" --import-from "$COC_IMPORT_PROFILE"
fi
exec chroot /host "$@"
