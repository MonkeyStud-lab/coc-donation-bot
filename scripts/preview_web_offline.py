"""Disposable browser QA server. Never connects to Android or uses live data."""
from pathlib import Path
import argparse
import os
import shutil
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
import uvicorn
from coc_bot.config import project_root
from coc_bot.control.lifecycle import BotController
from coc_bot.control.service import ControlService
from coc_bot.web.server import create_app


class FakeBot:
    def __init__(self, options):
        self.cancel = threading.Event()
        self.config = SimpleNamespace(farm_enabled=True)
        self.tracker = SimpleNamespace(seconds_since_last_farm=lambda: 20,
            effective_farm_interval_seconds=lambda: 7200, peek_remaining_seconds=lambda: 14400)
    def run(self):
        self.cancel.wait()
    def request_stop(self):
        self.cancel.set()
    def request_farm_attack(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--origin', action='append')
    args = parser.parse_args()
    if args.host not in ('127.0.0.1', 'localhost', '::1') and not args.origin:
        parser.error('Network testing requires an explicit --origin')
    origins = args.origin or [f'http://127.0.0.1:{args.port}']
    repo = project_root()
    with tempfile.TemporaryDirectory(prefix="coc-web-qa-") as temp:
        root = Path(temp)
        shutil.copytree(repo / "config", root / "config")
        (root / "data").mkdir()
        (root / "data/calibrated.yaml").write_text(
            "frame_width: 1280\nframe_height: 720\nrois:\n  clan_chat: [0, 0, 0.4, 0.8]\n")
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[:] = (40, 70, 40)
        cv2.rectangle(frame, (300, 120), (1000, 580), (220, 220, 220), -1)
        cv2.putText(frame, "OFFLINE TEST IMAGE", (400, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (30, 30, 30), 2)
        def session():
            client = SimpleNamespace(run=lambda args: None)
            return SimpleNamespace(client=client, input=SimpleNamespace(), navigator=SimpleNamespace(),
                attack_nav=SimpleNamespace(), deployer=SimpleNamespace(), app=SimpleNamespace(),
                config=SimpleNamespace(adb_device="offline-browser-qa"),
                capture=SimpleNamespace(screenshot=lambda: frame.copy()),
                prepare_farm_program_deploy=lambda: {"frame": frame.copy()})
        with patch.dict(os.environ, {"COC_BOT_HOME": str(root),
                                    "COC_BOT_CONFIG": str(root / "data/calibrated.yaml")}):
            service = ControlService(BotController(FakeBot), session_factory=session)
            from coc_bot.adb.client import AdbClient
            with patch.object(AdbClient, "run", side_effect=AssertionError("Live ADB forbidden")):
                app = create_app(service, origins=origins)
                print(f"Offline preview at {origins[0]}; opens directly without a password", flush=True)
                uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
