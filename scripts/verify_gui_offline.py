"""Build every page and theme without sending ADB input (use xvfb-run on CI)."""
from pathlib import Path
import sys
from unittest.mock import patch
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coc_bot.gui.app import BotControlApp
from coc_bot.gui.theme import theme_labels, apply_theme


def forbidden(*args, **kwargs):
    raise AssertionError("GUI smoke test attempted ADB input")


with patch("coc_bot.adb.client.AdbClient.run", side_effect=forbidden), \
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
        print("GUI offline: all pages and themes built successfully")
    finally:
        app._destroy_app()
