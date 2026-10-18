"""Read-only ADB evidence and cgroup-v2 measurements for runtime comparison.

Run on the Linux Android host. Does not launch apps, send input, connect/disconnect
devices, or change settings. Select the cgroup of the Android payload, not its
monitor. CPU 100% means one logical CPU; memory includes reclaimable cache.
"""
import argparse
import datetime
import json
from pathlib import Path
import statistics
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--cgroup", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.seconds < 1 or args.interval <= 0:
        parser.error("seconds and interval must be positive")

    def adb(*command):
        result = subprocess.run(["adb", "-s", args.device, *command],
                                capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))
        return result.stdout

    def shell(command):
        return adb("shell", command).decode(errors="replace").strip()

    def counters(name):
        return dict((k, int(v)) for k, v in
                    (line.split() for line in (args.cgroup / name).read_text().splitlines()))

    if adb("get-state").strip() != b"device":
        raise RuntimeError("Selected ADB target is not online")
    evidence = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "label": args.label, "device": args.device, "cgroup": str(args.cgroup),
        "android": shell("getprop ro.build.version.release"),
        "abis": shell("getprop ro.product.cpu.abilist"),
        "native_bridge": shell("getprop ro.dalvik.vm.native.bridge"),
        "gpu_mode": shell("getprop ro.boot.redroid_gpu_mode"),
        "renderer": [line.strip() for line in shell("dumpsys SurfaceFlinger").splitlines()
                     if "GLES:" in line],
        "display": shell("wm size"),
        "foreground": [line.strip() for line in shell("dumpsys activity activities").splitlines()
                       if "ResumedActivity" in line],
        "game": [line.strip() for line in shell("dumpsys package com.supercell.clashofclans").splitlines()
                 if any(key in line for key in ("versionName=", "versionCode=", "primaryCpuAbi="))],
        "samples": [],
        "scope": "Android payload only; excludes browser, web server, compositor and host services",
    }
    started = previous_time = time.monotonic()
    previous_cpu = counters("cpu.stat")["usage_usec"]
    deadline = started + args.seconds
    while time.monotonic() < deadline:
        time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
        now = time.monotonic()
        cpu = counters("cpu.stat")["usage_usec"]
        memory = counters("memory.stat")
        evidence["samples"].append({
            "elapsed_s": now - started,
            "cpu_one_core_percent": (cpu - previous_cpu) / ((now - previous_time) * 10000),
            "memory_current_mib": int((args.cgroup / "memory.current").read_text()) / 2**20,
            "anon_mib": memory["anon"] / 2**20,
            "file_mib": memory["file"] / 2**20,
        })
        previous_cpu, previous_time = cpu, now
    evidence["duration_s"] = time.monotonic() - started
    evidence["summary"] = {
        key + "_mean": statistics.mean(row[key] for row in evidence["samples"])
        for key in ("cpu_one_core_percent", "memory_current_mib", "anon_mib", "file_mib")
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence["summary"], indent=2))


if __name__ == "__main__":
    main()
