"""
远程监控HTTP服务器 (remote_server.py)
功能：提供局域网HTTP服务，供手机端查看状态、截图、控制启停
"""

import socket
import threading
import json
import cv2
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse
from PyQt6.QtCore import QMetaObject, Qt

from image_engine import take_screenshot


# 手机端HTML模板（必须用普通字符串，不能用f-string，HTML中有大量{}）
MOBILE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GameAutoLite 远程监控</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #f5f5f5;
            padding: 20px;
            max-width: 400px;
            margin: 0 auto;
        }
        .card {
            background: white;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .title {
            text-align: center;
            font-size: 18px;
            font-weight: bold;
            margin-bottom: 16px;
        }
        .status-row {
            display: flex;
            align-items: center;
            padding: 8px 0;
            font-size: 14px;
        }
        .status-icon { width: 24px; text-align: center; }
        .status-text { flex: 1; }
        .btn {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin: 8px 0;
        }
        .btn-start { background: #43A047; color: white; }
        .btn-stop { background: #EF5350; color: white; }
        .btn-screenshot { background: #2196F3; color: white; }
        .btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .frequency-selector {
            display: flex;
            justify-content: center;
            gap: 8px;
            margin: 12px 0;
        }
        .freq-btn {
            padding: 6px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            background: white;
            cursor: pointer;
        }
        .freq-btn.active { background: #2196F3; color: white; border-color: #2196F3; }
        #screenshot { 
            width: 100%; 
            border-radius: 8px; 
            margin-top: 12px;
            display: none;
        }
        #status-bar {
            text-align: center;
            font-size: 12px;
            color: #43A047;
            margin-top: 8px;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="title">🎮 GameAutoLite</div>
        <div id="status-bar">🔄 连接中...</div>
    </div>
    
    <div class="card">
        <div class="status-row">
            <span class="status-icon" id="icon1">⚡</span>
            <span class="status-text" id="line1">加载中...</span>
        </div>
        <div class="status-row">
            <span class="status-icon" id="icon2">🖱</span>
            <span class="status-text" id="line2">—</span>
        </div>
        <div class="status-row">
            <span class="status-icon" id="icon3">⏱</span>
            <span class="status-text" id="line3">—</span>
        </div>
    </div>
    
    <div class="card">
        <button class="btn btn-start" id="toggle-btn" onclick="toggleEngine()">▶ 开始</button>
    </div>
    
    <div class="card">
        <div style="text-align: center; font-size: 14px; margin-bottom: 8px;">刷新频率</div>
        <div class="frequency-selector">
            <button class="freq-btn" onclick="setFrequency(1000, this)">1秒</button>
            <button class="freq-btn active" onclick="setFrequency(2000, this)">2秒</button>
            <button class="freq-btn" onclick="setFrequency(5000, this)">5秒</button>
        </div>
    </div>
    
    <div class="card">
        <button class="btn btn-screenshot" id="screenshot-btn" onclick="loadScreenshot()">📷 查看屏幕</button>
        <img id="screenshot" alt="屏幕截图" onerror="this.alt='截图失败，请重试'">
    </div>

    <script>
        let refreshInterval = 2000;
        let timer = null;
        
        function fetchWithTimeout(url, options = {}, timeout = 3000) {
            return Promise.race([
                fetch(url, options),
                new Promise((_, reject) => 
                    setTimeout(() => reject(new Error('timeout')), timeout)
                )
            ]);
        }
        
        function updateStatus() {
            fetchWithTimeout('/status', {}, 2000)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('icon1').textContent = data.icon1;
                    document.getElementById('line1').textContent = data.line1;
                    document.getElementById('icon2').textContent = data.icon2;
                    document.getElementById('line2').textContent = data.line2;
                    document.getElementById('icon3').textContent = data.icon3;
                    document.getElementById('line3').textContent = data.line3;
                    
                    const btn = document.getElementById('toggle-btn');
                    if (data.is_running) {
                        btn.textContent = '⏹ 停止';
                        btn.className = 'btn btn-stop';
                    } else {
                        btn.textContent = '▶ 开始';
                        btn.className = 'btn btn-start';
                    }
                    
                    document.getElementById('status-bar').textContent = '✅ 已连接';
                    document.getElementById('status-bar').style.color = '#43A047';
                })
                .catch(() => {
                    document.getElementById('status-bar').textContent = '⚠ 连接断开，请刷新页面';
                    document.getElementById('status-bar').style.color = '#EF5350';
                });
        }
        
        function toggleEngine() {
            const btn = document.getElementById('toggle-btn');
            btn.disabled = true;
            fetchWithTimeout('/toggle', { method: 'POST' }, 3000)
                .then(() => { setTimeout(updateStatus, 500); })
                .catch(() => { updateStatus(); })
                .finally(() => { setTimeout(() => { btn.disabled = false; }, 1500); });
        }
        
        function loadScreenshot() {
            const btn = document.getElementById('screenshot-btn');
            const img = document.getElementById('screenshot');
            btn.textContent = '⏳ 加载中...';
            btn.disabled = true;
            
            const newImg = new Image();
            newImg.onload = () => {
                img.src = newImg.src;
                img.style.display = 'block';
                btn.textContent = '📷 查看屏幕';
                btn.disabled = false;
            };
            newImg.onerror = () => {
                img.alt = '截图失败，请重试';
                img.style.display = 'block';
                btn.textContent = '📷 查看屏幕';
                btn.disabled = false;
            };
            newImg.src = '/screenshot?t=' + Date.now();
        }
        
        function setFrequency(ms, btn) {
            refreshInterval = ms;
            if (timer) clearInterval(timer);
            timer = setInterval(updateStatus, ms);
            document.querySelectorAll('.freq-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        }
        
        updateStatus();
        timer = setInterval(updateStatus, refreshInterval);
    </script>
</body>
</html>"""


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
    
    def send_json(self, data):
        """发送JSON响应"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def do_GET(self):
        # 解析路径，去掉查询参数（如 ?t=1234567890）
        path = urlparse(self.path).path
        
        if path == '/status':
            main_win = self.server.main_window
            with main_win._remote_status_lock:
                status = main_win._remote_status_cache.copy()
            self.send_json(status)
        elif path == '/ping':
            self.send_json({"status": "ok"})
        elif path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(MOBILE_HTML_TEMPLATE.encode('utf-8'))
        elif path == '/screenshot':
            self.handle_screenshot()
        else:
            self.send_error(404)
    
    def do_POST(self):
        path = urlparse(self.path).path
        
        if path == '/toggle':
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
        self.end_headers()
        self.wfile.write(data)


def get_local_ip() -> str:
    """获取本机局域网IP地址"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


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
