"""阶段二修复项的无头回归冒烟测试。"""
import os
import tempfile
import unittest
from contextlib import ExitStack
from importlib import import_module
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication


class RefactorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temp_dir = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="gal_refactor_test_"))

        import config_manager
        replacements = {
            "CONFIG_FILE": os.path.join(temp_dir, "config.json"),
            "SCREENSHOTS_DIR": os.path.join(temp_dir, "screenshots"),
            "load_config": Mock(return_value=None),
            "save_config": Mock(),
        }
        for name, value in replacements.items():
            self.stack.enter_context(patch.object(config_manager, name, value))

        from hotkey_manager import HotkeyManager
        for name, value in {
            "register_all": [],
            "unregister_all": None,
            "add_hotkey": True,
            "remove_hotkey": None,
        }.items():
            self.stack.enter_context(patch.object(HotkeyManager, name, return_value=value))

        for module_name in ("pages.stop_conditions_page", "widgets.task_card", "main_window"):
            module = import_module(module_name)
            for name, value in replacements.items():
                if hasattr(module, name):
                    self.stack.enter_context(patch.object(module, name, value))

        from main_window import MainWindow
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_stop_enabled_toggled_signal_handles_both_states(self):
        self.window.chk_stop_enabled.setChecked(True)
        self.assertTrue(self.window.chk_stop_enabled.isChecked())
        self.window.chk_stop_enabled.setChecked(False)
        self.assertFalse(self.window.chk_stop_enabled.isChecked())

    def test_empty_hotkey_list_stays_empty_after_restore(self):
        self.window._settings_page.apply_ui_settings({"hotkeys": []})
        self.assertEqual(self.window._settings_page._hotkeys, [])

    def test_task_card_normalizes_invalid_enabled_and_threshold_values(self):
        card = self.window._task_cards[0]
        card.from_dict({"enabled": None, "threshold": True})
        self.assertTrue(card.chk_enabled.isChecked())
        self.assertEqual(card.slider.value(), 90)

        card.from_dict({"enabled": False, "threshold": float("inf")})
        self.assertFalse(card.chk_enabled.isChecked())
        self.assertEqual(card.slider.value(), 90)

        card.from_dict({"threshold": 0.25})
        self.assertEqual(card.slider.value(), 50)
        card.from_dict({"threshold": 120})
        self.assertEqual(card.slider.value(), 99)

    def test_scheme_image_restore_ignores_non_string_fields(self):
        import config_manager

        task = {"image_filename": [], "image_data": {}, "image_path": ["bad"]}
        self.assertIs(config_manager.restore_task_image(task), task)
        self.assertEqual(task["image_filename"], "")
        self.assertEqual(task["image_data"], "")
        self.assertEqual(task["image_path"], "")
        self.assertIsNone(config_manager.restore_stop_image([], {}, []))

    def test_stats_dialog_tie_breaking_matches_dashboard_rankings(self):
        from pages.dashboard_page import DashboardPage
        from widgets.dashboard_charts import FullTaskStatsDialog

        dashboard = DashboardPage()
        self.addCleanup(dashboard.close)
        stats = {
            "A": {"matches": 4, "clicks": 10, "total_score": 320.0},
            "B": {"matches": 4, "clicks": 10, "total_score": 320.0},
            "C": {"matches": 4, "clicks": 10, "total_score": 360.0},
            "D": {"matches": 6, "clicks": 10, "total_score": 450.0},
            "E": {"matches": 5, "clicks": 12, "total_score": 400.0},
        }
        with patch.object(dashboard, "get_full_stats_snapshot", return_value=("history", stats, 23, 52)):
            dialog = FullTaskStatsDialog(dashboard)
            self.addCleanup(dialog.close)
            read_names = lambda: [dialog.table.item(row, 1).text() for row in range(dialog.table.rowCount())]

            self.assertEqual(read_names(), ["D", "E", "C", "A", "B"])
            dialog.combo_sort.setCurrentIndex(dialog.combo_sort.findData("clicks"))
            self.assertEqual(read_names(), ["E", "D", "A", "B", "C"])

    def test_stats_dialog_sort_combo_ignores_wheel_event(self):
        from pages.dashboard_page import DashboardPage
        from widgets.dashboard_charts import FullTaskStatsDialog

        dashboard = DashboardPage()
        self.addCleanup(dashboard.close)
        with patch.object(dashboard, "get_full_stats_snapshot", return_value=("history", {}, 0, 0)):
            dialog = FullTaskStatsDialog(dashboard)
            self.addCleanup(dialog.close)
            current_index = dialog.combo_sort.currentIndex()

            class FakeWheelEvent:
                ignored = False

                def ignore(self):
                    self.ignored = True

            event = FakeWheelEvent()
            dialog.combo_sort.wheelEvent(event)
            self.assertTrue(event.ignored)
            self.assertEqual(dialog.combo_sort.currentIndex(), current_index)


if __name__ == "__main__":
    unittest.main()
