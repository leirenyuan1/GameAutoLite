# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

GameAutoLite 是一个 Windows 游戏自动化工具（PyQt6 桌面应用）：循环 "截全屏 → OpenCV 模板匹配 → 人性化鼠标移动 → 真实按压点击"，并支持停止条件、全局热键、手机端远程监控（局域网 HTTP + 二维码）。全仓库注释、docstring、UI 文案均为中文。

## 常用命令

```bash
pip install -r requirements.txt   # 安装依赖
python main.py                    # 运行（首次会自动弹 UAC 提权，因为 keyboard 全局热键需要管理员）
python main.py --admin            # 跳过自动提权直接启动（已提权后使用）
```

- 无测试套件、无 lint/格式化配置、无打包脚本（`main.py` 中已处理 PyInstaller frozen 模式的图标路径分支）。
- 运行配置保存在程序目录旁的 `config.json`；用户框选/导入的图片存放在 `screenshots/` 目录。
- 所有 UI 文案必须保持中文，`_on_status_update` 等逻辑依赖中文关键词匹配（见下文"状态文本协议"）。

## 架构分层

### 核心引擎层（不依赖 Qt Widgets）

- **[engine.py](engine.py)** — `EngineThread(QThread)`：核心循环 `截图 → 从列表顺序匹配 → 随机延迟 → 点击 → 冷却`。支持 4 种停止条件（任务执行次数、运行时长、识别到指定图、无匹配超时），统一由 `sc_enabled` 总开关控制。通过 `status_update` / `stop_condition_met` 信号与 UI 通信，`_sleep_interruptible` 保证停止事件中断。
- **[image_engine.py](image_engine.py)** — 无状态纯函数：`take_screenshot()`（mss 截主显示器，失败 fallback pyautogui）、`load_template()`、`find_template()`（`TM_CCOEFF_NORMED`，高于阈值返回 `(x,y,w,h)`）。
- **[mouse_controller.py](mouse_controller.py)** — 防检测核心，全部底层坐标操作（区域内随机取点、四阶贝塞尔曲线移动、真实按压点击）。**严禁**使用封装 click 函数、**严禁**取区域中心点；随机延迟、控制点偏移、路径抖动、惯性速度曲线是刻意设计，不要简化。
- **[overlay_selector.py](overlay_selector.py)** — 全屏半透明拖拽框选器，`get_region()`（单选）和 `get_regions()`（多选：Enter 确认/Backspace 回撤）。用独立 `QEventLoop` 阻塞等待结果。
- **[config_manager.py](config_manager.py)** — `config.json` 原子写入（tmp + `os.replace`）；`.galt` 方案文件实为 JSON，图片以 base64 内嵌，导入时优先还原到 `screenshots/`。
- **[remote_server.py](remote_server.py)** — 局域网 HTTP 服务（8080 起循环尝试端口），内置手机端 HTML 模板（纯字符串，勿改成 f-string，HTML 里有 `{}`）。`/toggle` 等 POST 必须经 `QMetaObject.invokeMethod` 转发主线程。
- **[hotkey_manager.py](hotkey_manager.py)** — `keyboard` 库全局热键，回调运行在钩子线程，用 `invokeMethod(QueuedConnection)` 转发主线程。

### UI 层（PyQt6）

