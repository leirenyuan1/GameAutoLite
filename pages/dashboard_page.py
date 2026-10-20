"""
数据看板页面 (pages/dashboard_page.py)
=====================================
生产级工业加固版本：
1. 折线图与流水列表排版安全无裁切 (136px 固定高度 / 22px item sizeHint / 水平滚动条关闭 / X 轴限位居中);
2. 历史执行流水闭环持久化与双模式解耦 (确立「历史 = 已结算」架构原则，最新在前，停机合并，占位符互斥);
3. 高分屏 (2880×1800@200% DPI) 全屏物理像素映射与 Letterbox 居中等比视口防形变;
4. 独立高清大图弹窗 ClickScatterDialog (单例管理、最大化支持、Tooltip 精确探测与全生命周期清理);
5. 损坏配置早退保护与多维度原子重置。
"""

from __future__ import annotations

import collections
import copy
import logging
import os
import subprocess
import time
from dataclasses import dataclass

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QToolTip, QVBoxLayout, QWidget,
)

from pages.utils import make_settings_card
from styles.colors import (
    CLR_BTN_PRIMARY, CLR_CARD_BG, CLR_CARD_BORDER,
    CLR_CONTENT_BG, CLR_SIDEBAR_ACT, CLR_TEXT_MAIN, CLR_TEXT_SUB,
)
from styles.icons import button_icon, set_label_icon

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# 1. 核心数据结构定义
# ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ScatterPoint:
    """点击物理落点数据结构 (全屏物理坐标与归一化坐标)."""
    nx: float          # 全屏归一化 X (0.0 ~ 1.0, 经过 clamp)
    ny: float          # 全屏归一化 Y (0.0 ~ 1.0, 经过 clamp)
    tx: int            # 真实物理像素 X (如 241)
    ty: int            # 真实物理像素 Y (如 795)
    task_name: str     # 触发该点击的任务名
    timestamp_str: str # 触发时间戳 (如 "05:04:09")


# ------------------------------------------------------------
# 2. 坐标与视口纯函数定义
# ------------------------------------------------------------
def get_primary_screen_physical_size() -> tuple[int, int]:
    """获取主屏物理像素尺寸 (sw_px, sh_px)，严格返回 2 元组，杜绝解包报错."""
    screen = QApplication.primaryScreen()
    if not screen:
        return (1920, 1080)
    geom = screen.geometry()
    dpr = screen.devicePixelRatio()
    sw = int(round(geom.width() * dpr))
    sh = int(round(geom.height() * dpr))
    return (max(1, sw), max(1, sh))


def normalize_click_physical(tx: int, ty: int, sw_px: int, sh_px: int) -> tuple[float, float]:
    """物理像素归一化，严密 clamp 在 [0.0, 1.0]，内部防除零."""
    nx = min(1.0, max(0.0, float(tx) / max(1, float(sw_px))))
    ny = min(1.0, max(0.0, float(ty) / max(1, float(sh_px))))
    return (nx, ny)


def fit_letterbox_rect(avail_w: int, avail_h: int, target_w: int, target_h: int, pad: int = 12) -> tuple[int, int, int, int]:
    """在可用空间内计算保持 target_w:target_h 宽高比的最大居中矩形 (x, y, w, h)."""
    max_w = max(10, avail_w - pad * 2)
    max_h = max(10, avail_h - pad * 2)
    scale = min(max_w / float(target_w), max_h / float(target_h))
    fit_w = int(round(target_w * scale))
    fit_h = int(round(target_h * scale))
    fit_x = pad + (max_w - fit_w) // 2
    fit_y = pad + (max_h - fit_h) // 2
    return (fit_x, fit_y, fit_w, fit_h)


class _DashboardCard(QFrame):
    """看板卡片容器：允许水平自适应收缩至 550px 极窄视口 (420px 零溢出)."""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())


_dashboard_card_counter = 0


def make_dashboard_card(title_text: str) -> tuple[_DashboardCard, QVBoxLayout]:
    """创建支持窄窗口自适应收缩的分组卡片."""
    global _dashboard_card_counter
    _dashboard_card_counter += 1
    card_id = f"dashboard_card_{_dashboard_card_counter}"

    card = _DashboardCard()
    card.setObjectName(card_id)
    card.setStyleSheet(f"""
        #{card_id} {{
            background: {CLR_CARD_BG};
            border: 1px solid {CLR_CARD_BORDER};
            border-radius: 10px;
        }}
    """)
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(12)
    shadow.setOffset(0, 2)
    shadow.setColor(QColor(33, 150, 243, 30))
    card.setGraphicsEffect(shadow)

    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(12, 8, 12, 10)
    card_layout.setSpacing(6)

    header = QLabel(title_text)
    header.setMinimumWidth(0)
    header.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {CLR_TEXT_MAIN};")
    card_layout.addWidget(header)

    return card, card_layout


