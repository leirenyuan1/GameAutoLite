"""手机端远程监控页面模板，保留为普通字符串以兼容打包。"""

import json
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
