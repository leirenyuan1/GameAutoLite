"""
线性描边 SVG 图标库（lucide 风格）
=================================
统一规格: viewBox="0 0 24 24", fill="none", stroke 2px 圆头圆角.
颜色运行时注入: 桌面端用真实颜色替换（QSvgRenderer 不解析 currentColor）,
移动端 HTML 直接使用 currentColor 交给浏览器渲染.

对外接口:
  - svg(key, color) -> str             # 完整的彩色 SVG 字符串（桌面上色用）
  - svg_element(key, color) -> str     # 单个 <svg> 片段（手机端 innerHTML 用, currentColor）
  - pixmap(key, color, size, dpr) -> QPixmap   # 渲染位图（带缓存）
  - set_label_icon(label, key, color, size)    # QLabel 文本图标 -> 位图
  - button_icon(key, color, size, dpr) -> QIcon
  - IconButton                         # 无文本小图标按钮, hover 代码切图

仅允许主线程调用: QPixmap/QIcon 非线程安全.
"""

import functools
import logging

from PyQt6.QtCore import QByteArray, QRectF
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QLabel, QPushButton

logger = logging.getLogger(__name__)

# ---- 尺寸常量（对齐现有布局槽位） ----
ICON_NAV = 15      # 导航项 20px 槽位
ICON_STATUS = 14   # 状态行 18px 槽位
ICON_BTN = 14      # 文本按钮
ICON_CARD = 16     # 卡片头小按钮（32px/30px 按钮内）

