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
from styles.icons import _BODY


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
        .token-input {
            width: 100%; padding: 12px; border: 1px solid #ddd;
            border-radius: 8px; font-size: 14px; margin: 8px 0;
            box-sizing: border-box;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="title">GameAutoLite</div>
        <div id="status-bar">连接中...</div>
    </div>

    <div class="card" id="token-card" style="display:none;">
        <div style="text-align:center; font-size:14px; margin-bottom:4px;">输入访问令牌</div>
        <div style="text-align:center; font-size:12px; color:#999; margin-bottom:8px;">令牌由桌面端「连接信息」卡显示，每次开启服务自动更换</div>
        <input type="text" id="token-input" class="token-input" placeholder="例如 aBcD-EfG1_H2iJ">
        <button class="btn btn-start" onclick="submitToken()">连接</button>
    </div>

    <div class="card" id="stop-card" style="display:none; background:#FFEBEE; border:1px solid #FFCDD2; color:#C62828;">
        <div style="display:flex; align-items:center; gap:8px;">
            <span id="stop-icon" style="width:20px; text-align:center;"></span>
            <span id="stop-text" style="font-size:13px; font-weight:500;"></span>
        </div>
    </div>

    <div class="card">
        <div class="status-row">
            <span class="status-icon" id="icon1"></span>
            <span class="status-text" id="line1">加载中...</span>
        </div>
        <div class="status-row">
            <span class="status-icon" id="icon2"></span>
            <span class="status-text" id="line2">—</span>
        </div>
        <div class="status-row">
            <span class="status-icon" id="icon3"></span>
            <span class="status-text" id="line3">—</span>
        </div>
        <div class="status-summary" style="margin-top: 10px; padding-top: 8px; border-top: 1px solid #E8F4FD; display: flex; justify-content: space-between; font-size: 12px; color: #7A9AB8;">
            <span>运行时长: <strong id="run-duration" style="color: #2196F3;">00:00:00</strong></span>
            <span>匹配触发: <strong id="total-matches" style="color: #43A047;">0</strong> 次</span>
        </div>
    </div>

    <div class="card">
        <button class="btn btn-start" id="toggle-btn" onclick="toggleEngine()">开始</button>
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
        <button class="btn btn-screenshot" id="screenshot-btn" onclick="loadScreenshot()">查看屏幕</button>
        <img id="screenshot" alt="屏幕截图" onerror="this.alt='截图失败，请重试'">
    </div>

    <script>
        let refreshInterval = 2000;
        let timer = null;

        // ===== 令牌鉴权状态机 =====
        // idle:  无 token / 401 -> 停轮询, 显示令牌输入卡
        // checking: 有 token 首次校验中（一次性请求）
        // valid: 校验通过 -> 恢复轮询
        let token = location.hash.startsWith('#tk=') ? location.hash.slice(4) : (localStorage.getItem('rm_token') || '');
        let authState = token ? 'checking' : 'idle';

        function authHeaders() { return { 'X-Auth-Token': token }; }

        function stopPolling() {
            if (timer) { clearInterval(timer); timer = null; }
        }
        function startPolling() {
            stopPolling();
            timer = setInterval(updateStatus, refreshInterval);
        }

        function enterTokenScreen(msg, clearToken = false) {
            authState = 'idle';
            stopPolling();
            if (clearToken) {
                token = '';
                try { localStorage.removeItem('rm_token'); } catch (e) {}
                if (location.hash.startsWith('#tk=')) {
                    try { history.replaceState(null, '', location.pathname); } catch (e) {}
                }
            }
            document.getElementById('token-card').style.display = 'block';
            document.getElementById('token-input').value = token || '';
            const bar = document.getElementById('status-bar');
            bar.textContent = msg || '需要访问令牌';
            bar.style.color = '#EF5350';
        }

        // 渲染状态卡片 (BUG-06, BUG-11: 抽取公共函数消除重复请求)
        function renderStatus(data) {
            setStatusIcon(document.getElementById('icon1'), data.icon1);
            document.getElementById('line1').textContent = data.line1;
            setStatusIcon(document.getElementById('icon2'), data.icon2);
            document.getElementById('line2').textContent = data.line2;
            setStatusIcon(document.getElementById('icon3'), data.icon3);
            document.getElementById('line3').textContent = data.line3;

            if (data.run_duration) document.getElementById('run-duration').textContent = data.run_duration;
            if (data.total_matches !== undefined) document.getElementById('total-matches').textContent = data.total_matches;

            const btn = document.getElementById('toggle-btn');
            if (data.is_running) {
                btn.innerHTML = icon('stop', 16) + ' 停止';
                btn.className = 'btn btn-stop';
            } else {
                btn.innerHTML = icon('play', 16) + ' 开始';
                btn.className = 'btn btn-start';
            }

            const stopCard = document.getElementById('stop-card');
            if (stopCard) {
                if (data.stop_reason && !data.is_running) {
                    document.getElementById('stop-icon').innerHTML = icon('octagon', 16, '#EF5350');
                    document.getElementById('stop-text').textContent = '自动停止: ' + data.stop_reason;
                    stopCard.style.display = 'block';
                } else {
                    stopCard.style.display = 'none';
                }
            }

            const bar = document.getElementById('status-bar');
            bar.innerHTML = icon('check', 16, '#43A047') + ' 已连接';
            bar.style.color = '#43A047';
        }

        // 一次性校验token: 通过 -> 落库localStorage + 恢复轮询; 401 -> 清空输入卡
        function validateAndStart() {
            authState = 'checking';
            fetchWithTimeout('/status', { headers: authHeaders() }, 3000)
                .then(r => {
                    if (r.status === 401) { enterTokenScreen('令牌无效或已过期', true); return null; }
                    if (!r.ok) throw new Error('http ' + r.status);
                    return r.json();
                })
                .then(data => {
                    if (!data) return;
                    localStorage.setItem('rm_token', token);
                    document.getElementById('token-card').style.display = 'none';
                    authState = 'valid';
                    renderStatus(data);
                    startPolling();
                })
                .catch(() => enterTokenScreen('无法连接服务器，请检查网络', false));
        }

        function submitToken() {
            const t = document.getElementById('token-input').value.trim();
            if (!t) return;
            token = t;
            validateAndStart();
        }

        // 线性描边图标（body 数据与桌面端 styles/icons.py 单一数据源）
        const ICON_BODY = {__ICON_BODY__};
        const DEFAULT_ICON_COLOR = '#7A9AB8';

        // 生成内联 SVG（color 不传时继承 currentColor）
        function icon(key, size, color) {
            size = size || 16;
            const body = ICON_BODY[key] || ICON_BODY.zap;
            const stroke = color || 'currentColor';
            return '<svg viewBox="0 0 24 24" fill="none" stroke="' + stroke +
                   '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
                   'width="' + size + '" height="' + size + '" style="vertical-align:-3px;">' +
                   body + '</svg>';
        }

        // 状态图标: 兼容对象 {key, color}（新协议）与旧字符串（防御旧缓存/旧页面）
        function setStatusIcon(el, spec) {
            if (!el) return;
            if (typeof spec === 'string') spec = { key: spec, color: DEFAULT_ICON_COLOR };
            if (!spec || !spec.key) return;
            el.innerHTML = icon(spec.key, 16, spec.color);
            el.style.color = spec.color || DEFAULT_ICON_COLOR;
        }

        function fetchWithTimeout(url, options = {}, timeout = 3000) {
            return Promise.race([
                fetch(url, options),
                new Promise((_, reject) =>
                    setTimeout(() => reject(new Error('timeout')), timeout)
                )
            ]);
        }

        function updateStatus() {
            fetchWithTimeout('/status', { headers: authHeaders() }, 2000)
                .then(r => {
                    if (r.status === 401) { enterTokenScreen('令牌无效或已过期', true); return null; }
                    if (!r.ok) throw new Error('http ' + r.status);
                    return r.json();
                })
                .then(data => {
                    if (!data) return;
                    renderStatus(data);
                })
                .catch(() => {
                    const bar = document.getElementById('status-bar');
                    bar.textContent = '连接断开，正在尝试重连...';
                    bar.style.color = '#EF5350';
                });
        }
        
        function toggleEngine() {
            const btn = document.getElementById('toggle-btn');
            btn.disabled = true;
            fetchWithTimeout('/toggle', { method: 'POST', headers: authHeaders() }, 3000)
                .then(r => {
                    if (r.status === 401) { enterTokenScreen('令牌无效或已过期', true); return; }
                    if (!r.ok) throw new Error('http ' + r.status);
                    setTimeout(updateStatus, 500);
                })
                .catch(() => { if (authState === 'valid') updateStatus(); })
                .finally(() => { setTimeout(() => { btn.disabled = false; }, 1500); });
        }
        
        // 截图: fetch+blob（img 无法携带 header; blob URL 天然绕过 HTTP 缓存, 无需 ?t= 参数）
        let screenshotUrl = null;
        function loadScreenshot() {
            const btn = document.getElementById('screenshot-btn');
            const img = document.getElementById('screenshot');
            btn.innerHTML = icon('hourglass', 16) + ' 加载中...';
            btn.disabled = true;

            fetch('/screenshot', { headers: authHeaders() })
                .then(r => {
                    if (r.status === 401) { enterTokenScreen('令牌无效或已过期', true); throw new Error('unauthorized'); }
                    if (!r.ok) throw new Error('http ' + r.status);
                    return r.blob();
                })
                .then(blob => {
                    if (screenshotUrl) URL.revokeObjectURL(screenshotUrl);  // 释放上一张
                    screenshotUrl = URL.createObjectURL(blob);
                    img.onerror = () => { img.alt = '截图失败，请重试'; };
                    img.src = screenshotUrl;
                    img.style.display = 'block';
                })
                .catch(() => { img.alt = '截图失败，请重试'; img.style.display = 'block'; })
                .finally(() => {
                    btn.innerHTML = icon('camera', 16) + ' 查看屏幕';
                    btn.disabled = false;
                });
        }

        function setFrequency(ms, btn) {
            refreshInterval = ms;
            document.querySelectorAll('.freq-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            stopPolling();
            if (authState === 'valid') startPolling();  // idle/checking 状态下不点活轮询
        }

        // 初始化: 启停按钮初始图标 + 鉴权入口
        document.getElementById('toggle-btn').innerHTML = icon('play', 16) + ' 开始';

        if (token) {
            validateAndStart();
        } else {
            enterTokenScreen();
        }
    </script>
</body>
</html>"""

# 从 styles/icons.py 单一数据源注入完整 JS 图标 body（BUG-11：全量注入，杜绝漏项）
MOBILE_HTML_TEMPLATE = MOBILE_HTML_TEMPLATE.replace(
    "__ICON_BODY__",
    ",\n        ".join('"%s": %s' % (k, json.dumps(v)) for k, v in _BODY.items()),
)


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
