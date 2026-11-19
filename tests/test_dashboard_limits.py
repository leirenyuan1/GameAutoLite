"""第二阶段看板限高、全量明细和弹窗生命周期隔离回归。"""
import os
import tempfile
import unittest
from contextlib import ExitStack
from importlib import import_module
from unittest.mock import Mock, patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtCore import Qt, QCoreApplication, QEvent, QPoint
from PyQt6.QtGui import QColor, QFontMetrics, QImage
from PyQt6.QtWidgets import QApplication, QLabel, QProgressBar


class DashboardLimitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        tmp = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='gal_dashboard_test_'))
        import config_manager
        replacements = dict(CONFIG_FILE=os.path.join(tmp, 'config.json'),
                            SCREENSHOTS_DIR=os.path.join(tmp, 'screenshots'),
                            load_config=Mock(return_value=None), save_config=Mock())
        for name, value in replacements.items():
            self.stack.enter_context(patch.object(config_manager, name, value))
        from hotkey_manager import HotkeyManager
        for name, value in dict(register_all=[], unregister_all=None, add_hotkey=True,
                                remove_hotkey=None).items():
            self.stack.enter_context(patch.object(HotkeyManager, name, return_value=value))
        for name in ('pages.stop_conditions_page', 'widgets.task_card', 'main_window'):
            module = import_module(name)
            for field, value in replacements.items():
                if hasattr(module, field):
                    self.stack.enter_context(patch.object(module, field, value))
        from pages.dashboard_page import DashboardPage
        self.d = DashboardPage()

    def tearDown(self):
        self.d.close()
        self.d.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def fill(self, n, mode='history'):
        stats = {f'T{i:03}': dict(matches=i+1, clicks=(i+1)*2,
                               total_score=(i+1)*(70.0+i/10)) for i in range(n)}
        total_m = sum(s['matches'] for s in stats.values())
        total_c = sum(s['clicks'] for s in stats.values())
        if mode == 'history':
            self.d.load_stats_history(dict(task_stats=stats, total_matches=total_m,
                                          total_clicks=total_c))
        else:
            self.d._session.update(task_stats=stats, matches=total_m, clicks=total_c)
        self.d._on_mode_switched(mode)
        return stats

    def test_thresholds_and_history_all_retained(self):
        for n in (0, 1, 5, 6, 7, 150):
            with self.subTest(n=n):
                stats = self.fill(n)
                self.assertEqual(self.d.rank_container.count(), max(1, min(n, 6)))
                self.assertEqual(self.d.hist_clicks_container.count(), max(1, min(n, 6)))
                self.assertEqual(self.d.btn_rank_all.isHidden(), n <= 6)
                self.assertEqual(self.d.btn_hist_clicks_all.isHidden(), n <= 6)
                self.assertEqual(self.d.export_stats_history()['task_stats'], stats)
                if n > 6:
                    self.assertEqual(self.d.btn_rank_all.text(), f'查看全部 ({n})')
                    self.assertIn(
                        f'其余 {n-5} 项',
                        self.d.rank_container.itemAt(5).widget().property('_dashboard_tooltip_text'),
                    )

    def test_session_also_collapses_without_mutating_model(self):
        stats = self.fill(150, 'session')
        self.assertEqual(self.d.rank_container.count(), 6)
        self.assertEqual(self.d._session['task_stats'], stats)
        session_row = self.d.rank_container.itemAt(0).widget()
        self.assertTrue(session_row.toolTip())
        self.assertIsNone(session_row.property('_dashboard_tooltip_text'))

    def test_aggregate_counts_weighted_score_and_percentages(self):
        stats = self.fill(10)
        rest = list(stats.values())[:5]
        rest_m = sum(s['matches'] for s in rest)
        rest_c = sum(s['clicks'] for s in rest)
        avg = sum(s['total_score'] for s in rest) / rest_m
        labels = self.d.rank_container.itemAt(5).widget().findChildren(QLabel)
        self.assertEqual(labels[-1].text(), f'{rest_m}次 ({rest_m/55*100:.0f}%) · 均分{avg:.0f}%')
        self.assertIn(
            f'{rest_c:,} 次',
            self.d.hist_clicks_container.itemAt(5).widget().property('_dashboard_tooltip_text'),
        )
        bars = [self.d.rank_container.itemAt(i).widget().findChild(QProgressBar).value() for i in range(6)]
        self.assertLessEqual(abs(sum(bars)-1000), 6)

    def test_denominators_choose_max_of_totals_and_task_sum(self):
        self.fill(2)
        self.d._history.update(total_matches=100, total_clicks=200)
        self.d._update_ui_display()
        self.assertIn('(2%)', self.d.rank_container.itemAt(0).widget().findChildren(QLabel)[-1].text())
        self.assertEqual(self.d.get_full_stats_snapshot()[2:], (100, 200))
        self.d._history.update(total_matches=0, total_clicks=0)
        self.assertEqual(self.d.get_full_stats_snapshot()[2:], (3, 6))

    def test_public_snapshots_do_not_allow_model_mutation(self):
        self.fill(150)
        snapshot = self.d.get_full_stats_snapshot()[1]
        snapshot['T000']['matches'] = 999
        self.assertEqual(self.d._history['task_stats']['T000']['matches'], 1)
        self.assertIsNot(self.d.get_scatter_snapshot()[1], self.d._scatter_points)

    def test_dialog_four_sorts_search_true_rank_and_focus(self):
        from widgets.dashboard_charts import FullTaskStatsDialog
        self.d._history.update(task_stats={
            'Many': dict(matches=10, clicks=10, total_score=500),
            'Clicks': dict(matches=2, clicks=20, total_score=120),
            'Score': dict(matches=1, clicks=1, total_score=99),
            'Ratio': dict(matches=1, clicks=15, total_score=80),
        }, total_matches=14, total_clicks=46)
        self.d._on_mode_switched('history')
        dialog = FullTaskStatsDialog(self.d)
        for index, name in enumerate(('Many', 'Clicks', 'Score', 'Ratio')):
            dialog.combo_sort.setCurrentIndex(index)
            self.assertEqual(dialog.table.item(0, 1).text(), name)
            dialog.refresh_data()
            self.assertEqual(dialog.combo_sort.currentIndex(), index)
        dialog.refresh_data(focus='matches')
        dialog.edit_search.setText('  sCoRe  ')
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 0).text(), '3')
        self.assertEqual(dialog.table.columnCount(), 8)
        self.assertIn('共 4 项 · 当前显示 1 项', dialog.lbl_summary.text())
        dialog.close()

    def test_dialog_click_only_and_zero_denominators(self):
        from widgets.dashboard_charts import FullTaskStatsDialog
        stats = {'ClickOnly': dict(matches=0, clicks=3), 'Empty': dict(matches=0, clicks=0), 'Bad': None}
        with patch.object(self.d, 'get_full_stats_snapshot', return_value=('history', stats, 0, 0)):
            dialog = FullTaskStatsDialog(self.d)
            self.assertEqual(dialog.table.rowCount(), 1)
            for col in (3, 4, 6):
                self.assertEqual(dialog.table.item(0, col).text(), '0.0%')
            self.assertEqual(dialog.table.item(0, 7).text(), '0.00')
            dialog.close()

    def test_dialog_singleton_lifecycle_and_resize_not_refresh(self):
        self.fill(150)
        self.d._open_stats_dialog('matches')
        dialog = self.d._stats_dialog
        self.assertFalse(dialog.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose))
        self.assertTrue(dialog.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))
        self.d._open_stats_dialog('clicks')
        self.assertIs(self.d._stats_dialog, dialog)
        self.assertEqual(dialog.combo_sort.currentData(), 'clicks')
        with patch.object(dialog, 'refresh_data', wraps=dialog.refresh_data) as refresh:
            self.d._update_history_clicks_display()
            refresh.assert_not_called()
            self.d._update_rank_display()
            refresh.assert_called_once()
        dialog.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertIsNone(self.d._stats_dialog)

    def test_rank_large_numbers_and_420px_history_layout(self):
        self.fill(7)
        self.d._history['task_stats']['T006'].update(matches=999999, clicks=999999,
                                                  total_score=89999910)
        self.d._history.update(total_matches=0, total_clicks=0)
        self.d.resize(420, 800)
        self.d.show()
        self.app.processEvents()
        self.d._update_ui_display()
        label = self.d.rank_container.itemAt(0).widget().findChildren(QLabel)[-1]
        self.assertGreaterEqual(label.minimumWidth(), QFontMetrics(label.font()).horizontalAdvance(label.text()))
        self.assertEqual(label.maximumWidth(), 16777215)
        self.assertLessEqual(self.d.widget().width(), self.d.viewport().width())
        self.assertLessEqual(abs(self.d.card_hist_clicks.width()-self.d.card_hist_guide.width()), 1)

    def test_rank_tooltip_uses_custom_white_painted_window(self):
        self.fill(7)
        row = self.d.rank_container.itemAt(0).widget()
        expected = row.property('_dashboard_tooltip_text')
        self.assertTrue(expected.startswith('T006: 触发'))
        self.assertEqual(row.toolTip(), '')

        tooltip = self.d._rank_tooltip_controller._tooltip
        self.d.show()
        self.app.processEvents()
        QCoreApplication.sendEvent(row, QEvent(QEvent.Type.Enter))
        self.app.processEvents()
        self.assertTrue(tooltip.isVisible())
        self.assertEqual(tooltip._text, expected)
        tooltip.show_text(expected, QPoint(100, 100))
        self.app.processEvents()
        image = QImage(tooltip.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor('#000000'))
        tooltip.render(image)
        self.assertEqual(image.pixelColor(tooltip.width() - 5, tooltip.height() // 2), QColor('#FFFFFF'))
        self.d._rank_tooltip_controller.hide()


if __name__ == '__main__':
    unittest.main()
