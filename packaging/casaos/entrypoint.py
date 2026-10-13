"""Initialize empty storage without replacing any existing user files."""
import os
from pathlib import Path
import shutil
import socket
import json
import sys


def seed(source, target):
    if source.is_dir():
        for file in source.rglob("*"):
            if file.is_file():
                seed(file, target / file.relative_to(source))
    elif not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def main():
    profile = Path(os.environ.get("COC_BOT_HOME", "/profile"))
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)
    app = Path("/app")
    for name in ("config", "data/game", "data/live"):
        seed(app / name, profile / name)
    (profile / "data").mkdir(parents=True, exist_ok=True)
    host = os.environ.get("COC_WEB_HOST", "auto")
    if host == "auto":
        # Route lookup only: UDP connect does not send a packet.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            host = probe.getsockname()[0]
    port = os.environ.get("COC_WEB_PORT", "8767")
    origin = os.environ.get("COC_WEB_ORIGIN") or f"http://{host}:{port}"
    Path("/tmp/coc-web-address.json").write_text(json.dumps({"url": f"http://{host}:{port}"}))
    os.execv(sys.executable, [sys.executable, "-m", "coc_bot.web", "--host", host, "--port", port,
                            "--origin", origin])


if __name__ == "__main__":
    main()
