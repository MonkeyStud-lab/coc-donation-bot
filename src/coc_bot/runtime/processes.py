"""Bounded subprocesses that can be interrupted without leaving children running."""
from __future__ import annotations

import subprocess
import time


class ProcessStopped(RuntimeError):
    pass


def run_process(args, *, timeout=30.0, text=False, stop_check=None):
    if stop_check and stop_check():
        raise ProcessStopped("Stop requested")
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text)
    try:
        while True:
            if stop_check and stop_check():
                raise ProcessStopped("Stop requested")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(.1, remaining))
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
