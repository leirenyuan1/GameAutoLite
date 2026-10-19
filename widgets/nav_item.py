"""
侧边栏导航项 (widgets/nav_item.py)
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel

from styles.colors import CLR_SIDEBAR_ACT, CLR_SIDEBAR_SEL, CLR_SIDEBAR_TEXT
from styles.icons import set_label_icon, ICON_NAV


class NavItem(QWidget):
    """侧边栏导航菜单项."""

    clicked = pyqtSignal()

    def __init__(self, icon_key: str, label: str, parent=None):
        super().__init__(parent)
        self._selected = False
        self._icon_key = icon_key
        self.setObjectName("nav_item")
        # QWidget 子类默认不绘制 QSS 背景，需显式开启
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(8)

        self.icon_label = QLabel()
        self.icon_label.setFixedWidth(20)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text_label = QLabel(label)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label, 1)
        self._update_style()

    def _update_style(self) -> None:
        if self._selected:
            self.text_label.setStyleSheet(
                f"color: {CLR_SIDEBAR_ACT}; font-size: 13px; font-weight: bold;"
            )
            set_label_icon(self.icon_label, self._icon_key, CLR_SIDEBAR_ACT, ICON_NAV)
            # #nav_item 精确选择器：只给自身画整块背景，不级联到图标/文字子控件
            self.setStyleSheet(
                f"#nav_item {{ background: {CLR_SIDEBAR_SEL}; border-radius: 8px; }}"
            )
        else:
            self.text_label.setStyleSheet(
                f"color: {CLR_SIDEBAR_TEXT}; font-size: 13px;"
            )
            set_label_icon(self.icon_label, self._icon_key, CLR_SIDEBAR_TEXT, ICON_NAV)
            self.setStyleSheet("#nav_item { background: transparent; }")

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_style()

    def enterEvent(self, event) -> None:
        if not self._selected:
            self.setStyleSheet(
                "#nav_item { background: rgba(33,150,243,0.08); border-radius: 8px; }"
            )
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._update_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

