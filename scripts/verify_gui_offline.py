"""Build every page and theme without sending ADB input (use xvfb-run on CI)."""
from pathlib import Path
from contextlib import contextmanager, ExitStack
import os
import shutil
import sys
import tempfile
import threading
from unittest.mock import patch
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coc_bot.gui.app import BotControlApp
from coc_bot.gui.theme import theme_labels, apply_theme
from coc_bot.control import BotController


@contextmanager
def isolated_data():
    """All config/runtime reads and writes use disposable data, never the user's."""
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="coc-gui-test-") as tmp, ExitStack() as stack:
        root = Path(tmp)
        shutil.copytree(source / "config", root / "config")
        (root / "data").mkdir()
        (root / "data" / "calibrated.yaml").write_text(
            "frame_width: 1853\nframe_height: 1048\nrois:\n  clan_chat: [0, 0, 0.3, 1]\n",
            encoding="utf-8",
        )
        for name in ("coc_bot.config._project_root", "coc_bot.config.project_root",
                     "coc_bot.gui.app.project_root", "coc_bot.gui.calib_backup.project_root"):
            stack.enter_context(patch(name, return_value=root))
        stack.enter_context(patch.dict(os.environ, {
            "COC_BOT_HOME": str(root),
            "COC_BOT_CONFIG": str(root / "data" / "calibrated.yaml"),
            "ADB_DEVICE": "offline-test-device",
        }))
        yield root


def forbidden(*args, **kwargs):
    raise AssertionError("GUI smoke test attempted ADB input")


with isolated_data(), \
     patch("coc_bot.adb.client.AdbClient.run", side_effect=forbidden), \
     patch.object(BotControlApp, "_save_gui_state", return_value=None), \
     patch.object(BotControlApp, "_poll_adb_status", return_value=None):
    app = BotControlApp()
    app.geometry("860x600")
    try:
        for label in theme_labels():
            apply_theme(app, label)
            app._theme_id = label
            app._rebuild_pages_for_theme()
            for page in ("home", "settings", "setup", "library", "tools"):
                app._settings_dirty = False
                app._show_page(page)
                app.update_idletasks()
                assert app._pages[page].winfo_exists()
                # Controls must fit the minimum supported width, even when
                # descriptions are available only as contextual help.
                def check_controls(widget):
                    if widget.winfo_ismapped() and isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox)):
                        assert widget.winfo_rootx() + widget.winfo_width() <= app.winfo_rootx() + app.winfo_width(), widget
                    for child in widget.winfo_children():
                        check_controls(child)
                check_controls(app._pages[page])
            # Tab switches must retain unsaved edits and the same controls.
            app._show_page("settings")
            var = app._setting_vars["farm_interval_seconds"]
            original = var.get()
            var.set("7311")
            for tab in app._settings_notebook.tabs():
                app._settings_notebook.select(tab)
                app.update_idletasks()
                check_controls(app._pages["settings"])
                assert app._setting_vars["farm_interval_seconds"] is var
                assert var.get() == "7311"
            var.set(original)
            assert app._library_buttons
            with patch.object(app, "_farm_oneshot_running", return_value=True):
                app._update_tool_buttons_state()
                for button in (*app._tool_buttons, *app._library_buttons):
                    if not button._allow_while_running:
                        assert str(button.cget("state")) == "disabled"
            app._update_tool_buttons_state()
            app._settings_dirty = False
            app._open_sequence_setup()
            assert app._calib_tree.selection() == ("farm::deploy_sequence",)
            # Developer timing fields remain editable in the compact layout.
            from coc_bot.gui.settings_fields import current_setting_values, SETTINGS
            values = current_setting_values()
            values["gui_dev_options"] = True
            with patch("coc_bot.gui.page_views.current_setting_values", return_value=values):
                app._build_settings_page()
            app._show_page("settings")
            app._settings_notebook.select(3)
            app.update_idletasks()
            check_controls(app._pages["settings"])
            assert set(app._setting_vars) == {field.key for field in SETTINGS}
        # Exercise the actual desktop Start/Stop adapter with a harmless worker.
        class FakeBot:
            def __init__(self):
                self.entered = threading.Event()
                self.release = threading.Event()
            def run(self):
                self.entered.set()
                if not self.release.wait(3):
                    raise TimeoutError("Fake worker did not stop")
            def request_stop(self):
                self.release.set()
        bot = FakeBot()
        app._controller = BotController(lambda options: bot)
        app.start_bot()
        assert bot.entered.wait(3)
        assert app._bot_running()
        assert str(app._start_btn.cget("state")) == "disabled"
        app.stop_bot()
        assert app._controller.wait(3)
        app._poll_controller()
        assert not app._controller_run_pending
        assert str(app._start_btn.cget("state")) == "normal"
        assert str(app._stop_btn.cget("state")) == "disabled"
        # A normal-run completion must not disable Stop for a newer one-shot.
        with patch.object(app, "_farm_oneshot_running", return_value=True):
            app._on_bot_stopped()
            assert str(app._start_btn.cget("state")) == "disabled"
            assert str(app._stop_btn.cget("state")) == "normal"
        app._on_bot_stopped()
        print("GUI offline: all pages/themes and controller Start/Stop passed with isolated data")
    finally:
        app._destroy_app()