- **[main_window.py](main_window.py)** — 1482 行中心枢纽。`SideBar + QStackedWidget` 四页结构（任务列表 / 停止条件 / 全局设置 / 远程监控）。持有每个页面控件的"快捷引用"（如 `self.chk_stop_enabled = self._stop_conditions_page.chk_stop_enabled`），新代码可继续沿用此模式。
- **pages/** — 每个页面以 `QWidget` 持有全部控件；停止条件页与设置页共用 [pages/utils.py](pages/utils.py) 的 `make_settings_card()`。
- **widgets/[task_card.py](widgets/task_card.py)** — `CollapsibleTaskCard`（可折叠任务卡片，879 行），任务配置由 `to_dict()` / `from_dict()` 序列化，字段：`name, image_path, threshold, region, click_on_match, multi_region, regions, click_count, delay_min/max, cooldown_min/max`。
- **styles/** — 集中式配色（colors.py）、全局 QSS（qss.py）、复选框样式（CheckboxStyle，必须由 `main.py` 在 QApplication 创建后设置）。

## 关键设计约定

- **坐标/缩放体系**：`main.py` 强制 `QT_SCALE_FACTOR=1` 保证 overlay / mss / win32api 三方都是同一物理像素坐标系；overlay 框选开始时是逻辑坐标，`_finalize()` 时乘 `devicePixelRatioF()` 换算回物理像素。任何新增截图/鼠标功能必须遵循这一约定，否则 125%/150% 缩放下坐标会漂移。
- **中文路径**：cv2 家族禁止直接 `imread`，统一用 `np.fromfile + cv2.imdecode`（中文路径支持），现有 `image_engine.load_template` 已是这种写法。
- **状态文本协议**：engine 通过 `status_update` 信号发送纯中文句子（"运行中..."、"匹配到「xx」, 延迟 Nms 后点击"...），[main_window.py 的 `_on_status_update`](main_window.py#L742-L809) 用**关键词子串匹配**解析（"运行中"/"匹配到"/"点击完成"/"截图失败"/"已停止"）更新侧边栏、悬浮窗和远程监控缓存（`_remote_status_cache`）。改动 engine 的输出文案时必须同步改解析。
- **界面图标一律用 SVG（禁止写 emoji 字符）**：统一来自 [styles/icons.py](styles/icons.py)（lucide 风格线性描边，24×24，颜色运行时注入），通过 `set_label_icon`（QLabel 位图）/ `button_icon`（QIcon）/ `IconButton`（hover 代码切图）使用；手机端 HTML 的 `ICON_BODY` 由 remote_server.py 从 icons.py 单一数据源注入。新增图标只需扩展 `_BODY` 字典。
- **引擎运行状态唯一权威**：`sidebar.is_running()`（由 `set_engine_running` 维护），禁止从按钮文本推断（旧代码 `startswith("⏹")`、`"停止" in text` 已铲除）。
- **远程监控状态协议**：`_remote_status_cache` 的 `icon1/2/3` 是 `{"key": "zap", "color": "#..."}` 对象，由 `MainWindow._status_icons` 维护（唯一写入口 `_set_sidebar_icon`）。改动该协议时，桌面端与 remote_server.py 的 JS 渲染必须同步落地。
- **远程监控鉴权**：局域网 HTTP 服务带 token 鉴权——`server.token` 由 `start_server` 每次启动随机生成（`secrets.token_urlsafe(9)`，不持久化）；除 `/` 与 `/ping` 外所有请求必须携带 `X-Auth-Token` header（`hmac.compare_digest` bytes 比较，空 token 必须拒绝）；手机端经 `http://ip:port/#tk=<token>` 分发 token（fragment 不进 query/日志），轮询/截图/启停全部带 header，401 时暂停轮询弹令牌输入卡，校验通过才写入 localStorage；改动鉴权时注意响应统一 `Cache-Control: no-store`（防旧页面缓存）。
- **线程安全**：所有底层库回调（engine 线程、keyboard 钩子线程、HTTP server 请求线程）都不得直接操作 UI，必须经 Qt 信号或 `QMetaObject.invokeMethod` 转发到主线程。
- **引擎生命周期**：`_start_engine()` 启动前校验任务名（不得空/重复）和任务配置完整性；`_stop_engine()` 等待线程退出（3 秒 timeout），超时进入 `_engine_dying` 状态——此时拒绝启动新引擎，等旧线程真正 finished 后才清理（`_on_dying_engine_finished`）。停止条件校验失败时只弹提示警告并将该条件禁用，不阻止启动。
- **防检测随机性**：engine 里的随机延迟、mouse_controller 里的随机取点/控制点偏移/路径抖动都是产品核心卖点，修改时保持随机分布特征。
