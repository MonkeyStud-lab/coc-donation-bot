"""Small GUI helpers (terminal launch, script paths)."""

from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
from pathlib import Path

from coc_bot.config import project_root


def calibrate_script() -> Path:
    return project_root() / "scripts" / "calibrate.py"


def open_in_terminal(command: str) -> bool:
    """Run an interactive command in a new terminal window."""
    if platform.system() == "Windows":
        # Use cmd /k to open a new terminal and keep it open
        cmd_list = ["cmd", "/k", "title CoC Bot Setup && " + command]
        try:
            subprocess.Popen(cmd_list, cwd=str(project_root()))
            return True
        except OSError:
            return False

    # Linux: try known terminal emulators
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
            subprocess.Popen(argv, cwd=str(project_root()))
            return True
        except OSError:
            continue
    return False
