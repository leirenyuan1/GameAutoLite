"""
模块三: 区域选择器 (overlay_selector.py)
===================================
功能: 全屏弹出半透明遮罩, 供用户用鼠标拖拽划定一个红色矩形,
     系统记录该矩形的绝对坐标并返回.

第三阶段核心演进 (FEAT-01):
  1. 静态底图冻结: 弹出时抓取全屏帧, 消除画面运动干扰;
  2. 原色镂空高亮: 框选区内重绘原色底图, 框选外保留半透明蒙版;
  3. 4倍局部放大镜: 鼠标周围跟随 120x146 放大镜 + 红色十字准星 + 尺寸/坐标 HUD;
  4. 内存直接切图: get_region_with_image 框选完成直接返回切片, 杜绝二次截图.

对外接口:
  - get_region(prompt=None) -> tuple[int, int, int, int] | None
  - get_regions(prompt=None) -> list[tuple[int, int, int, int]] | None
  - get_region_with_image(prompt=None) -> tuple[tuple[int, int, int, int] | None, np.ndarray | None]
"""

from __future__ import annotations

import logging
import cv2
import numpy as np

from PyQt6.QtCore import Qt, QEventLoop, QPoint, QRect
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QCursor, QImage, QPixmap,
)
from PyQt6.QtWidgets import QWidget, QApplication

import image_engine

logger = logging.getLogger(__name__)


