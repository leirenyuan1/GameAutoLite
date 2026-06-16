"""远程监控页面 (pages/remote_monitor_page.py)"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage, QIntValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QLineEdit, QFrame, QScrollArea,
)

from styles.colors import (
    CLR_TEXT_MAIN, CLR_TEXT_SUB, CLR_CARD_BG, CLR_CARD_BORDER,
    CLR_BTN_PRIMARY, CLR_CONTENT_BG,
)
from pages.utils import make_settings_card

if TYPE_CHECKING:
    from main_window import MainWindow


class RemoteMonitorPage(QWidget):
    """远程监控页面：提供局域网HTTP服务，手机扫码查看状态和控制。"""

    def __init__(self, main_win: 'MainWindow', parent=None):
        super().__init__(parent)
        self._main_win = main_win
        self._server = None
        self._thread = None
        self._port = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建远程监控页面"""
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # 顶部工具栏
        toolbar = QWidget()
        toolbar.setMinimumHeight(32)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        title = QLabel("远程监控")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {CLR_TEXT_MAIN};"
        )
        toolbar_layout.addWidget(title)
        toolbar_layout.addStretch(1)
        page_layout.addWidget(toolbar)

        # 可滚动设置区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # ---- 开关卡片 ----
        switch_card, switch_layout = make_settings_card("远程监控服务")
        
        self.chk_toggle = QCheckBox("启用远程监控")
        self.chk_toggle.setChecked(False)
        self.chk_toggle.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        # 重要：chk_toggle的clicked信号必须在所有控件初始化完成后最后连接
        # 避免初始化时意外触发_toggle_service
        switch_layout.addWidget(self.chk_toggle)
        
        desc = QLabel("开启后，手机可通过局域网扫码访问查看状态和控制引擎")
        desc.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 11px;")
        desc.setWordWrap(True)
        switch_layout.addWidget(desc)
        layout.addWidget(switch_card)

        # ---- 二维码卡片 ----
        qr_card, qr_layout = make_settings_card("扫码访问")
        
        # 提示文字（服务关闭时显示）
        self.hint_label = QLabel("开启后手机可通过局域网访问")
        self.hint_label.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_layout.addWidget(self.hint_label)
        
        # 二维码容器（服务开启时显示）
        self.qrcode_widget = QWidget()
        qr_container_layout = QVBoxLayout(self.qrcode_widget)
        qr_container_layout.setContentsMargins(0, 0, 0, 0)
        qr_container_layout.setSpacing(8)
        
        self.qrcode_label = QLabel()
        self.qrcode_label.setFixedSize(200, 200)
        self.qrcode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qrcode_label.setStyleSheet(
            f"border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px;"
        )
        qr_container_layout.addWidget(self.qrcode_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # URL容器
        self.url_widget = QWidget()
        url_layout = QHBoxLayout(self.url_widget)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(8)
        
        self.label_url = QLabel()
        self.label_url.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-size: 12px;")
        self.label_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        url_layout.addWidget(self.label_url, 1)
        
        btn_copy = QPushButton("复制链接")
        btn_copy.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 10px; font-size: 11px; color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        btn_copy.clicked.connect(self._copy_link)
        url_layout.addWidget(btn_copy)
        
        qr_container_layout.addWidget(self.url_widget)
        qr_layout.addWidget(self.qrcode_widget)
        
        # 初始隐藏二维码和URL
        self.qrcode_widget.hide()
        self.url_widget.hide()
        
        layout.addWidget(qr_card)

        # ---- 信息卡片 ----
        info_card, info_layout = make_settings_card("连接信息")
        
        info_row1 = QHBoxLayout()
        info_row1.addWidget(QLabel("端口："))
        self.label_port = QLabel("—")
        self.label_port.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-weight: bold;")
        info_row1.addWidget(self.label_port)
        info_row1.addStretch(1)
        info_layout.addLayout(info_row1)
        
        info_row2 = QHBoxLayout()
        info_row2.addWidget(QLabel("局域网IP："))
        self.label_ip = QLabel("—")
        self.label_ip.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-weight: bold;")
        info_row2.addWidget(self.label_ip)
        info_row2.addStretch(1)
        info_layout.addLayout(info_row2)
        
        layout.addWidget(info_card)

        layout.addStretch(1)

        scroll.setWidget(container)
        page_layout.addWidget(scroll, 1)

        # 信号连接（在所有控件初始化完成后）
        self.chk_toggle.clicked.connect(self._toggle_service)

    def _toggle_service(self):
        """切换服务启停"""
        if self._server is None:
            # 启动服务
            try:
                from remote_server import start_server
                self._server, self._thread, self._port = start_server(self._main_win)
                self._main_win._remote_server = self._server
                self._main_win._remote_thread = self._thread
                self._update_ui_running()
            except Exception as e:
                msg = self._main_win._styled_msgbox()
                msg.setWindowTitle("远程监控服务启动失败")
                msg.setText(str(e))
                self._main_win._exec_msgbox_centered(msg)
                self.chk_toggle.setChecked(False)
        else:
            # 停止服务（异步，不阻塞UI线程）
            from remote_server import stop_server_async
            stop_server_async(self._server, self._thread)
            self._server = None
            self._thread = None
            self._port = None
            self._main_win._remote_server = None
            self._main_win._remote_thread = None
            self._update_ui_stopped()

    def _update_ui_running(self):
        """更新UI为运行状态"""
        from remote_server import get_local_ip
        ip = get_local_ip()
        
        # 更新底部信息区
        self.label_port.setText(str(self._port))
        
        # 检测IP是否有效（127.0.0.1表示无法获取局域网IP）
        if ip == "127.0.0.1":
            self.qrcode_widget.hide()
            self.url_widget.hide()
            self.hint_label.show()
            self.hint_label.setText("⚠ 无法获取局域网IP\n请检查网络连接")
            self.hint_label.setStyleSheet("color: #EF5350; font-size: 12px;")
            self.label_ip.setText("127.0.0.1（本机）")
            return
        
        url = f"http://{ip}:{self._port}"
        self.label_url.setText(url)
        self._update_qrcode(url)
        self.qrcode_widget.show()
        self.url_widget.show()
        self.hint_label.hide()
        self.label_ip.setText(ip)

    def _update_ui_stopped(self):
        """更新UI为停止状态"""
        self.qrcode_widget.hide()
        self.url_widget.hide()
        self.hint_label.show()
        self.hint_label.setText("开启后手机可通过局域网访问")
        self.hint_label.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")
        self.label_port.setText("—")
        self.label_ip.setText("—")

    def _update_qrcode(self, url: str):
        """更新二维码（带异常保护）"""
        try:
            import qrcode
            from io import BytesIO
            
            qr = qrcode.QRCode(box_size=10, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            # 转换为QPixmap
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            qimg = QImage()
            ok = qimg.loadFromData(buffer.read())
            if not ok:
                raise RuntimeError("QImage加载PNG数据失败")
            pixmap = QPixmap.fromImage(qimg)
            
            self.qrcode_label.setPixmap(pixmap.scaled(
                200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
        except Exception:
            # 二维码生成失败时，显示文字URL供用户手动输入
            self.qrcode_label.setText(url)
            self.qrcode_label.setStyleSheet("font-size: 10px; color: #666; word-break: break-all;")

    def _copy_link(self):
        """复制链接到剪贴板"""
        from PyQt6.QtWidgets import QApplication
        url = self.label_url.text()
        if url and url != "—":
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            # 短暂显示复制成功提示
            original_text = self.label_url.text()
            self.label_url.setText("✅ 已复制！")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self.label_url.setText(original_text))