# ------------------------------------------------------------
# 3. 自绘折线图组件 (TrendChartWidget)
# ------------------------------------------------------------
class TrendChartWidget(QWidget):
    """自绘最近 15 分钟触发频率趋势折线图 (带渐变填充与边界安全限位)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self._trend_buckets: dict[int, int] = {}
        self._is_history_mode: bool = False

    def update_data(self, buckets: dict[int, int], is_history: bool = False) -> None:
        self._trend_buckets = buckets
        self._is_history_mode = is_history
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if self._is_history_mode:
            painter.setPen(QColor(CLR_TEXT_SUB))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "历史模式不提供实时趋势")
            return

        cur_min = int(time.time() // 60)
        minutes = [cur_min - 14 + i for i in range(15)]
        counts = [self._trend_buckets.get(m, 0) for m in minutes]
        labels = [time.strftime("%H:%M", time.localtime(m * 60)) for m in [minutes[0], minutes[5], minutes[10], minutes[14]]]

        pad_left, pad_right, pad_top, pad_bottom = 32, 16, 16, 28
        max_val = max(max(counts, default=0), 5)

        # 绘制网格与刻度
        painter.setPen(QPen(QColor("#EAF4FD"), 1))
        painter.setFont(QFont("Microsoft YaHei", 9))
        for i in range(4):
            y = pad_top + (h - pad_top - pad_bottom) * (i / 3.0)
            painter.drawLine(pad_left, int(y), w - pad_right, int(y))
            val_str = str(int(round(max_val * (1.0 - i / 3.0))))
            painter.setPen(QColor(CLR_TEXT_SUB))
            painter.drawText(4, int(y - 6), 24, 12, Qt.AlignmentFlag.AlignRight, val_str)
            painter.setPen(QPen(QColor("#EAF4FD"), 1))

        # 计算折线顶点
        pts = []
        for idx, cnt in enumerate(counts):
            x = pad_left + (w - pad_left - pad_right) * (idx / 14.0)
            y = pad_top + (h - pad_top - pad_bottom) * (1.0 - cnt / float(max_val))
            pts.append((x, y))

        # 面积渐变填充
        path = QPainterPath()
        path.moveTo(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.lineTo(pts[-1][0], h - pad_bottom)
        path.lineTo(pts[0][0], h - pad_bottom)
        path.closeSubpath()

        grad = QLinearGradient(0, pad_top, 0, h - pad_bottom)
        grad.setColorAt(0.0, QColor(33, 150, 243, 60))
        grad.setColorAt(1.0, QColor(33, 150, 243, 0))
        painter.fillPath(path, grad)

        # 绘制折线
        painter.setPen(QPen(QColor(CLR_SIDEBAR_ACT), 2))
        for idx in range(len(pts) - 1):
            painter.drawLine(int(pts[idx][0]), int(pts[idx][1]), int(pts[idx + 1][0]), int(pts[idx + 1][1]))

        # 绘制顶点圆点
        for x, y in pts:
            painter.setPen(QPen(QColor(CLR_SIDEBAR_ACT), 2))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(int(x - 3), int(y - 3), 6, 6)

        # 底部 X 轴标签 (严格左右下边界安全限位，绝不越界)
        painter.setPen(QColor(CLR_TEXT_SUB))
        label_xs = [
            pad_left,
            pad_left + (w - pad_left - pad_right) * (5 / 14.0),
            pad_left + (w - pad_left - pad_right) * (10 / 14.0),
            w - pad_right,
        ]
        for lx, ltext in zip(label_xs, labels):
            rect_x = min(max(0, int(lx - 20)), w - 40)
            painter.drawText(rect_x, int(h - 22), 40, 16, Qt.AlignmentFlag.AlignCenter, ltext)


# ------------------------------------------------------------
# 4. 主卡片全屏散点组件 (ClickScatterWidget)
# ------------------------------------------------------------
class ClickScatterWidget(QWidget):
    """自绘全屏物理点击落点分布图 (等比例 Letterbox + 绝对物理坐标)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self._scatter_points = collections.deque(maxlen=100)
        self._is_history_mode: bool = False

    def update_data(self, points: collections.deque, is_history: bool = False) -> None:
        self._scatter_points = points
        self._is_history_mode = is_history
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if self._is_history_mode:
            painter.setPen(QColor(CLR_TEXT_SUB))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "历史模式不提供实时分布")
            return

        sw_px, sh_px = get_primary_screen_physical_size()
        pad = 14
        fit_x, fit_y, fit_w, fit_h = fit_letterbox_rect(w, h, sw_px, sh_px, pad=pad)

        # 屏幕外框与底色
        painter.setPen(QPen(QColor(CLR_CARD_BORDER), 1))
        painter.setBrush(QColor(CLR_CONTENT_BG))
        painter.drawRoundedRect(fit_x, fit_y, fit_w, fit_h, 8, 8)

        # 十字虚线
        pen_dash = QPen(QColor("#C5DFFA"), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen_dash)
        painter.drawLine(fit_x, int(fit_y + fit_h / 2.0), fit_x + fit_w, int(fit_y + fit_h / 2.0))
        painter.drawLine(int(fit_x + fit_w / 2.0), fit_y, int(fit_x + fit_w / 2.0), fit_y + fit_h)

        # 遍历 ScatterPoint 绘制
        pts = list(self._scatter_points)
        if pts:
            for pt in pts[:-1]:
                px = fit_x + pt.nx * fit_w
                py = fit_y + pt.ny * fit_h
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(33, 150, 243, 140))
                painter.drawEllipse(int(px - 2.5), int(py - 2.5), 5, 5)

            # 最新点静态高亮双环
            lpt = pts[-1]
            lx = fit_x + lpt.nx * fit_w
            ly = fit_y + lpt.ny * fit_h
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(67, 160, 71, 70))
            painter.drawEllipse(int(lx - 7.5), int(ly - 7.5), 15, 15)
            painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
            painter.setBrush(QColor("#43A047"))
            painter.drawEllipse(int(lx - 3.5), int(ly - 3.5), 7, 7)

        # 右下角微缩视口标注 (动态测量文字宽度 + 半透明底垫防遮挡落点)
        txt = f"{sw_px}×{sh_px} 视口"
        painter.setFont(QFont("Microsoft YaHei", 8))
        fm = painter.fontMetrics()
        tw = min(fm.horizontalAdvance(txt) + 10, max(10, fit_w - 8))
        th = fm.height() + 2
        tx = fit_x + fit_w - tw - 4
        ty = fit_y + fit_h - th - 3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 180))
        painter.drawRoundedRect(tx, ty, tw, th, 3, 3)
        painter.setPen(QColor(CLR_TEXT_SUB))
        painter.drawText(tx, ty, tw, th, Qt.AlignmentFlag.AlignCenter, txt)


