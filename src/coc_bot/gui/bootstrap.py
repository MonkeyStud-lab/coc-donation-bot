"""GUI entry with an early splash before heavy imports."""

from __future__ import annotations

import tkinter as tk

from coc_bot.gui.splash import StartupSplash


def run_gui(
    *,
    dry_run: bool = False,
    debug_save_frames: bool = False,
    debug: bool = False,
) -> None:
    """
    Show a loading bar, then open the control window.

    Import-phase splash uses a disposable root that is fully destroyed before
    ``BotControlApp`` is constructed. Leaving that root as tk's default made
    later StringVars (Home chip/timers, Settings entries, Setup/Tools labels)
    attach to a dead window and stop updating.
    """
    boot = tk.Tk()
    boot.withdraw()
    splash = StartupSplash(master=boot)
    try:
        splash.set(0.05, "Starting…")
        splash.set(0.15, "Loading libraries (OpenCV)…")
        # Importing app pulls OpenCV, calibration, and Tools helpers.
        from coc_bot.gui.app import BotControlApp

        splash.set(0.40, "Opening window…")
    finally:
        try:
            splash.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            boot.destroy()
        except Exception:  # noqa: BLE001
            pass
        # Ensure the next Tk() becomes the sole default root.
        try:
            tk._default_root = None  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    app = BotControlApp(
        dry_run=dry_run,
        debug_save_frames=debug_save_frames,
        debug=debug,
        show_startup_splash=True,
    )
    app.mainloop()