# ---- 图形定义（无颜色, 要素字符串拼接） ----
_BODY: dict[str, str] = {
    # ————— 状态图标 —————
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "mouse": (
        '<path d="M12 3a7 7 0 0 1 7 7v4a7 7 0 0 1-14 0v-4a7 7 0 0 1 7-7z"/>'
        '<path d="M12 6.5v4"/>'
    ),
    "timer": (
        '<circle cx="12" cy="13.5" r="7"/>'
        '<path d="M9 2.5h6"/>'
        '<path d="M12 2.5v4"/>'
        '<path d="M12 13.5v-3.5"/>'
        '<path d="M12 13.5h2.2"/>'
    ),
    "search": '<circle cx="11" cy="11" r="6.5"/>' '<path d="M15.7 15.7 21 21"/>',
    "target": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<circle cx="12" cy="12" r="4.5"/>'
        '<circle cx="12" cy="12" r="1"/>'
    ),
    "camera": (
        '<path d="M4.5 7.5a2 2 0 0 1 2-2H9l1.5-2h4l1.5 2h2.5a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-12a2 2 0 0 1-2-2z"/>'
        '<circle cx="12" cy="12.5" r="3.5"/>'
    ),
    "pencil": '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>',
    "alert-triangle": (
        '<path d="M10.3 4.9 2.6 17.8a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.9a2 2 0 0 0-3.4 0z"/>'
        '<path d="M12 9.5v4.5"/>'
        '<path d="M12 17h.01"/>'
    ),
    "info": '<circle cx="12" cy="12" r="9"/>' '<path d="M12 11.2v5"/>' '<path d="M12 8h.01"/>',
    "octagon": (
        '<polygon points="8 2 16 2 22 8 22 16 16 22 8 22 2 16 2 8 8 2"/>'
        '<path d="M8.5 12h7"/>'
    ),
    # ————— 导航/Logo —————
    "gamepad": (
        '<rect x="3.5" y="8" width="17" height="9" rx="4.5"/>'
        '<path d="M7.5 12.5h4"/>'
        '<path d="M9.5 10.5v4"/>'
        '<circle cx="15.8" cy="10.8" r="1"/>'
        '<circle cx="18" cy="12.8" r="1"/>'
    ),
    "list": (
        '<path d="M8.5 6h12"/>'
        '<path d="M8.5 12h12"/>'
        '<path d="M8.5 18h12"/>'
        '<path d="M3.5 6h.01"/>'
        '<path d="M3.5 12h.01"/>'
        '<path d="M3.5 18h.01"/>'
    ),
    "settings": (
        # 六齿轮廓(方案G: 6 齿、细长齿杆、宽齿隙) + 中心圆孔; 描边 1.7px 比其它图标更细
        '<path stroke-width="1.7" d="M9.80 5.04 L9.97 4.99 L10.14 4.94 L10.31 4.90 L10.48 4.86 L9.84 1.83 L10.91 1.66 L12.00 1.60 L13.09 1.66 L14.16 1.83 L13.52 4.86 L13.69 4.90 L13.86 4.94 L14.03 4.99 L14.20 5.04 L16.93 6.62 L17.06 6.74 L17.18 6.86 L17.31 6.99 L17.42 7.12 L19.73 5.04 L20.41 5.89 L21.01 6.80 L21.50 7.77 L21.89 8.79 L18.94 9.74 L18.99 9.91 L19.04 10.08 L19.09 10.25 L19.13 10.42 L19.13 13.58 L19.09 13.75 L19.04 13.92 L18.99 14.09 L18.94 14.26 L21.89 15.21 L21.50 16.23 L21.01 17.20 L20.41 18.11 L19.73 18.96 L17.42 16.88 L17.31 17.01 L17.18 17.14 L17.06 17.26 L16.93 17.38 L14.20 18.96 L14.03 19.01 L13.86 19.06 L13.69 19.10 L13.52 19.14 L14.16 22.17 L13.09 22.34 L12.00 22.40 L10.91 22.34 L9.84 22.17 L10.48 19.14 L10.31 19.10 L10.14 19.06 L9.97 19.01 L9.80 18.96 L7.07 17.38 L6.94 17.26 L6.82 17.14 L6.69 17.01 L6.58 16.88 L4.27 18.96 L3.59 18.11 L2.99 17.20 L2.50 16.23 L2.11 15.21 L5.06 14.26 L5.01 14.09 L4.96 13.92 L4.91 13.75 L4.87 13.58 L4.87 10.42 L4.91 10.25 L4.96 10.08 L5.01 9.91 L5.06 9.74 L2.11 8.79 L2.50 7.77 L2.99 6.80 L3.59 5.89 L4.27 5.04 L6.58 7.12 L6.69 6.99 L6.82 6.86 L6.94 6.74 L7.07 6.62 Z"/>'
        '<circle cx="12" cy="12" r="3.8" stroke-width="1.7"/>'
    ),
    "smartphone": '<rect x="6.5" y="2" width="11" height="20" rx="2.5"/>' '<path d="M10.5 18.5h3"/>',
    # ————— 按钮图标 —————
    "play": '<path d="M7.5 4.8 18.7 12 7.5 19.2z"/>',
    "stop": '<rect x="5.5" y="5.5" width="13" height="13" rx="2"/>',
    "chevron-down": '<path d="m6 9.5 6 6 6-6"/>',
    "chevron-right": '<path d="m9.5 6 6 6-6 6"/>',
    "chevron-up": '<path d="m6 14.5 6-6 6 6"/>',
    "x": '<path d="M18 6 6 18"/>' '<path d="M6 6l12 12"/>',
    "image": (
        '<rect x="3.5" y="4" width="17" height="16" rx="2"/>'
        '<circle cx="8.7" cy="9.7" r="1.5"/>'
        '<path d="M20.5 14.5 16 10.5 8 18"/>'
    ),
    "folder": (
        '<path d="M4.5 6.5a2 2 0 0 1 2-2h4l2 2h5a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2z"/>'
    ),
    "save": (
        '<path d="M6.5 3.5h9.3l4.7 4.7v10.3a2 2 0 0 1-2 2H5.5a2 2 0 0 1-2-2V5.5a2 2 0 0 1 2-2z"/>'
        '<path d="M8.5 3.5v4h7v-4"/>'
        '<rect x="8" y="12.5" width="8" height="6.5"/>'
    ),
    "circle-plus": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M12 8v8"/>'
        '<path d="M8 12h8"/>'
    ),
    # ————— 手机端专用 —————
    "hourglass": (
        '<path d="M5.5 2.5h13"/>'
        '<path d="M5.5 21.5h13"/>'
        '<path d="M7 2.5v4.4a2 2 0 0 0 .6 1.4L12 12.8l4.4-4.5a2 2 0 0 0 .6-1.4V2.5"/>'
        '<path d="M7 21.5v-4.4a2 2 0 0 1 .6-1.4L12 11.3l4.4 4.4a2 2 0 0 1 .6 1.4v4.4"/>'
    ),
    "refresh-cw": (
        '<path d="M21 4.5v5h-5"/>'
        '<path d="M3 19.5v-5h5"/>'
        '<path d="M21 9.5a8.5 8.5 0 0 0-14.7-3.6L3 9.5"/>'
        '<path d="M3 14.5a8.5 8.5 0 0 0 14.7 3.6l3.3-3.6"/>'
    ),
    "check": '<circle cx="12" cy="12" r="9"/>' '<path d="m7.8 12.3 3 3 5.4-5.6"/>',
}

