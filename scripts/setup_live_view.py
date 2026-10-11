"""Download and verify the optional, pinned upstream scrcpy Android server."""
import hashlib
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coc_bot.web.live import server_path, SERVER_URL, SERVER_SHA256


def main():
    destination = server_path()
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == SERVER_SHA256:
        print("Live view server already installed.")
        return
    with urllib.request.urlopen(SERVER_URL, timeout=30) as response:
        data = response.read(2 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != SERVER_SHA256:
        raise RuntimeError("scrcpy download checksum mismatch; nothing installed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".download")
    temporary.write_bytes(data)
    temporary.replace(destination)
    print("Live view server installed:", destination)


if __name__ == "__main__":
    main()