# ------------------------------------------------------------
# 5. 高清全屏大图弹窗 (ClickScatterDialog)
# ------------------------------------------------------------
class ClickScatterDialog(QDialog):
    """高清全屏点击落点大图弹窗 (支持拉伸、最大化、Tooltip 精确探测、Esc 退出)."""

    def __init__(self, dashboard: DashboardPage):
        super().__init__(parent=dashboard)
        self._dashboard = dashboard
        self._hovered_pt: ScatterPoint | None = None
        self.setWindowTitle("屏幕点击分布高清大图")
        self.resize(850, 550)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setStyleSheet(f"background: {CLR_CONTENT_BG};")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if self._dashboard._current_view_mode == "history":
            QToolTip.hideText()
            painter.setPen(QColor(CLR_TEXT_SUB))
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "历史模式不提供实时分布")
            return

        pts = list(self._dashboard._scatter_points)
        if not pts:
            QToolTip.hideText()
            painter.setPen(QColor(CLR_TEXT_SUB))
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无点击记录")
            return

        sw_px, sh_px = get_primary_screen_physical_size()
        pad = 24
        fit_x, fit_y, fit_w, fit_h = fit_letterbox_rect(w, h, sw_px, sh_px, pad=pad)

        # 绘制外框与十字辅助线
        painter.setPen(QPen(QColor(CLR_CARD_BORDER), 1.5))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(fit_x, fit_y, fit_w, fit_h, 8, 8)

        pen_dash = QPen(QColor("#C5DFFA"), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen_dash)
        painter.drawLine(fit_x, int(fit_y + fit_h / 2.0), fit_x + fit_w, int(fit_y + fit_h / 2.0))
        painter.drawLine(int(fit_x + fit_w / 2.0), fit_y, int(fit_x + fit_w / 2.0), fit_y + fit_h)

        # 绘制散点
        for pt in pts[:-1]:
            px = fit_x + pt.nx * fit_w
            py = fit_y + pt.ny * fit_h
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(33, 150, 243, 160))
            painter.drawEllipse(int(px - 3.5), int(py - 3.5), 7, 7)

        # 最新点静态高亮双环
        lpt = pts[-1]
        lx = fit_x + lpt.nx * fit_w
        ly = fit_y + lpt.ny * fit_h
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(67, 160, 71, 70))
        painter.drawEllipse(int(lx - 10), int(ly - 10), 20, 20)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setBrush(QColor("#43A047"))
        painter.drawEllipse(int(lx - 4.5), int(ly - 4.5), 9, 9)

        # 悬停命中点动态十字准星与外环 (FIX-05)
        if self._hovered_pt is not None and self._hovered_pt in pts:
            hx = int(round(fit_x + self._hovered_pt.nx * fit_w))
            hy = int(round(fit_y + self._hovered_pt.ny * fit_h))
            pen_cross = QPen(QColor(239, 83, 80, 180), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen_cross)
            painter.drawLine(fit_x, hy, fit_x + fit_w, hy)
            painter.drawLine(hx, fit_y, hx, fit_y + fit_h)
            painter.setPen(QPen(QColor("#EF5350"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(hx - 6, hy - 6, 12, 12)

        # 右下角视口标注 (动态测量文字宽度 + 半透明底垫防遮挡落点)
        txt = f"{sw_px}×{sh_px} 真实物理视口"
        painter.setFont(QFont("Microsoft YaHei", 9))
        fm = painter.fontMetrics()
        tw = min(fm.horizontalAdvance(txt) + 12, max(10, fit_w - 12))
        th = fm.height() + 2
        tx = fit_x + fit_w - tw - 6
        ty = fit_y + fit_h - th - 5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 190))
        painter.drawRoundedRect(tx, ty, tw, th, 4, 4)
        painter.setPen(QColor(CLR_TEXT_SUB))
        painter.drawText(tx, ty, tw, th, Qt.AlignmentFlag.AlignCenter, txt)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dashboard._current_view_mode == "history":
            QToolTip.hideText()
            if self._hovered_pt is not None:
                self._hovered_pt = None
                self.update()
            return
        pts = list(self._dashboard._scatter_points)
        if not pts:
            QToolTip.hideText()
            if self._hovered_pt is not None:
                self._hovered_pt = None
                self.update()
            return

        sw_px, sh_px = get_primary_screen_physical_size()
        fit_x, fit_y, fit_w, fit_h = fit_letterbox_rect(self.width(), self.height(), sw_px, sh_px, pad=24)
        mx, my = event.pos().x(), event.pos().y()

        hovered_pt = None
        for pt in reversed(pts):
            px = fit_x + pt.nx * fit_w
            py = fit_y + pt.ny * fit_h
            if (mx - px) ** 2 + (my - py) ** 2 <= 64:  # 8px 半径内精准命中
                hovered_pt = pt
                break

        if hovered_pt != self._hovered_pt:
            self._hovered_pt = hovered_pt
            self.update()

        if hovered_pt:
            tip = f"[{hovered_pt.task_name}] 落点: ({hovered_pt.tx}, {hovered_pt.ty}) · 时间: {hovered_pt.timestamp_str}"
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()

    def resizeEvent(self, event) -> None:
        QToolTip.hideText()
        if self._hovered_pt is not None:
            self._hovered_pt = None
            self.update()
        super().resizeEvent(event)

    def leaveEvent(self, event) -> None:
        QToolTip.hideText()
        if self._hovered_pt is not None:
            self._hovered_pt = None
            self.update()
        super().leaveEvent(event)

    def closeEvent(self, event) -> None:
        QToolTip.hideText()
        if self._hovered_pt is not None:
            self._hovered_pt = None
            self.update()
        super().closeEvent(event)


# ------------------------------------------------------------
# 6. 数据看板主页面 (DashboardPage)
# ------------------------------------------------------------
class DashboardPage(QScrollArea):
    """数据看板主页面 (工业生产级加固实现)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_window = parent
        self._running = False
        self._current_view_mode = "session"  # "session" 或 "history"
        self._stats_load_failed = False     # 保护标志：若加载损坏配置，防导出覆盖零值

        # 1. 持久化历史模型
        self._history = {
            "total_run_seconds": 0.0,
            "total_scans": 0,
            "total_scan_cost_ms": 0.0,
            "total_matches": 0,
            "total_clicks": 0,
            "task_stats": {},
        }
        # 2. 本次运行模型
        self._session = self._create_empty_stats()

        # 3. 数据容器 (显式完整声明，双队列数据源解耦)
        self._session_logs = collections.deque(maxlen=50)
        self._history_logs = collections.deque(maxlen=50)
        self._scatter_points = collections.deque(maxlen=100)
        self._trend_buckets = {}
        self._scatter_dialog: ClickScatterDialog | None = None
        self.btn_zoom: QPushButton | None = None

        # 4. 计时器、真实时钟基准与排行防抖定时器 (BUG-03 修复：基于自然时钟杜绝跳秒)
        self._session_start_time: float = 0.0
        self._last_telemetry_time: float = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_timer_tick)
        self._rank_debounce_timer = QTimer(self)
        self._rank_debounce_timer.setSingleShot(True)
        self._rank_debounce_timer.setInterval(200)
        self._rank_debounce_timer.timeout.connect(self._update_rank_display)

        # 50ms 历史榜单防抖重算定时器 (FIX-05)
        self._hist_resize_timer = QTimer(self)
        self._hist_resize_timer.setSingleShot(True)
        self._hist_resize_timer.setInterval(50)
        self._hist_resize_timer.timeout.connect(self._update_history_clicks_display)

        # 5. 构建 UI 界面
        self._setup_ui()

    def _create_empty_stats(self) -> dict:
        return {
            "run_seconds": 0.0, "scans": 0, "scan_cost_ms": 0.0,
            "last_cost_ms": 0.0, "matches": 0, "clicks": 0, "task_stats": {},
        }

    def _setup_ui(self) -> None:
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("border: none; background: transparent;")

        container = QWidget()
        container.setObjectName("dashboard_container")
        container.setStyleSheet(f"#dashboard_container {{ background: {CLR_CONTENT_BG}; }}")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 10, 12, 14)
        layout.setSpacing(10)

        # TopBar
        top_bar = QHBoxLayout()
        title = QLabel("数据看板")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {CLR_TEXT_MAIN};")
        top_bar.addWidget(title)
        top_bar.addStretch(1)

        self.btn_mode_session = QPushButton("本次运行")
        self.btn_mode_history = QPushButton("历史累计")
        for b in (self.btn_mode_session, self.btn_mode_history):
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setStyleSheet(
                f"QPushButton {{ background: #FFFFFF; border: 1px solid {CLR_CARD_BORDER}; "
                f"border-radius: 6px; padding: 0 12px; font-size: 12px; color: {CLR_TEXT_SUB}; }} "
                f"QPushButton:checked {{ background: {CLR_BTN_PRIMARY}; color: #FFF; font-weight: bold; }}"
            )
        self.btn_mode_session.setChecked(True)
        self.btn_mode_session.clicked.connect(lambda: self._on_mode_switched("session"))
        self.btn_mode_history.clicked.connect(lambda: self._on_mode_switched("history"))
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.btn_mode_session)
        self.mode_group.addButton(self.btn_mode_history)
        top_bar.addWidget(self.btn_mode_session)
        top_bar.addWidget(self.btn_mode_history)

        self.btn_clear = QPushButton("清空统计")
        self.btn_clear.setIcon(button_icon("refresh-cw", CLR_TEXT_SUB, 14, self.devicePixelRatioF()))
        self.btn_clear.setFixedHeight(28)
        self.btn_clear.setStyleSheet(
            f"QPushButton {{ background: #FFFFFF; border: 1px solid {CLR_CARD_BORDER}; "
            f"border-radius: 6px; padding: 0 10px; font-size: 12px; color: {CLR_TEXT_SUB}; }} "
            f"QPushButton:hover {{ border-color: #B0CDE8; color: {CLR_BTN_PRIMARY}; }}"
        )
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        top_bar.addWidget(self.btn_clear)
        layout.addLayout(top_bar)

        # KPI 4 卡片 (2x2 网格紧凑间距与字体，确保 550px 窄窗口下彻底杜绝水平溢出与裁切)
        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(6)
        def _make_kpi(t: str):
            c, cl = make_dashboard_card(t)
            cl.setContentsMargins(6, 6, 6, 6)
            cl.setSpacing(2)
            if cl.count() > 0 and cl.itemAt(0).widget():
                cl.itemAt(0).widget().setStyleSheet(f"font-size: 11px; font-weight: bold; color: {CLR_TEXT_MAIN};")
            v = QLabel("0")
            v.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {CLR_TEXT_MAIN};")
            s = QLabel("—")
            s.setStyleSheet(f"font-size: 10px; color: {CLR_TEXT_SUB};")
            cl.addWidget(v)
            cl.addWidget(s)
            return c, v, s

        c_dur, self.kpi_dur_v, self.kpi_dur_s = _make_kpi("运行时长")
        c_mat, self.kpi_mat_v, self.kpi_mat_s = _make_kpi("匹配触发")
        c_clk, self.kpi_clk_v, self.kpi_clk_s = _make_kpi("累计点击")
        c_cst, self.kpi_cst_v, self.kpi_cst_s = _make_kpi("扫描性能")
        kpi_grid.addWidget(c_dur, 0, 0)
        kpi_grid.addWidget(c_mat, 0, 1)
        kpi_grid.addWidget(c_clk, 1, 0)
        kpi_grid.addWidget(c_cst, 1, 1)
        layout.addLayout(kpi_grid)

        # 任务排行
        rank_card, rank_layout = make_dashboard_card("任务触发排行与占比")
        self.rank_container = QVBoxLayout()
        rank_layout.addLayout(self.rank_container)
        layout.addWidget(rank_card)

        # 双栏图表 (折线图 + 散点图与放大按钮接入)
        charts_row = QHBoxLayout()
        c_trend, l_trend = make_dashboard_card("触发频率趋势 (最近15分钟)")
        if l_trend.count() > 0 and l_trend.itemAt(0).widget():
            l_trend.itemAt(0).widget().setFixedHeight(24)  # 严格对齐右侧放大按钮卡片高度，消除6px高低肩
        self.trend_chart = TrendChartWidget()
        l_trend.addWidget(self.trend_chart)

        c_scat, l_scat = make_dashboard_card("点击分布")
        self.btn_zoom = QPushButton()
        self.btn_zoom.setIcon(button_icon("maximize-2", CLR_TEXT_SUB, 14, self.devicePixelRatioF()))
        self.btn_zoom.setFixedSize(24, 24)
        self.btn_zoom.setToolTip("放大查看")
        self.btn_zoom.setStyleSheet(
            f"QPushButton {{ background: #FFFFFF; border: 1px solid {CLR_CARD_BORDER}; border-radius: 4px; }} "
            f"QPushButton:hover {{ border-color: #B0CDE8; color: {CLR_BTN_PRIMARY}; }}"
        )
        self.btn_zoom.clicked.connect(self._open_scatter_dialog)

        if l_scat.count() > 0:
            hdr_scat = l_scat.itemAt(0).widget()
            l_scat.removeWidget(hdr_scat)
            h_row_scat = QHBoxLayout()
            h_row_scat.addWidget(hdr_scat)
            h_row_scat.addStretch(1)
            h_row_scat.addWidget(self.btn_zoom)
            l_scat.insertLayout(0, h_row_scat)

        self.scatter_chart = ClickScatterWidget()
        l_scat.addWidget(self.scatter_chart)

        self.card_trend = c_trend
        self.card_scat = c_scat

        # 历史累计模式双卡片 (点击贡献榜 + 数据存储与备份迁移指引)
        self.card_hist_clicks, l_hist_clicks = make_dashboard_card("各任务累计点击贡献")
        self.card_hist_clicks.setMinimumWidth(0)
        if l_hist_clicks.count() > 0 and l_hist_clicks.itemAt(0).widget():
            hdr = l_hist_clicks.itemAt(0).widget()
            hdr.setFixedHeight(24)
            hdr.setMinimumWidth(0)
        self.hist_clicks_container = QVBoxLayout()
        self.hist_clicks_container.setContentsMargins(0, 4, 0, 4)
        self.hist_clicks_container.setSpacing(8)
        l_hist_clicks.addLayout(self.hist_clicks_container)
        l_hist_clicks.addStretch(1)

        self.card_hist_guide, l_hist_guide = make_dashboard_card("数据存储与备份迁移指引")
        self.card_hist_guide.setMinimumWidth(0)
        if l_hist_guide.count() > 0 and l_hist_guide.itemAt(0).widget():
            hdr = l_hist_guide.itemAt(0).widget()
            hdr.setFixedHeight(24)
            hdr.setMinimumWidth(0)

        guide_box = QFrame()
        guide_box.setObjectName("guide_box_panel")
        guide_box.setStyleSheet(
            "#guide_box_panel {"
            "  background: #F4F9FD;"
            "  border: 1px solid #D2E3F7;"
            "  border-radius: 6px;"
            "}"
        )
        guide_box_layout = QVBoxLayout(guide_box)
        guide_box_layout.setContentsMargins(8, 8, 8, 8)
        guide_box_layout.setSpacing(8)

        def _make_guide_row(icon_name: str, icon_clr: str, title_str: str, desc_str: str) -> QWidget:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(6)
            ic_lbl = QLabel()
            ic_lbl.setFixedSize(16, 16)
            set_label_icon(ic_lbl, icon_name, icon_clr, 14)
            row_l.addWidget(ic_lbl, 0, Qt.AlignmentFlag.AlignTop)

            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            t_lbl = QLabel(title_str)
            t_lbl.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {CLR_TEXT_MAIN};")
            d_lbl = QLabel(desc_str)
            d_lbl.setWordWrap(True)
            d_lbl.setStyleSheet(f"font-size: 10px; color: {CLR_TEXT_SUB};")
            col.addWidget(t_lbl)
            col.addWidget(d_lbl)
            row_l.addLayout(col, 1)
            return row_w

        guide_box_layout.addWidget(_make_guide_row(
            "save", CLR_BTN_PRIMARY, "本地自动保存",
            "战绩与配置存至根目录 config.json，模板图存至 screenshots/ 目录。"
        ))
        guide_box_layout.addWidget(_make_guide_row(
            "folder", CLR_SIDEBAR_ACT, "版本升级迁移",
            "换机或升级时，将旧版 config.json 与 screenshots/ 复制覆盖到新版即可继承全部数据。"
        ))
        guide_box_layout.addWidget(_make_guide_row(
            "info", CLR_TEXT_SUB, "清空重置说明",
            "点击右上角「清空统计」将归零所有历史累计战绩。"
        ))
        l_hist_guide.addWidget(guide_box)
        l_hist_guide.addStretch(1)

        self.btn_open_config_dir = QPushButton("打开配置所在目录")
        self.btn_open_config_dir.setIcon(button_icon("folder", CLR_TEXT_MAIN, 14, self.devicePixelRatioF()))
        self.btn_open_config_dir.setFixedHeight(28)
        self.btn_open_config_dir.setStyleSheet(
            f"QPushButton {{ background: #FFFFFF; border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px; "
            f"padding: 0 10px; font-size: 11px; color: {CLR_TEXT_MAIN}; font-weight: bold; }} "
            f"QPushButton:hover {{ border-color: #B0CDE8; color: {CLR_BTN_PRIMARY}; }}"
        )
        self.btn_open_config_dir.clicked.connect(self._on_open_config_dir)
        l_hist_guide.addWidget(self.btn_open_config_dir)

        # 初始默认处于 session 模式，隐藏历史卡片
        self.card_hist_clicks.setVisible(False)
        self.card_hist_guide.setVisible(False)

        # 确保全部卡片加入行布局 (历史双卡采用 1:1 均分自适应)
        charts_row.addWidget(self.card_trend, 6)
        charts_row.addWidget(self.card_scat, 4)
        charts_row.addWidget(self.card_hist_clicks, 1)
        charts_row.addWidget(self.card_hist_guide, 1)
        layout.addLayout(charts_row)

        # 流水卡片 (关闭水平滚动条，统一行高与精确固定高度 136px，消除半截横切)
        c_log, l_log = make_dashboard_card("最近执行流水 (最近50条)")
        btn_copy = QPushButton("复制记录")
        btn_copy.setIcon(button_icon("copy", CLR_TEXT_SUB, 14, self.devicePixelRatioF()))
        btn_copy.setFixedHeight(24)
        btn_copy.setStyleSheet(
            f"QPushButton {{ background: #FFFFFF; border: 1px solid {CLR_CARD_BORDER}; border-radius: 4px; padding: 0 8px; font-size: 11px; color: {CLR_TEXT_MAIN}; }} "
            f"QPushButton:hover {{ border-color: #B0CDE8; color: {CLR_BTN_PRIMARY}; }}"
        )
        btn_copy.clicked.connect(lambda: self._on_copy_logs_clicked(btn_copy))
        if l_log.count() > 0:
            hdr_log = l_log.itemAt(0).widget()
            l_log.removeWidget(hdr_log)
            h_row_log = QHBoxLayout()
            h_row_log.addWidget(hdr_log)
            h_row_log.addStretch(1)
            h_row_log.addWidget(btn_copy)
            l_log.insertLayout(0, h_row_log)

        self.list_logs = QListWidget()
        self.list_logs.setFixedHeight(136)
        self.list_logs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_logs.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list_logs.setUniformItemSizes(True)
        self.list_logs.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerItem)
        self.list_logs.setStyleSheet(
            f"background: transparent; border: 1px solid #EDF5FD; border-radius: 6px; "
            f"font-size: 12px; color: {CLR_TEXT_MAIN};"
        )
        l_log.addWidget(self.list_logs)
        layout.addWidget(c_log)

        self.setWidget(container)
        self._update_ui_display()
        self._refresh_logs_display()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "_current_view_mode", "session") == "history":
            if hasattr(self, "_hist_resize_timer"):
                self._hist_resize_timer.start()

    # ------------------------------------------------------------
    # 单例弹窗工厂与销毁回调
    # ------------------------------------------------------------
    def _open_scatter_dialog(self) -> None:
        try:
            if self._scatter_dialog is None:
                self._scatter_dialog = ClickScatterDialog(self)
                self._scatter_dialog.destroyed.connect(self._on_scatter_dialog_destroyed)
            self._scatter_dialog.show()
            self._scatter_dialog.raise_()
            self._scatter_dialog.activateWindow()
        except Exception as e:
            logger.error(f"打开放大弹窗异常: {e}")

    def _on_scatter_dialog_destroyed(self) -> None:
        self._scatter_dialog = None

    def _on_timer_tick(self) -> None:
        try:
            if self._running:
                # 基于真实自然时钟计算秒数，丝滑均匀且绝无跳秒顿挫 (BUG-03)
                if self._session_start_time > 0:
                    self._session["run_seconds"] = max(self._session["run_seconds"], time.time() - self._session_start_time)
                self._update_kpi_display()
                # 保持趋势图 X 轴随真实时间自然流淌 (即使长时间无匹配，时间刻度也不会冻结)
                is_sess = (self._current_view_mode == "session")
                self.trend_chart.update_data(self._trend_buckets, is_history=not is_sess)
                if self._main_window and hasattr(self._main_window, "_update_remote_status_cache"):
                    self._main_window._update_remote_status_cache()
        except Exception as e:
            logger.error(f"计时器更新异常: {e}")

    def get_current_duration_str(self) -> str:
        try:
            total_sec = int(self._session["run_seconds"])
            return f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}:{total_sec % 60:02d}"
        except Exception:
            return "00:00:00"

    def get_current_match_count(self) -> int:
        try:
            return int(self._session["matches"])
        except Exception:
            return 0

    def load_stats_history(self, raw: dict | None) -> None:
        """加载历史持久化数据，含健壮校验与异常标记."""
        try:
            if raw is None:
                self._stats_load_failed = False
                self._refresh_logs_display()
                return
            if not isinstance(raw, dict):
                self._stats_load_failed = True
                logger.warning("历史数据非合法字典，标记加载失败以保护原有持久化数据。")
                self._refresh_logs_display()
                return
            self._history["total_run_seconds"] = float(raw.get("total_run_seconds", raw.get("total_run_time_sec", 0.0)))
            self._history["total_scans"] = int(raw.get("total_scans", 0))
            self._history["total_scan_cost_ms"] = float(raw.get("total_scan_cost_ms", 0.0))
            self._history["total_matches"] = int(raw.get("total_matches", 0))
            self._history["total_clicks"] = int(raw.get("total_clicks", 0))
            ts = raw.get("task_stats")
            if isinstance(ts, dict):
                self._history["task_stats"] = {
                    str(k): {
                        "matches": int(v.get("matches", 0)),
                        "clicks": int(v.get("clicks", 0)),
                        "total_score": float(v.get("total_score", 0.0)),
                    } for k, v in ts.items() if isinstance(v, dict)
                }

            # 历史流水安全读取 (非列表或缺失绝不连坐标记数值损坏)
            logs_raw = raw.get("recent_logs")
            if isinstance(logs_raw, (list, tuple)):
                valid_logs = [str(x) for x in logs_raw if isinstance(x, str)]
                self._history_logs = collections.deque(valid_logs[:50], maxlen=50)
            else:
                self._history_logs.clear()

            self._stats_load_failed = False
            self._update_ui_display()
            self._refresh_logs_display()
        except Exception as e:
            self._stats_load_failed = True
            logger.warning(f"历史数据解析异常，标记保护: {e}")
            self._refresh_logs_display()

    def on_engine_started(self) -> None:
        """引擎启动完整生命周期 (显式清空本次日志队列，杜绝跨轮重复)."""
        try:
            self._running = True
            self._session_start_time = time.time()  # 锚定自然时钟起点
            self._current_view_mode = "session"
            self.btn_mode_session.setChecked(True)
            self.btn_mode_history.setChecked(False)
            self._last_telemetry_time = 0.0
            if hasattr(self, "_rank_debounce_timer"):
                self._rank_debounce_timer.stop()
            self._session = self._create_empty_stats()
            self._session_logs.clear()       # 显式重置本次日志
            self._scatter_points.clear()
            self._trend_buckets.clear()
            self._refresh_logs_display()     # 刷新显示为占位条目
            self._timer.start()              # 时长计时器启动
            self.btn_clear.setEnabled(False) # 运行中禁用清空
            self._update_ui_display()
            if self._scatter_dialog and self._scatter_dialog.isVisible():
                self._scatter_dialog.update()
        except Exception as e:
            logger.error(f"看板启动异常: {e}")

    def on_engine_stopped(self) -> None:
        """引擎停机结算 (数值与日志合并拆分独立 try 保护)."""
        if not self._running:
            return
        self._running = False
        if self._session_start_time > 0:
            self._session["run_seconds"] = max(self._session["run_seconds"], time.time() - self._session_start_time)
            self._session_start_time = 0.0

        # 1. 数值合并
        try:
            self._history["total_run_seconds"] += self._session["run_seconds"]
            self._history["total_scans"] += self._session["scans"]
            self._history["total_scan_cost_ms"] += self._session["scan_cost_ms"]
            self._history["total_matches"] += self._session["matches"]
            self._history["total_clicks"] += self._session["clicks"]
            for name, stat in self._session["task_stats"].items():
                h = self._history["task_stats"].setdefault(name, {"matches": 0, "clicks": 0, "total_score": 0.0})
                h["matches"] += stat.get("matches", 0)
                h["clicks"] += stat.get("clicks", 0)
                h["total_score"] += stat.get("total_score", 0.0)
        except Exception as e:
            logger.error(f"历史数据合并异常: {e}")

        # 2. 日志合并 (独立保护，本次 session 排在最前，截取最新 50 条)
        try:
            new_combined = list(self._session_logs) + list(self._history_logs)
            self._history_logs = collections.deque(new_combined[:50], maxlen=50)
        except Exception as e:
            logger.error(f"历史流水合并异常: {e}")

        # 3. 定时器与 UI 刷新
        try:
            if hasattr(self, "_rank_debounce_timer"):
                self._rank_debounce_timer.stop()
            self._timer.stop()
            self.btn_clear.setEnabled(True)
            self._update_ui_display()
            self._refresh_logs_display()
            if self._scatter_dialog and self._scatter_dialog.isVisible():
                self._scatter_dialog.update()
            if self._main_window and hasattr(self._main_window, "_save_config"):
                self._main_window._save_config()
        except Exception as e:
            logger.error(f"看板停机刷新异常: {e}")

    @pyqtSlot(dict)
    def on_stats_updated(self, data: dict) -> None:
        try:
            if not data:
                return
            if not self._running:
                # 停机后到达的在途遥测包或结算包，补计入历史与会话，杜绝无声丢弃
                self._session["scans"] += data.get("scan_delta", 0)
                self._session["scan_cost_ms"] += data.get("scan_cost_delta_ms", 0.0)
                self._session["last_cost_ms"] = data.get("last_cost_ms", 0.0)
                self._history["total_scans"] += data.get("scan_delta", 0)
                self._history["total_scan_cost_ms"] += data.get("scan_cost_delta_ms", 0.0)
                self._update_kpi_display()
                return
            self._session["scans"] += data.get("scan_delta", 0)
            self._session["scan_cost_ms"] += data.get("scan_cost_delta_ms", 0.0)
            self._session["last_cost_ms"] = data.get("last_cost_ms", 0.0)
            if "elapsed_sec" in data:
                self._session["run_seconds"] = max(self._session["run_seconds"], float(data["elapsed_sec"]))
                self._last_telemetry_time = time.time()
            self._update_kpi_display()
        except Exception as e:
            logger.error(f"更新统计异常: {e}")

    @pyqtSlot(dict)
    def on_task_triggered(self, data: dict) -> None:
        """任务触发完整方法 (全屏物理散点装配、最新在前流水写入、弹窗实时联动)."""
        try:
            if not data:
                return
            self._session["matches"] += 1
            clicks = data.get("clicks") or []
            self._session["clicks"] += len(clicks)
            tname = data.get("name", "未命名")
            ts = self._session["task_stats"].setdefault(tname, {"matches": 0, "clicks": 0, "total_score": 0.0})
            ts["matches"] += 1
            ts["clicks"] += len(clicks)
            ts["total_score"] += data.get("score", 0.0)

            # 若停机结算已完成，同步补记到历史统计中 (Bug-09)
            if not self._running:
                self._history["total_matches"] += 1
                self._history["total_clicks"] += len(clicks)
                hs = self._history["task_stats"].setdefault(tname, {"matches": 0, "clicks": 0, "total_score": 0.0})
                hs["matches"] += 1
                hs["clicks"] += len(clicks)
                hs["total_score"] += data.get("score", 0.0)

            # 趋势折线桶
            epoch_min = int(time.time() // 60)
            self._trend_buckets[epoch_min] = self._trend_buckets.get(epoch_min, 0) + 1

            # 全屏物理散点装配 (严格 2 元组解包与 clamp 归一化)
            sw_px, sh_px = get_primary_screen_physical_size()
            tstr = time.strftime("%H:%M:%S")
            for pt in clicks:
                if len(pt) >= 2:
                    tx, ty = int(pt[0]), int(pt[1])
                    nx, ny = normalize_click_physical(tx, ty, sw_px, sh_px)
                    self._scatter_points.append(ScatterPoint(nx, ny, tx, ty, tname, tstr))

            # 流水文本生成与 session 队列追加 (最新在前)
            coord_str = f"{clicks[0][0]},{clicks[0][1]}" if clicks else "—"
            text = f"{tstr} 触发「{tname}」· 精度 {data.get('score')}% · 落点 ({coord_str}) · 延迟 {data.get('delay_ms')}ms"
            self._session_logs.appendleft(text)
            if not self._running:
                self._history_logs.appendleft(text)

            # 仅当处于 session 模式时动态插入 UI
            if self._current_view_mode == "session":
                if self.list_logs.count() == 1 and self.list_logs.item(0).data(Qt.ItemDataRole.UserRole) == "placeholder":
                    self.list_logs.clear()
                item = QListWidgetItem(text)
                item.setSizeHint(QSize(0, 22))
                self.list_logs.insertItem(0, item)
                while self.list_logs.count() > 50:
                    self.list_logs.takeItem(self.list_logs.count() - 1)

            if not self._running:
                self._update_ui_display()
                self._refresh_logs_display()
                if self._main_window and hasattr(self._main_window, "_save_config"):
                    self._main_window._save_config()
            else:
                self._update_kpi_display()
                is_sess = (self._current_view_mode == "session")
                self.trend_chart.update_data(self._trend_buckets, is_history=not is_sess)
                self.scatter_chart.update_data(self._scatter_points, is_history=not is_sess)
                if self._scatter_dialog and self._scatter_dialog.isVisible():
                    self._scatter_dialog.update()

                # 排行列表节流刷新
                if hasattr(self, "_rank_debounce_timer") and not self._rank_debounce_timer.isActive():
                    self._rank_debounce_timer.start()
                elif not hasattr(self, "_rank_debounce_timer"):
                    self._update_rank_display()
        except Exception as e:
            logger.error(f"触发记录异常: {e}")

    def export_stats_history(self) -> dict:
        """导出纯快照 (铁律：损坏早退；异常回退安全注入日志)."""
        try:
            if self._stats_load_failed:
                return {}  # 铁律：损坏早退
            h = copy.deepcopy(self._history)
            if self._running:
                h["total_run_seconds"] += self._session["run_seconds"]
                h["total_scans"] += self._session["scans"]
                h["total_scan_cost_ms"] += self._session["scan_cost_ms"]
                h["total_matches"] += self._session["matches"]
                h["total_clicks"] += self._session["clicks"]
                for name, stat in self._session["task_stats"].items():
                    ts = h["task_stats"].setdefault(name, {"matches": 0, "clicks": 0, "total_score": 0.0})
                    ts["matches"] += stat.get("matches", 0)
                    ts["clicks"] += stat.get("clicks", 0)
                    ts["total_score"] += stat.get("total_score", 0.0)
                h["recent_logs"] = (list(self._session_logs) + list(self._history_logs))[:50]
            else:
                h["recent_logs"] = list(self._history_logs)
            return h
        except Exception as e:
            logger.error(f"导出快照异常: {e}")
            res = copy.deepcopy(self._history)
            if self._running:
                res["total_run_seconds"] += self._session.get("run_seconds", 0.0)
                res["total_matches"] += self._session.get("matches", 0)
                res["total_clicks"] += self._session.get("clicks", 0)
                res["recent_logs"] = (list(self._session_logs) + list(self._history_logs))[:50]
            else:
                res["recent_logs"] = list(self._history_logs)
            return res

    def _refresh_logs_display(self) -> None:
        """清空并重填 list_logs，占位条目带 UserRole='placeholder' 标记."""
        try:
            self.list_logs.clear()
            target_logs = self._session_logs if self._current_view_mode == "session" else self._history_logs
            if not target_logs:
                tip = "暂无本次运行流水" if self._current_view_mode == "session" else "暂无历史执行流水"
                item = QListWidgetItem(tip)
                item.setSizeHint(QSize(0, 22))
                item.setData(Qt.ItemDataRole.UserRole, "placeholder")
                item.setForeground(QColor(CLR_TEXT_SUB))
                self.list_logs.addItem(item)
            else:
                for text in target_logs:
                    item = QListWidgetItem(text)
                    item.setSizeHint(QSize(0, 22))
                    self.list_logs.addItem(item)
        except Exception as e:
            logger.error(f"刷新流水列表异常: {e}")

    def _update_kpi_display(self) -> None:
        try:
            is_sess = (self._current_view_mode == "session")
            cur = self._session if is_sess else {
                "run_seconds": self._history.get("total_run_seconds", self._history.get("total_run_time_sec", 0.0)),
                "matches": self._history.get("total_matches", 0),
                "clicks": self._history.get("total_clicks", 0),
                "scans": self._history.get("total_scans", 0),
                "scan_cost_ms": self._history.get("total_scan_cost_ms", 0.0),
                "last_cost_ms": 0.0,
            }
            sec = int(cur["run_seconds"])
            self.kpi_dur_v.setText(f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}")
            self.kpi_dur_s.setText("状态: 运行中" if self._running else "状态: 已就绪")

            m = cur["matches"]
            self.kpi_mat_v.setText(f"{m} 次")
            freq = (m / (sec / 60.0)) if sec > 0 else 0.0
            self.kpi_mat_s.setText(f"频率: {freq:.1f} 次/分")

            c = cur["clicks"]
            self.kpi_clk_v.setText(f"{c} 次")
            ratio = (c / float(m)) if m > 0 else 0.0
            self.kpi_clk_s.setText(f"连击: {ratio:.2f} 击/次")

            scans = cur["scans"]
            tot_cost = cur["scan_cost_ms"]
            avg_cost = (tot_cost / float(scans)) if scans > 0 else 0.0
            rate = (1000.0 / avg_cost) if avg_cost > 0 else 0.0
            self.kpi_cst_v.setText(f"{avg_cost:.1f} ms")
            self.kpi_cst_s.setText(f"速率: {rate:.1f} 轮/秒")
        except Exception as e:
            logger.error(f"刷新KPI异常: {e}")

    def _update_ui_display(self) -> None:
        try:
            self._update_kpi_display()
            self._update_rank_display()
            is_sess = (self._current_view_mode == "session")
            if self.btn_zoom:
                self.btn_zoom.setVisible(is_sess)
            if hasattr(self, "card_trend") and hasattr(self, "card_scat"):
                self.card_trend.setVisible(is_sess)
                self.card_scat.setVisible(is_sess)
            if hasattr(self, "card_hist_clicks") and hasattr(self, "card_hist_guide"):
                self.card_hist_clicks.setVisible(not is_sess)
                self.card_hist_guide.setVisible(not is_sess)
            if is_sess:
                self.trend_chart.update_data(self._trend_buckets, is_history=False)
                self.scatter_chart.update_data(self._scatter_points, is_history=False)
            else:
                self._update_history_clicks_display()
        except Exception as e:
            logger.error(f"刷新看板视图异常: {e}")

    def _on_open_config_dir(self) -> None:
        try:
            from config_manager import CONFIG_FILE
            if not os.path.exists(CONFIG_FILE) and self._main_window and hasattr(self._main_window, "_save_config"):
                self._main_window._save_config()
            norm_path = os.path.normpath(os.path.abspath(CONFIG_FILE))
            if os.path.exists(norm_path):
                subprocess.Popen(["explorer", f"/select,{norm_path}"])
            else:
                os.startfile(os.path.dirname(norm_path))
        except Exception as e:
            logger.error(f"打开配置文件目录失败: {e}")

    def _update_history_clicks_display(self) -> None:
        try:
            if not hasattr(self, "hist_clicks_container") or self.hist_clicks_container is None:
                return

            while self.hist_clicks_container.count() > 0:
                it = self.hist_clicks_container.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.hide()
                    w.deleteLater()

            task_stats = self._history.get("task_stats", {})
            total_clicks = self._history.get("total_clicks", 0)

            if not task_stats or total_clicks <= 0:
                empty = QLabel("暂无历史点击数据，运行任务后在此展示累计战绩")
                empty.setWordWrap(True)
                empty.setMinimumWidth(0)
                empty.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px; padding: 12px;")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.hist_clicks_container.addWidget(empty)
                return

            card_w = self.card_hist_clicks.width() if hasattr(self, "card_hist_clicks") else 0
            if card_w < 140 and self.viewport() and self.viewport().width() > 300:
                card_w = (self.viewport().width() - 30) // 2
            row_content_width = card_w - 28 if card_w > 0 else 0
            calc_row_w = 165 if row_content_width < 140 else row_content_width

            for name, s in sorted(task_stats.items(), key=lambda x: x[1].get("clicks", 0), reverse=True):
                clicks = s.get("clicks", 0)
                pct = (clicks / float(total_clicks) * 100.0) if total_clicks > 0 else 0.0
                matches = s.get("matches", 0)
                ratio = (clicks / float(matches)) if matches > 0 else 0.0

                if clicks < 10000:
                    val_text = f"{clicks} ({pct:.0f}%)"
                elif clicks < 100000:
                    val_text = f"{clicks / 1000.0:.1f}k ({pct:.0f}%)"
                else:
                    val_text = f"{clicks / 1000.0:.0f}k ({pct:.0f}%)"

                item_widget = QWidget()
                item_layout = QVBoxLayout(item_widget)
                item_layout.setContentsMargins(0, 2, 0, 2)
                item_layout.setSpacing(3)

                h_row = QHBoxLayout()
                h_row.setContentsMargins(0, 0, 0, 0)
                h_row.setSpacing(4)

                font_val = QFont("Microsoft YaHei")
                font_val.setPixelSize(10)
                lbl_val = QLabel(val_text)
                lbl_val.setFont(font_val)
                lbl_val.setStyleSheet(f"font-size: 10px; color: {CLR_TEXT_SUB};")
                lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                val_w = QFontMetrics(font_val).horizontalAdvance(val_text)
                avail_w = max(24, calc_row_w - val_w - 12)

                font_name = QFont("Microsoft YaHei")
                font_name.setPixelSize(11)
                font_name.setWeight(QFont.Weight.Bold)
                elided_name = QFontMetrics(font_name).elidedText(name, Qt.TextElideMode.ElideRight, avail_w)
                lbl_name = QLabel(elided_name)
                lbl_name.setFont(font_name)
                lbl_name.setMaximumWidth(avail_w)
                lbl_name.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {CLR_TEXT_MAIN};")

                h_row.addWidget(lbl_name)
                h_row.addStretch(1)
                h_row.addWidget(lbl_val)

                bar = QProgressBar()
                bar.setFixedHeight(6)
                bar.setTextVisible(False)
                bar.setRange(0, 1000)
                bar.setValue(int(pct * 10))
                bar.setStyleSheet(f"""
                    QProgressBar {{
                        background: #EAF4FD;
                        border: none;
                        border-radius: 3px;
                    }}
                    QProgressBar::chunk {{
                        background: {CLR_SIDEBAR_ACT};
                        border-radius: 3px;
                    }}
                """)

                item_layout.addLayout(h_row)
                item_layout.addWidget(bar)

                tip_text = f"{name}: 累计点击 {clicks:,} 次, 占比 {pct:.1f}%, 连击率 {ratio:.1f}"
                item_widget.setToolTip(tip_text)
                lbl_name.setToolTip(tip_text)
                lbl_val.setToolTip(tip_text)
                bar.setToolTip(tip_text)

                self.hist_clicks_container.addWidget(item_widget)
        except Exception as e:
            logger.error(f"刷新历史点击榜异常: {e}")

    def _update_rank_display(self) -> None:
        try:
            is_sess = (self._current_view_mode == "session")
            target_stats = self._session["task_stats"] if is_sess else self._history["task_stats"]

            while self.rank_container.count() > 0:
                it = self.rank_container.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.hide()
                    w.deleteLater()

            tot_m = sum(v.get("matches", 0) for v in target_stats.values())
            if not target_stats or tot_m == 0:
                empty = QLabel("暂无任务触发记录")
                empty.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px; padding: 12px;")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.rank_container.addWidget(empty)
            else:
                for name, s in sorted(target_stats.items(), key=lambda x: x[1].get("matches", 0), reverse=True):
                    cnt = s.get("matches", 0)
                    pct = (cnt / float(tot_m) * 100.0) if tot_m > 0 else 0.0
                    avg_sc = (s.get("total_score", 0.0) / float(cnt)) if cnt > 0 else 0.0

                    row_widget = QWidget()
                    row = QHBoxLayout(row_widget)
                    row.setContentsMargins(0, 2, 0, 2)
                    row.setSpacing(8)

                    lbl_n = QLabel()
                    lbl_n.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
                    lbl_n.setText(lbl_n.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, 92))
                    lbl_n.setToolTip(name)
                    lbl_n.setFixedWidth(95)
                    lbl_n.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {CLR_TEXT_MAIN};")

                    bar = QProgressBar()
                    bar.setFixedHeight(8)
                    bar.setTextVisible(False)
                    bar.setRange(0, 1000)
                    bar.setValue(int(pct * 10))
                    bar.setMinimumWidth(40)
                    bar.setStyleSheet(f"""
                        QProgressBar {{
                            background: #EAF4FD;
                            border: none;
                            border-radius: 4px;
                        }}
                        QProgressBar::chunk {{
                            background: {CLR_SIDEBAR_ACT};
                            border-radius: 4px;
                        }}
                    """)

                    lbl_s = QLabel(f"{cnt}次 ({pct:.0f}%) · 均分{avg_sc:.0f}%")
                    lbl_s.setFixedWidth(135)
                    lbl_s.setAlignment(Qt.AlignmentFlag.AlignRight)
                    lbl_s.setStyleSheet(f"font-size: 10px; color: {CLR_TEXT_SUB};")

                    row.addWidget(lbl_n)
                    row.addWidget(bar, 1)
                    row.addWidget(lbl_s)
                    self.rank_container.addWidget(row_widget)
        except Exception as e:
            logger.error(f"刷新排行异常: {e}")

    def _on_mode_switched(self, mode: str) -> None:
        try:
            self._current_view_mode = mode
            self.btn_mode_session.setChecked(mode == "session")
            self.btn_mode_history.setChecked(mode == "history")
            if self.btn_zoom:
                self.btn_zoom.setVisible(mode == "session")
            self._update_ui_display()
            self._refresh_logs_display()
            if mode == "history" and hasattr(self, "_hist_resize_timer"):
                self._hist_resize_timer.start(0)
            if self._scatter_dialog and self._scatter_dialog.isVisible():
                QToolTip.hideText()
                self._scatter_dialog.update()
        except Exception as e:
            logger.error(f"模式切换异常: {e}")

    def _on_clear_clicked(self) -> None:
        """清空统计数据，清空所有容器与控件并立即存盘落库 (显式修复并重置保护标志)."""
        try:
            if self._running:
                return
            box = QMessageBox(self)
            box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            box.setWindowTitle("确认清空")
            box.setText("确定要清空全部统计数据吗？此操作不可撤销。")
            btn_yes = box.addButton("确定清空", QMessageBox.ButtonRole.YesRole)
            btn_no = box.addButton("取消", QMessageBox.ButtonRole.NoRole)
            box.setDefaultButton(btn_no)
            box.setEscapeButton(btn_no)
            box.setStyleSheet(f"""
                QMessageBox {{ background: {CLR_CARD_BG}; }}
                QMessageBox QLabel {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
                QPushButton {{
                    background: {CLR_CARD_BG}; border: 1px solid {CLR_CARD_BORDER};
                    border-radius: 6px; padding: 6px 16px; font-size: 12px;
                    color: {CLR_TEXT_MAIN}; min-width: 60px;
                }}
                QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
            """)
            box.exec()
            if box.clickedButton() == btn_yes:
                if self._running:
                    logger.warning("引擎已在弹窗期间启动，放弃清空统计以保护正在运行的数据")
                    return
                self._reset_all_stats()
        except Exception as e:
            logger.error(f"清空统计异常: {e}")

    def _reset_all_stats(self) -> None:
        """原子级重置全部内存数据与持久化配置."""
        self._stats_load_failed = False
        self._history = {
            "total_run_seconds": 0.0, "total_scans": 0, "total_scan_cost_ms": 0.0,
            "total_matches": 0, "total_clicks": 0, "task_stats": {},
        }
        self._session = self._create_empty_stats()
        self._session_logs.clear()
        self._history_logs.clear()
        self._scatter_points.clear()
        self._trend_buckets.clear()
        self._update_ui_display()
        self._refresh_logs_display()
        if self._scatter_dialog and self._scatter_dialog.isVisible():
            QToolTip.hideText()
            self._scatter_dialog.update()
        if self._main_window and hasattr(self._main_window, "_save_config"):
            self._main_window._save_config()
        if self._main_window and hasattr(self._main_window, "_update_remote_status_cache"):
            self._main_window._update_remote_status_cache()

    def _on_copy_logs_clicked(self, btn: QPushButton) -> None:
        try:
            texts = [
                self.list_logs.item(i).text()
                for i in range(self.list_logs.count())
                if self.list_logs.item(i).data(Qt.ItemDataRole.UserRole) != "placeholder"
            ]
            QApplication.clipboard().setText("\n".join(texts))
            btn.setText("已复制！")
            def _restore():
                try:
                    btn.setText("复制记录")
                except RuntimeError:
                    pass
            QTimer.singleShot(1500, _restore)
        except Exception as e:
            logger.error(f"复制日志异常: {e}")

    def on_task_renamed(self, old_name: str, new_name: str) -> None:
        """任务改名安全合并迁移，加权合并匹配次数与点击数，杜绝统计分叉."""
        try:
            if not old_name or not new_name or old_name == new_name:
                return
            for target_dict in (self._session["task_stats"], self._history["task_stats"]):
                if old_name in target_dict:
                    old_stat = target_dict[old_name]
                    if not isinstance(old_stat, dict):
                        target_dict.pop(old_name, None)
                        continue
                    target_dict.pop(old_name)
                    if new_name in target_dict:
                        if not isinstance(target_dict[new_name], dict):
                            target_dict[new_name] = {"matches": 0, "clicks": 0, "total_score": 0.0}
                        target_dict[new_name]["matches"] += old_stat.get("matches", 0)
                        target_dict[new_name]["clicks"] += old_stat.get("clicks", 0)
                        target_dict[new_name]["total_score"] += old_stat.get("total_score", 0.0)
                    else:
                        target_dict[new_name] = old_stat

            # 同步更新散点大图队列中的已有点任务名（PRE-05）
            if hasattr(self, "_scatter_points") and self._scatter_points:
                new_queue = collections.deque(maxlen=self._scatter_points.maxlen)
                for pt in self._scatter_points:
                    if pt.task_name == old_name:
                        new_queue.append(ScatterPoint(pt.nx, pt.ny, pt.tx, pt.ty, new_name, pt.timestamp_str))
                    else:
                        new_queue.append(pt)
                self._scatter_points = new_queue

            self._update_ui_display()
        except Exception as e:
            logger.error(f"任务改名统计迁移异常: {e}")