_ATTRS = (
    'fill="none" stroke="{0}" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"'
)


def svg(key: str, color: str) -> str:
    """完整彩色 SVG 字符串（桌面上色用；QSvgRenderer 需要真实颜色）. 返回值可缓存. """
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        + _ATTRS.format(color)
        + ">"
        + _BODY[key]
        + "</svg>"
    )


def svg_element(key: str, color: str = "currentColor") -> str:
    """单个 <svg> 片段（手机端 innerHTML 用, 颜色跟随 CSS, 默认 currentColor）. """
    return svg(key, color)


# ---- 渲染 ----

@functools.lru_cache(maxsize=1024)
def _render_pixmap(key: str, color: str, size: int, dpr: float) -> QPixmap:
    """渲染 size* dpr 像素并设置设备像素比. 缓存键 (key, color, size, dpr). """
    px = int(round(size * dpr))
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)  # 全透明
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    svg_str = svg(key, color)
    renderer = QSvgRenderer(QByteArray(svg_str.encode("utf-8")))
    if not renderer.isValid():
        logger.error("SVG 渲染器无法解析图标: %s", key)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def pixmap(key: str, color: str, size: int, dpr: float = 1.0) -> QPixmap:
    """渲染位图（带缓存）. """
    return _render_pixmap(key, color, max(1, int(round(size))), dpr)


def set_label_icon(label: QLabel, key: str, color: str, size: int = ICON_STATUS) -> None:
    """QLabel 文本图标 -> 位图（不触碰 label 的固定宽/对齐, 原 color 类 QSS 应删除）. """
    label.setPixmap(pixmap(key, color, size, label.devicePixelRatioF()))


def button_icon(key: str, color: str, size: int = ICON_BTN, dpr: float = 1.0) -> QIcon:
    """QPushButton.setIcon 用. """
    return QIcon(pixmap(key, color, size, dpr))


class IconButton(QPushButton):
    """无文本小图标按钮, hover 切换图标颜色（QSS :hover 不作用于 QIcon, 需代码切图）.
    用法: set_icon(key, color, hover_color) 后自动应用; 尺寸/样式由调用方设置. """

    def __init__(self, icon_key: str | None = None, color: str | None = None,
                 hover_color: str | None = None, size: int = ICON_CARD, parent=None):
        super().__init__(parent)
        self._icon_key: str | None = icon_key
        self._color = color
        self._hover_color = hover_color
        self._icon_size = size
        if icon_key is not None:
            self.set_icon(icon_key, color, hover_color)

    def set_icon(self, icon_key: str, color: str | None = None,
                 hover_color: str | None = None) -> None:
        """设置图标（color/hover_color 传 None 表示沿用旧值）. """
        self._icon_key = icon_key
        if color is not None:
            self._color = color
        if hover_color is not None:
            self._hover_color = hover_color
        self._apply_icon()

    def _apply_icon(self) -> None:
        if not self._icon_key or self._color is None:
            return
        color = self._hover_color if self.underMouse() else self._color
        self.setIcon(button_icon(
            self._icon_key, color, self._icon_size, self.devicePixelRatioF()))

    def enterEvent(self, event) -> None:
        self._apply_icon()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_icon()
        super().leaveEvent(event)


# 所有图标 key（冒烟测试用）
ALL_KEYS: tuple[str, ...] = tuple(_BODY.keys())
