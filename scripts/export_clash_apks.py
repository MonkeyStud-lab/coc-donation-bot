"""Export only installed Clash APKs; never copy account or Android app data."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile


def export(device, destination):
    result = subprocess.run(["adb", "-s", device, "shell", "pm", "path", "com.supercell.clashofclans"],
                            capture_output=True, text=True, timeout=30, check=True)
    paths = [line.removeprefix("package:").strip() for line in result.stdout.splitlines()
             if line.startswith("package:")]
    if not paths or len(paths) > 32 or any(not p.startswith("/data/app/") or not p.endswith(".apk") for p in paths):
        raise ValueError("Could not find installed Clash APK files on the selected device")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        files = []
        for index, path in enumerate(paths):
            target = Path(temp) / f"part-{index:02}.apk"
            subprocess.run(["adb", "-s", device, "pull", path, str(target)], check=True, timeout=90)
            files.append(target)
        staging = Path(temp) / "clash.zip"
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_STORED) as archive:
            for file in files:
                archive.write(file, file.name)
        staging.replace(destination)
    destination.chmod(0o600)
    return {"archive": str(destination), "apk_files": len(files),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output", type=Path, default=Path("clash-apks.zip"))
    args = parser.parse_args()
    print(json.dumps(export(args.device, args.output)))


if __name__ == "__main__":
    main()