class _OverlayWidget(QWidget):
    """全屏半透明遮罩窗口, 内部类, 不对外暴露."""

    def __init__(self, prompt: str | None = None, need_crop: bool = False):
        super().__init__()
        self._prompt = prompt
        self._need_crop = need_crop
        self._cropped_bgr: np.ndarray | None = None

        self._start_pos: QPoint | None = None
        self._end_pos: QPoint | None = None
        self._cursor_pos: QPoint = QPoint(0, 0)
        self._dragging = False
        self._result = None
        self._loop = QEventLoop()

        # ---- 多选模式 ----
        self._multi_mode = False
        self._regions: list[tuple[int, int, int, int]] = []  # 逻辑坐标

        # ---- 全屏静态底图与高 DPI 适配 ----
        self._frozen_bgr: np.ndarray | None = None
        self._bg_pixmap: QPixmap | None = None
        self._init_frozen_background()

        self._init_ui()

    def _init_frozen_background(self) -> None:
        """抓取全屏底图并初始化高分屏 QPixmap (FEAT-01)."""
        try:
            self._frozen_bgr = image_engine.take_screenshot()
            # 转为 RGB 后构建独立拷贝的 QImage
            rgb = cv2.cvtColor(self._frozen_bgr, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
            self._bg_pixmap = QPixmap.fromImage(qimg)
            # 设置 DPI 缩放比，确保在逻辑窗口坐标系下 drawPixmap 1:1 铺满
            ratio = self.devicePixelRatioF()
            self._bg_pixmap.setDevicePixelRatio(ratio)
        except Exception as e:
            logger.warning(f"框选器抓取全屏底图失败，回退普通蒙版: {e}")
            self._frozen_bgr = None
            self._bg_pixmap = None

    def _init_ui(self) -> None:
        """初始化全屏无边框置顶窗口."""
        screen_geom = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geom)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        if self._bg_pixmap is None:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 防止主窗口处于 hide() 不可见状态时，关闭选区遮罩误触发 QApplication 自动退出
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        # 初始化光标逻辑位置
        self._cursor_pos = self.mapFromGlobal(QCursor.pos())

    # ---- 鼠标事件 ----

    def mousePressEvent(self, event) -> None:
        self._start_pos = event.pos()
        self._end_pos = event.pos()
        self._cursor_pos = event.pos()
        self._dragging = True
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self._cursor_pos = event.pos()
        if self._dragging:
            self._end_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._end_pos = event.pos()
            self._cursor_pos = event.pos()
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
            self._cropped_bgr = None
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
        ratio = self.devicePixelRatioF()

        # 1. 底图与半透明蒙版
        if self._bg_pixmap is not None:
            painter.drawPixmap(0, 0, self._bg_pixmap)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        # 2. 顶部居中提示文字
        self._draw_prompt_text(painter)

        # 3. 绘制多选模式下已确认的区域 (镂空原色底图 + 蓝色边框 + 序号)
        if self._multi_mode:
            for i, (x, y, w, h) in enumerate(self._regions):
                if self._bg_pixmap is not None:
                    src_rect = QRect(int(x * ratio), int(y * ratio), int(w * ratio), int(h * ratio))
                    painter.drawPixmap(QRect(x, y, w, h), self._bg_pixmap, src_rect)
                else:
                    painter.fillRect(x, y, w, h, QColor(0, 120, 255, 30))
                painter.setPen(QPen(QColor(0, 120, 255), 2))
                painter.drawRect(x, y, w, h)
                # 序号标签
                painter.setFont(QFont("Microsoft YaHei", 12))
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(x + 4, y + 18, str(i + 1))

        # 4. 当前拖拽矩形 (镂空原色底图 + 红色边框) — 单选/多选通用
        if self._start_pos is not None and self._end_pos is not None:
            x, y, w, h = self._normalized_rect()
            if w > 0 and h > 0:
                if self._bg_pixmap is not None:
                    src_rect = QRect(int(x * ratio), int(y * ratio), int(w * ratio), int(h * ratio))
                    painter.drawPixmap(QRect(x, y, w, h), self._bg_pixmap, src_rect)
                else:
                    painter.fillRect(x, y, w, h, QColor(255, 0, 0, 30))
                pen = QPen(QColor(255, 0, 0), 2)
                painter.setPen(pen)
                painter.drawRect(x, y, w, h)

        # 5. 4倍局部放大镜 (FEAT-01)
        self._draw_magnifier(painter)

    def _draw_prompt_text(self, painter: QPainter) -> None:
        """绘制顶部居中提示文字(白色 + 黑色描边)."""
        if self._prompt:
            text = self._prompt
            if self._multi_mode:
                text += f" (已选 {len(self._regions)} 个)"
        elif self._multi_mode:
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

    def _draw_magnifier(self, painter: QPainter) -> None:
        """绘制 4 倍十字准星放大镜与 HUD (FEAT-01, P1-1, P2-A)."""
        if self._frozen_bgr is None or self._bg_pixmap is None:
            return

        cx = self._cursor_pos.x()
        cy = self._cursor_pos.y()
        win_w = self.width()
        win_h = self.height()

        # 放大镜尺寸: 120 x 146 (120x120 图像 + 120x26 HUD)
        mag_w, mag_h = 120, 146

        # 默认放置在光标右下方 (+20, +20); 靠近右/下边缘时自动翻转
        mag_x = cx + 20
        mag_y = cy + 20
        if mag_x + mag_w > win_w:
            mag_x = cx - mag_w - 20
        if mag_y + mag_h > win_h:
            mag_y = cy - mag_h - 20

        # 四边屏幕 Clamp
        mag_x = max(0, min(mag_x, win_w - mag_w))
        mag_y = max(0, min(mag_y, win_h - mag_h))

        ratio = self.devicePixelRatioF()
        px = int(cx * ratio)
        py = int(cy * ratio)
        img_h, img_w = self._frozen_bgr.shape[:2]

        # 30x30 物理采样窗口 (中心对准光标像素)
        src_x1 = max(0, px - 15)
        src_y1 = max(0, py - 15)
        src_x2 = min(img_w, px + 15)
        src_y2 = min(img_h, py + 15)

        # 目标绘制矩形根据实际裁剪量偏移，保证 (px, py) 100% 居中在 (mag_x + 60, mag_y + 60)
        dst_x = mag_x + (src_x1 - (px - 15)) * 4
        dst_y = mag_y + (src_y1 - (py - 15)) * 4
        dst_w = (src_x2 - src_x1) * 4
        dst_h = (src_y2 - src_y1) * 4

        # 图像区域背景底色
        painter.fillRect(mag_x, mag_y, 120, 120, QColor(0, 0, 0))

        if dst_w > 0 and dst_h > 0:
            painter.drawPixmap(
                QRect(dst_x, dst_y, dst_w, dst_h),
                self._bg_pixmap,
                QRect(src_x1, src_y1, src_x2 - src_x1, src_y2 - src_y1),
            )

        # 图像框边框 (纯白色 1px)
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(mag_x, mag_y, 120, 120)

        # 中心红色十字准星 (长 20px, 宽 1px)
        center_x = mag_x + 60
        center_y = mag_y + 60
        painter.setPen(QPen(QColor(255, 0, 0), 1))
        painter.drawLine(center_x - 10, center_y, center_x + 10, center_y)
        painter.drawLine(center_x, center_y - 10, center_x, center_y + 10)

        # HUD 状态栏 (120 x 26)
        hud_y = mag_y + 120
        painter.fillRect(mag_x, hud_y, 120, 26, QColor(20, 20, 20, 230))
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
        painter.drawRect(mag_x, hud_y, 120, 26)

        # HUD 文本：拖拽时显示当前划定物理尺寸，平时显示当前绝对物理坐标
        if self._dragging and self._start_pos is not None and self._end_pos is not None:
            _, _, w, h = self._normalized_rect()
            hud_text = f"{int(w * ratio)} × {int(h * ratio)}"
        else:
            hud_text = f"({px}, {py})"

        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QRect(mag_x, hud_y, 120, 26), Qt.AlignmentFlag.AlignCenter, hud_text)

    # ---- 内部方法 ----

    def _normalized_rect(self) -> tuple[int, int, int, int]:
        """将起点/终点坐标归一化为标准 (x, y, w, h)."""
        x = min(self._start_pos.x(), self._end_pos.x())
        y = min(self._start_pos.y(), self._end_pos.y())
        w = abs(self._end_pos.x() - self._start_pos.x())
        h = abs(self._end_pos.y() - self._start_pos.y())
        return int(x), int(y), int(w), int(h)

    def _finalize(self) -> None:
        """拖拽结束, 计算最终区域并按需执行内存切片 (FEAT-01). 若 w 或 h < 10 视为误操作."""
        x, y, w, h = self._normalized_rect()
        if w < 10 or h < 10:
            self._result = None
            self._cropped_bgr = None
        else:
            ratio = self.devicePixelRatioF()
            rx = int(x * ratio)
            ry = int(y * ratio)
            rw = int(w * ratio)
            rh = int(h * ratio)
            self._result = (rx, ry, rw, rh)

            if self._need_crop and self._frozen_bgr is not None:
                img_h, img_w = self._frozen_bgr.shape[:2]
                cx1 = max(0, min(rx, img_w))
                cy1 = max(0, min(ry, img_h))
                cx2 = max(0, min(rx + rw, img_w))
                cy2 = max(0, min(ry + rh, img_h))
                if cx2 > cx1 and cy2 > cy1:
                    self._cropped_bgr = self._frozen_bgr[cy1:cy2, cx1:cx2].copy()
                else:
                    self._cropped_bgr = None
            else:
                self._cropped_bgr = None

        self._close_and_exit()

    def _close_and_exit(self) -> None:
        self.hide()
        QApplication.processEvents()
        self.close()
        self._frozen_bgr = None
        self._bg_pixmap = None
        self._loop.quit()

    # ---- 对外暴露的方法 ----

    def run_blocking(self):
        """显示窗口并进入阻塞事件循环, 窗口关闭后返回结果."""
        self.show()
        self.activateWindow()
        self.setFocus()
        self._loop.exec()
        return self._result


