from __future__ import annotations
from typing import TYPE_CHECKING

import collections
import time
from dataclasses import dataclass

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import (
    QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFrame,
    QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout,
    QWidget,
)

from styles.colors import (
    CLR_BTN_PRIMARY, CLR_CARD_BG, CLR_CARD_BORDER, CLR_CARD_HEADER,
    CLR_CONTENT_BG, CLR_SIDEBAR_ACT, CLR_TEXT_MAIN, CLR_TEXT_SUB,
)

if TYPE_CHECKING:
    from pages.dashboard_page import DashboardPage


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
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setStyleSheet(f"background: {CLR_CONTENT_BG};")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        is_history, pts = self._dashboard.get_scatter_snapshot()
        if is_history:
            QToolTip.hideText()
            painter.setPen(QColor(CLR_TEXT_SUB))
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "历史模式不提供实时分布")
            return

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
        is_history, pts = self._dashboard.get_scatter_snapshot()
        if is_history:
            QToolTip.hideText()
            if self._hovered_pt is not None:
                self._hovered_pt = None
                self.update()
            return
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


class _WheelIgnoredComboBox(QComboBox):
    """滚轮事件交给父级滚动区域处理，不改变当前选项。"""

    def wheelEvent(self, event) -> None:
        event.ignore()


class FullTaskStatsDialog(QDialog):
    """全量任务统计明细，按全局名次搜索并支持四维排序。"""

    def __init__(self, dashboard: DashboardPage, focus: str = "matches"):
        super().__init__(parent=dashboard)
        self._dashboard = dashboard
        self.setWindowTitle("全部任务统计明细")
        self.resize(760, 480)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(
            f"QDialog {{ background: {CLR_CONTENT_BG}; color: {CLR_TEXT_MAIN}; }}"
            f"QLineEdit, QComboBox {{ background: white; color: {CLR_TEXT_MAIN}; "
            f"selection-background-color: {CLR_BTN_PRIMARY}; selection-color: white; }}"
            f"QComboBox QAbstractItemView {{ background: white; color: {CLR_TEXT_MAIN}; "
            f"selection-background-color: {CLR_BTN_PRIMARY}; selection-color: white; }}"
            f"QTableWidget {{ background: {CLR_CARD_BG}; border: 1px solid {CLR_CARD_BORDER}; "
            f"border-radius: 6px; gridline-color: {CLR_CARD_HEADER}; color: {CLR_TEXT_MAIN}; "
            f"selection-background-color: {CLR_BTN_PRIMARY}; selection-color: white; }}"
            f"QTableWidget::item:selected {{ background: {CLR_BTN_PRIMARY}; color: white; }}"
            f"QHeaderView::section {{ background: {CLR_CARD_HEADER}; color: {CLR_TEXT_MAIN}; "
            f"font-weight: bold; border: none; padding: 4px 6px; }}"
        )
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.lbl_summary = QLabel()
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("按任务名称搜索过滤...")
        self.combo_sort = _WheelIgnoredComboBox()
        for label, key in (("触发次数", "matches"), ("累计点击", "clicks"),
                           ("平均精度", "score"), ("连击率", "ratio")):
            self.combo_sort.addItem(label, key)
        toolbar.addWidget(self.lbl_summary)
        toolbar.addWidget(self.edit_search, 1)
        toolbar.addWidget(self.combo_sort)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["排名", "任务名称", "触发次数", "触发占比", "均分", "累计点击", "点击占比", "连击率"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        self.edit_search.textChanged.connect(lambda _text: self.refresh_data())
        self.combo_sort.currentIndexChanged.connect(lambda _index: self.refresh_data())
        self.refresh_data(focus=focus)

    def refresh_data(self, focus: str | None = None) -> None:
        """刷新只读快照；未传 focus 时保留用户当前排序。"""
        if focus in ("matches", "clicks"):
            blocked = self.combo_sort.blockSignals(True)
            self.combo_sort.setCurrentIndex(self.combo_sort.findData(focus))
            self.combo_sort.blockSignals(blocked)
        mode, task_stats, tot_m, denom_clicks = self._dashboard.get_full_stats_snapshot()
        rows = []
        for name, stats in task_stats.items():
            if not isinstance(stats, dict):
                continue
            matches, clicks = stats.get("matches", 0), stats.get("clicks", 0)
            if matches <= 0 and clicks <= 0:
                continue
            avg = stats.get("total_score", 0.0) / float(matches) if matches > 0 else 0.0
            ratio = clicks / float(matches) if matches > 0 else 0.0
            total_score = stats.get("total_score", 0.0)
            rows.append((str(name), matches, clicks, avg, ratio, total_score))
        sort_key_map = {
            # 与主界面触发榜保持相同的决胜规则。
            "matches": lambda row: (row[1], row[5]),
            # 与主界面点击榜保持相同的决胜规则；稳定排序保留完全并列项原顺序。
            "clicks": lambda row: (row[2], row[1]),
            "score": lambda row: (row[3], row[1], row[2]),
            "ratio": lambda row: (row[4], row[2], row[1]),
        }
        key_fn = sort_key_map.get(self.combo_sort.currentData(), sort_key_map["matches"])
        rows.sort(key=key_fn, reverse=True)
        query = self.edit_search.text().strip().lower()
        visible = [(rank, row) for rank, row in enumerate(rows, 1) if query in row[0].lower()]
        scroll = self.table.verticalScrollBar().value()
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(visible))
            for r, (rank, (name, matches, clicks, avg, ratio, _total_score)) in enumerate(visible):
                match_pct = matches / float(tot_m) * 100.0 if tot_m > 0 else 0.0
                click_pct = clicks / float(denom_clicks) * 100.0 if denom_clicks > 0 else 0.0
                values = [str(rank), name, f"{matches:,}", f"{match_pct:.1f}%", f"{avg:.1f}%",
                          f"{clicks:,}", f"{click_pct:.1f}%", f"{ratio:.2f}"]
                for c, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    if c != 1:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(r, c, item)
            label = "本次运行" if mode == "session" else "历史累计"
            self.lbl_summary.setText(f"{label} · 共 {len(rows)} 项 · 当前显示 {len(visible)} 项")
            self.table.verticalScrollBar().setValue(scroll)
        finally:
            self.table.setUpdatesEnabled(True)
