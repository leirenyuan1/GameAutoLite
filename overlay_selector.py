"""
模块三: 区域选择器 (overlay_selector.py)
===================================
功能: 全屏弹出半透明遮罩, 供用户用鼠标拖拽划定一个红色矩形,
     系统记录该矩形的绝对坐标并返回.

对外接口:
  - get_region() -> tuple[int, int, int, int] | None
    阻塞调用, 弹出选择窗口, 等待用户操作完成后返回结果.
    返回 (x, y, w, h) 或 None(用户取消时).

  - get_regions() -> list[tuple[int, int, int, int]] | None
    多选模式: 连续框选多个区域, Enter 确认, Backspace 回撤, Esc 取消.
"""

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QEventLoop, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QFont


class _OverlayWidget(QWidget):
    """全屏半透明遮罩窗口, 内部类, 不对外暴露."""

    def __init__(self):
        super().__init__()
        self._start_pos: QPoint | None = None
        self._end_pos: QPoint | None = None
        self._dragging = False
        self._result = None
        self._loop = QEventLoop()
        # ---- 多选模式 ----
        self._multi_mode = False
        self._regions: list[tuple[int, int, int, int]] = []  # 逻辑坐标
        self._init_ui()

    def _init_ui(self) -> None:
        """初始化全屏无边框置顶窗口."""
        screen_geom = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geom)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ---- 鼠标事件 ----

    def mousePressEvent(self, event) -> None:
        self._start_pos = event.pos()
        self._end_pos = event.pos()
        self._dragging = True

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._end_pos = event.pos()
        self._dragging = False
        if self._multi_mode:
            # 多选: 将当前区域加入列表, 重置拖拽状态, 继续框选
            x, y, w, h = self._normalized_rect()
            if w >= 10 and h >= 10:
                self._regions.append((x, y, w, h))
            self._start_pos = None
            self._end_pos = None
            self.update()
        else:
            self._finalize()

    # ---- 键盘事件 ----

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._result = None
            self._close_and_exit()
        elif self._multi_mode and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._regions:
                ratio = self.devicePixelRatioF()
                self._result = [
                    (int(x * ratio), int(y * ratio), int(w * ratio), int(h * ratio))
                    for x, y, w, h in self._regions
                ]
            else:
                self._result = None
            self._close_and_exit()
        elif self._multi_mode and key == Qt.Key.Key_Backspace:
            if self._regions:
                self._regions.pop()
                self.update()

    # ---- 关闭事件 ----

    def closeEvent(self, event) -> None:
        self._loop.quit()
        super().closeEvent(event)

    # ---- 绘制 ----

    def paintEvent(self, event) -> None:
        painter = QPainter(self)

        # 半透明黑色蒙版 (rgba 0,0,0,100 ≈ 40% opacity)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        # 顶部居中提示文字, 白色带黑色描边
        self._draw_prompt_text(painter)

        if self._multi_mode:
            # 绘制已确认的区域 (蓝色填充 + 边框 + 序号)
            for i, (x, y, w, h) in enumerate(self._regions):
                painter.fillRect(x, y, w, h, QColor(0, 120, 255, 30))
                painter.setPen(QPen(QColor(0, 120, 255), 2))
                painter.drawRect(x, y, w, h)
                # 序号标签
                painter.setFont(QFont("Microsoft YaHei", 12))
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(x + 4, y + 18, str(i + 1))

        # 当前拖拽矩形 (红色) — 单选/多选通用
        if self._start_pos is not None and self._end_pos is not None:
            x, y, w, h = self._normalized_rect()
            # 内部填充: 半透明红色
            painter.fillRect(x, y, w, h, QColor(255, 0, 0, 30))
            # 描边: 纯红色, 线宽 2px
            pen = QPen(QColor(255, 0, 0), 2)
            painter.setPen(pen)
            painter.drawRect(x, y, w, h)

    def _draw_prompt_text(self, painter: QPainter) -> None:
        """绘制顶部居中提示文字(白色 + 黑色描边)."""
        if self._multi_mode:
            count = len(self._regions)
            text = f"拖拽框选区域 | Enter 确认 | Backspace 回撤 | Esc 取消 (已选 {count} 个)"
        else:
            text = "拖拽鼠标划定点击区域, 按 Esc 取消"
        font = QFont("Microsoft YaHei", 16)
        painter.setFont(font)

        text_rect = self.rect()
        text_rect.setTop(40)
        text_rect.setHeight(60)

        flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop

        # 黑色描边: 先绘制略粗的黑色文字作为背景描边
        painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
        painter.drawText(text_rect, flags, text)
        # 白色文字: 覆盖在上层
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(text_rect, flags, text)

    # ---- 内部方法 ----

    def _normalized_rect(self) -> tuple[int, int, int, int]:
        """将起点/终点坐标归一化为标准 (x, y, w, h)."""
        x = min(self._start_pos.x(), self._end_pos.x())
        y = min(self._start_pos.y(), self._end_pos.y())
        w = abs(self._end_pos.x() - self._start_pos.x())
        h = abs(self._end_pos.y() - self._start_pos.y())
        return int(x), int(y), int(w), int(h)

    def _finalize(self) -> None:
        """拖拽结束, 计算最终区域. 若 w 或 h < 10 视为误操作."""
        x, y, w, h = self._normalized_rect()
        if w < 10 or h < 10:
            self._result = None
        else:
            ratio = self.devicePixelRatioF()
            self._result = (int(x * ratio), int(y * ratio), int(w * ratio), int(h * ratio))
        self._close_and_exit()

    def _close_and_exit(self) -> None:
        self.close()
        self._loop.quit()

    # ---- 对外暴露的方法 ----

    def run_blocking(self):
        """显示窗口并进入阻塞事件循环, 窗口关闭后返回结果."""
        self.show()
        self.activateWindow()
        self.setFocus()
        self._loop.exec()
        return self._result


def get_region() -> tuple[int, int, int, int] | None:
    """
    阻塞调用, 弹出选择窗口, 等待用户操作完成后返回结果.
    返回 (x, y, w, h) 或 None(用户取消时).
    内部使用独立 QEventLoop 实现阻塞等待.
    """
    overlay = _OverlayWidget()
    return overlay.run_blocking()


def get_regions() -> list[tuple[int, int, int, int]] | None:
    """
    多选模式: 连续框选多个区域, Enter 确认, Backspace 回撤, Esc 取消.
    返回区域列表或 None(用户取消时).
    """
    overlay = _OverlayWidget()
    overlay._multi_mode = True
    return overlay.run_blocking()