def get_region(prompt: str | None = None) -> tuple[int, int, int, int] | None:
    """
    单选模式: 弹出选择窗口, 返回绝对物理矩形 (x, y, w, h) 或 None.
    始终享有底图冻结、选区原色高亮与 4 倍准星放大镜.
    """
    overlay = _OverlayWidget(prompt=prompt, need_crop=False)
    return overlay.run_blocking()


def get_regions(prompt: str | None = None) -> list[tuple[int, int, int, int]] | None:
    """
    多选模式: 连续框选多个区域, Enter 确认, Backspace 回撤, Esc 取消.
    始终享有底图冻结、选区原色高亮与 4 倍准星放大镜.
    """
    overlay = _OverlayWidget(prompt=prompt, need_crop=False)
    overlay._multi_mode = True
    return overlay.run_blocking()


def get_region_with_image(prompt: str | None = None) -> tuple[tuple[int, int, int, int] | None, np.ndarray | None]:
    """
    截图模式: 框选区域的同时从冻结底图直接内存切片返回 (rx, ry, rw, rh), cropped_bgr.
    若用户按 Esc 或无效取消, 返回 (None, None).
    """
    overlay = _OverlayWidget(prompt=prompt, need_crop=True)
    res = overlay.run_blocking()
    if res is None:
        return None, None
    return res, overlay._cropped_bgr
