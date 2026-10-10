"""Build every page and theme without sending ADB input (use xvfb-run on CI)."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coc_bot.gui.app import BotControlApp
from coc_bot.gui.theme import theme_labels, apply_theme


def forbidden(*args, **kwargs):
    raise AssertionError("GUI smoke test attempted ADB input")


with patch("coc_bot.adb.client.AdbClient.run", side_effect=forbidden), \
     patch.object(BotControlApp, "_poll_adb_status", return_value=None):
    app = BotControlApp()
    app.withdraw()
    try:
        for label in theme_labels():
            apply_theme(app, label)
            app._theme_id = label
            app._rebuild_pages_for_theme()
            for page in ("home", "settings", "setup", "tools"):
                app._settings_dirty = False
                app._show_page(page)
                app.update_idletasks()
                assert app._pages[page].winfo_exists()
        print("GUI offline: all pages and themes built successfully")
    finally:
        app._destroy_app()
