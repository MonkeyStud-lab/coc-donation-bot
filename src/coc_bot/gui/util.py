"""Small GUI helpers (terminal launch, script paths)."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

from coc_bot.config import project_root


def calibrate_script() -> Path:
    return project_root() / "scripts" / "calibrate.py"


def install_run_shortcut_script() -> Path:
    return project_root() / "scripts" / "install_run_shortcut.sh"


def install_desktop_shortcut() -> str:
    """Run ``install_run_shortcut.sh``; return the script's stdout message."""
    script = install_run_shortcut_script()
    if not script.is_file():
        raise FileNotFoundError(f"Missing script: {script}")
    result = subprocess.run(  # noqa: S603
        ["bash", str(script)],
        cwd=str(project_root()),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    out = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0:
        raise RuntimeError(out or f"Shortcut install failed (exit {result.returncode})")
    return out or "Desktop shortcut installed."


def open_in_terminal(command: str) -> bool:
    """Run an interactive command in a new terminal window (Linux)."""
    wrapped = f"{command}; echo; read -r -p 'Press Enter to close…'"
    candidates = [
        ["gnome-terminal", "--", "bash", "-lc", wrapped],
        ["kgx", "-e", "bash", "-lc", wrapped],
        ["xfce4-terminal", "-e", f"bash -lc {shlex.quote(wrapped)}"],
        ["konsole", "-e", "bash", "-lc", wrapped],
        ["x-terminal-emulator", "-e", "bash", "-lc", wrapped],
        ["xterm", "-e", "bash", "-lc", wrapped],
    ]
    for argv in candidates:
        if shutil.which(argv[0]) is None:
            continue
        try:
            subprocess.Popen(argv, cwd=str(project_root()))  # noqa: S603
            return True
        except OSError:
            continue
    return False
