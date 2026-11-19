from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget


class MatchHighlightOverlay(QWidget):
    """测试识别匹配结果全屏透明高亮框 (FEAT-02)"""

    def __init__(
        self,
        task_name: str,
        score_pct: float,
        passed: bool,
        rx: int,
        ry: int,
        rw: int,
        rh: int,
        parent=None,
    ):
        super().__init__(parent)
        self._task_name = task_name
        self._score_pct = score_pct
        self._passed = passed
        self._tag_bg_color = QColor("#43A047") if passed else QColor("#FF9800")
        self._rx, self._ry, self._rw, self._rh = rx, ry, rw, rh
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)

        ratio = self.devicePixelRatioF()
        lx, ly = int(self._rx / ratio), int(self._ry / ratio)
        lw, lh = max(1, int(self._rw / ratio)), max(1, int(self._rh / ratio))
        self._lx, self._ly, self._lw, self._lh = lx, ly, lw, lh

        pad_x = 4
        pad_top = 28
        win_w = max(lw + pad_x * 2, 160)
        win_h = lh + pad_top + 4

        screen = QApplication.primaryScreen().geometry()
        tag_below = (ly < pad_top)
        self._tag_below = tag_below
        win_y = ly if tag_below else (ly - pad_top)
        win_x = max(0, min(lx - pad_x, screen.width() - win_w))
        win_y = max(0, min(win_y, screen.height() - win_h))
        self.setGeometry(win_x, win_y, win_w, win_h)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        win_x = self.x()
        win_y = self.y()
        target_x = self._lx - win_x
        target_y = self._ly - win_y
        lw, lh = self._lw, self._lh

        # 1. 目标框体 (消除边缘 Clamp 平移错位)
        painter.setPen(QPen(self._tag_bg_color, 2, Qt.PenStyle.SolidLine if self._passed else Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(target_x, target_y, lw, lh), 2.5, 2.5)

        # 2. 胶囊标签 (固定字体，长任务名自适应省略与截断保护)
        painter.setFont(QFont("Microsoft YaHei", 9))
        fm = painter.fontMetrics()
        win_w = self.width()
        win_h = self.height()
        max_tag_w = max(60, win_w - 8)
        elided_name = fm.elidedText(self._task_name, Qt.TextElideMode.ElideRight, max(30, max_tag_w - 55))
        raw_tag = f"{elided_name} · {self._score_pct:.1f}%" if self._passed else f"未达标 · 最高 {self._score_pct:.1f}%"
        tag_text = fm.elidedText(raw_tag, Qt.TextElideMode.ElideRight, max_tag_w - 12)
        tag_w = min(max_tag_w, fm.horizontalAdvance(tag_text) + 14)
        tag_h = 22

        # 3. 标签坐标安全 clamp
        tag_x = max(2, min(target_x, win_w - tag_w - 2))
        if self._tag_below:
            tag_y = min(win_h - tag_h - 2, target_y + lh + 4)
        else:
            tag_y = max(2, target_y - tag_h - 4)

        # 4. 绘制圆角胶囊背景与文字
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._tag_bg_color)
        painter.drawRoundedRect(QRectF(tag_x, tag_y, tag_w, tag_h), 4.0, 4.0)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(tag_x, tag_y, tag_w, tag_h), Qt.AlignmentFlag.AlignCenter, tag_text)
