"""GUI entry with an early splash before heavy imports."""

from __future__ import annotations

from typing import Callable

from coc_bot.gui.splash import StartupSplash


def run_gui(
    *,
    dry_run: bool = False,
    debug_save_frames: bool = False,
    debug: bool = False,
) -> None:
    """
    Show a loading bar immediately, then import/build the control window.

    Heavy modules (OpenCV, calibration, Tools) load after the splash is visible.
    """
    splash = StartupSplash()
    progress: Callable[[float, str], None] = splash.set
    try:
        progress(0.05, "Starting…")
        progress(0.12, "Loading libraries (OpenCV)…")
        # Importing app pulls OpenCV, calibration, and Tools helpers.
        from coc_bot.gui.app import BotControlApp

        progress(0.48, "Building control window…")
        app = BotControlApp(
            dry_run=dry_run,
            debug_save_frames=debug_save_frames,
            debug=debug,
            progress=progress,
        )
        progress(1.0, "Ready")
        splash.close()
        app.reveal()
        app.mainloop()
    except Exception:
        splash.close()
        raise
