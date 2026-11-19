"""
远程监控HTTP服务器 (remote_server.py)
功能：提供局域网HTTP服务，供手机端查看状态、截图、控制启停
"""

import hmac
import secrets
import socket
import threading
import json
import cv2
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse
from PyQt6.QtCore import QMetaObject, Qt

from image_engine import take_screenshot, close_thread_sct
from pages.remote_template import MOBILE_HTML_TEMPLATE


class RemoteHTTPServer(ThreadingMixIn, HTTPServer):
    """支持多线程处理的HTTP服务器"""
    daemon_threads = True
    
    def __init__(self, main_window, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.main_window = main_window


class StatusHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""
    
    def log_message(self, format, *args):
        """禁用默认日志输出"""
        pass
    
    def send_json(self, data, code=200):
        """发送JSON响应（默认200, no-store 防止被缓存）"""
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _authorized(self) -> bool:
        """校验 X-Auth-Token 是否等于服务器当前 token（恒时比较）.
        注意: 空 token 时无条件拒绝（防止 ''=='' 绕过）; compare_digest 只接受 bytes. """
        server_token = getattr(self.server, "token", None)
        if not server_token:
            return False
        supplied = self.headers.get("X-Auth-Token", "")
        return hmac.compare_digest(
            server_token.encode("utf-8"), supplied.encode("utf-8"))

    def send_unauthorized(self):
        self.send_json(
            {"status": "unauthorized", "message": "无效或缺失访问令牌"}, code=401)

    def do_GET(self):
        # 解析路径，去掉查询参数（如 ?t=1234567890）
        path = urlparse(self.path).path

        if path == '/':
            # 豁免鉴权: 页面需先加载, 令牌输入卡在这里; no-store 防旧页面缓存
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(MOBILE_HTML_TEMPLATE.encode('utf-8'))
        elif path == '/ping':
            # 豁免鉴权: 连通性探测, 无敏感数据
            self.send_json({"status": "ok"})
        elif path == '/status':
            if not self._authorized():
                self.send_unauthorized()
                return
            main_win = self.server.main_window
            with main_win._remote_status_lock:
                status = main_win._remote_status_cache.copy()
            self.send_json(status)
        elif path == '/screenshot':
            if not self._authorized():
                self.send_unauthorized()
                return
            self.handle_screenshot()
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/toggle':
            if not self._authorized():
                self.send_unauthorized()
                return
            main_win = self.server.main_window
            QMetaObject.invokeMethod(
                main_win,
                "_toggle_engine",
                Qt.ConnectionType.QueuedConnection
            )
            self.send_json({"status": "ok"})
        else:
            self.send_error(404)
    
    def handle_screenshot(self):
        """处理截图请求（数据准备与发送分离，避免响应损坏）"""
        try:
            # 先完成所有数据准备，再发送响应
            try:
                img = take_screenshot()
                success, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if not success:
                    raise RuntimeError("JPEG编码失败")
                data = buffer.tobytes()
            except Exception as e:
                # 数据准备阶段失败，此时还没发任何响应，可以安全发500
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(f"截图失败: {e}".encode('utf-8'))
                return
            # 数据准备成功，发送200
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
        finally:
            close_thread_sct()


def _is_blacklisted_ip(ip: str) -> bool:
    """检查 IP 是否属于黑名单 (0.*, 127.*, 169.254.*, 组播/保留地址 >= 224)"""
    if not ip:
        return True
    parts = ip.split(".")
    if len(parts) != 4:
        return True
    try:
        p0, p1 = int(parts[0]), int(parts[1])
    except ValueError:
        return True
    if p0 == 0 or p0 == 127:
        return True
    if p0 == 169 and p1 == 254:
        return True
    if p0 >= 224:
        return True
    return False


def _ip_priority(ip: str) -> int:
    """网段优先级：192.168.* (0) > 10.* (1) > 172.16~31.* (2) > 100.64~127.* (Tailscale等, 3) > 198.18~19.* (Mihomo TUN等, 4) > 其它 (5)"""
    try:
        parts = ip.split(".")
        p0, p1 = int(parts[0]), int(parts[1])
        if p0 == 192 and p1 == 168:
            return 0
        if p0 == 10:
            return 1
        if p0 == 172 and 16 <= p1 <= 31:
            return 2
        if p0 == 100 and 64 <= p1 <= 127:
            return 3
        if p0 == 198 and (p1 == 18 or p1 == 19):
            return 4
    except Exception:
        pass
    return 5


def get_local_ips() -> list[str]:
    """获取本机所有可用局域网 IPv4 地址列表（网段优先级 + 默认路由优先排序）."""
    candidates: set[str] = set()
    udp_ip: str = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not _is_blacklisted_ip(ip):
                udp_ip = ip
                candidates.add(ip)
        finally:
            s.close()
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = item[4][0]
            if ip and not _is_blacklisted_ip(ip):
                candidates.add(ip)
    except Exception:
        pass

    if not candidates:
        return ["127.0.0.1"]

    # 排序键：(_ip_priority(ip), 0 if ip == udp_ip else 1, ip)，确保常规局域网第一、同网段下默认路由优先
    return sorted(candidates, key=lambda ip: (_ip_priority(ip), 0 if ip == udp_ip else 1, ip))


def get_local_ip() -> str:
    return get_local_ips()[0]


def start_server(main_window, max_port_attempts: int = 10) -> tuple[HTTPServer, threading.Thread, int]:
    """
    启动HTTP服务器（支持多线程，直接在循环中尝试绑定端口）
    :return: (server, thread, port) 服务器实例、线程、实际端口号
    :raises RuntimeError: 启动失败时抛出
    """
    start_port = 8080
    
    # 直接在循环中尝试绑定端口，避免TOCTOU竞态
    for port in range(start_port, start_port + max_port_attempts):
        try:
            server = RemoteHTTPServer(main_window, ('', port), StatusHandler)
            break
        except OSError:
            # 端口被占用或权限不足，继续尝试下一个端口
            continue
    else:
        raise RuntimeError(f"无法找到可用端口（已尝试 {start_port}-{start_port + max_port_attempts - 1}）")

    # 每次启动随机生成访问令牌（不持久化; 必须在线程启动前赋值, 建立 happens-before）
    server.token = secrets.token_urlsafe(9)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, port


def stop_server_async(server: HTTPServer, thread: threading.Thread = None) -> None:
    """异步停止HTTP服务器（不阻塞UI线程）
    thread参数预留，当前不使用（daemon线程会随进程自动退出）
    """
    def _stop():
        if server:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass
    
    # 在daemon线程中执行关闭，不阻塞调用方
    shutdown_thread = threading.Thread(target=_stop, daemon=True)
    shutdown_thread.start()
