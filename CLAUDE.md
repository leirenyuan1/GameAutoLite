# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

GameAutoLite 是 Windows 游戏自动化工具（PyQt6 桌面应用）：循环“截全屏 → OpenCV 模板匹配 → 人性化鼠标移动 → 真实按压点击”，支持停止条件、全局热键、悬浮窗、手机端远程监控（局域网 HTTP + 二维码）和 v4.0 数据看板。全仓库注释、docstring、UI 文案使用中文；界面图标只来自 `styles/icons.py` 的 SVG，禁止 emoji。

## 常用命令

```bash
pip install -r requirements.txt
python main.py                 # 首次启动会请求 UAC 提权（keyboard 全局热键需要）
python main.py --admin         # 已提权/跳过自动提权
```

打包（README 中的手动命令，仓库没有打包脚本）：

```bash
python -m PyInstaller --noconfirm --windowed --icon=icon.ico --name=GameAutoLite --add-data "icon.ico;." main.py
```

- 仓库没有测试套件、lint 或格式化配置，也没有单测命令；改动后至少用 `python -m py_compile <file>` 检查语法。
- 运行时文件：程序目录下 `config.json` 与 `screenshots/`（均被 .gitignore 忽略）。
- 单实例：`main.py` 用命名互斥体 `Local\GameAutoLite_SingleInstance` 拒绝重复启动；互斥体必须在 UAC 提权之后创建，防止提权重启自撞锁。

## 架构分层

### 入口与主窗口

- `main.py`：日志 → UAC 提权 → 单实例锁 → 强制 `QT_SCALE_FACTOR=1` → QApplication + `CheckboxStyle` → `MainWindow`。
- `main_window.py`：`SideBar + QStackedWidget` 五页结构（任务列表 / 停止条件 / 全局设置 / 远程监控 / 数据看板，索引 0~4）。持有任务卡片、`EngineThread`、`HotkeyManager`、远程 HTTP 服务、悬浮窗，并负责配置保存/加载、停止条件校验、看板遥测接线。页面控件通过 `self.chk_* = self._xxx_page.chk_*` 的快捷引用访问。

### 核心层（不依赖 Qt Widgets）

- `engine.py`：`EngineThread(QThread)`，循环“截图 → 按任务顺序匹配 → 随机延迟 → 点击 → 冷却”。四个停止条件由 `sc_enabled` 总开关控制；`_sleep_interruptible` 用 `Event.wait` 保证停止即时响应。信号：`status_update`、`stop_condition_met`、`stats_updated`（500ms 节流遥测）、`task_triggered`（单次触发包）。循环退出时把未发送的遥测余量存入 `final_stats_delta`，由主线程收割；finally 中 `image_engine.close_thread_sct()`。
- `image_engine.py`：TLS 缓存当前线程的 mss 实例，`close_thread_sct()` 显式释放 GDI；截图失败会关闭句柄重建重试一次，再失败回退 pyautogui。`load_template` 用 `np.fromfile + cv2.imdecode` 支持中文路径。`find_best_match` / `find_template_with_score` 支持 `search_region`，返回值始终是换算回全屏的绝对物理坐标 `(x, y, w, h, score)`。
- `mouse_controller.py`：防检测核心。区域内均匀随机取点、四阶贝塞尔曲线、控制点随机偏移、路径抖动、惯性速度曲线、真实按下/停留/松开。严禁替换为封装 click 或取区域中心点，不要简化随机性。
- `overlay_selector.py`：全屏框选器，冻结底图、选区镂空原色、4 倍准星放大镜；`get_region`（单选）、`get_regions`（多选 Enter/Backspace）、`get_region_with_image`（框选同时从冻结帧内存切片）。用独立 QEventLoop 阻塞等待。
- `config_manager.py`：`config.json` 原子写入（tmp + `os.replace`）；`.galt` 方案文件是 JSON，图片 base64 内嵌，导入以 `stem_hash8.ext` 还原到 `screenshots/`。配置结构为 `{"settings": {...}, "tasks": [...]}`，看板历史在 `settings.stats_history`。
- `remote_server.py`：多线程 HTTP 服务，从 8080 起尝试端口；手机端 HTML 模板是普通字符串（含 `{}`，不要改成 f-string）。`/toggle` 经 `QMetaObject.invokeMethod` 转发主线程。
- `hotkey_manager.py`：`keyboard` 全局热键，回调在钩子线程，必须用 `invokeMethod(QueuedConnection)` 转发主线程。

### UI 层

- `pages/`：任务列表、停止条件、全局设置、远程监控、数据看板。`DashboardPage` 是 `QScrollArea`，维护“本次运行 session”和“历史累计 history”两套模型；KPI、排行榜、趋势图、物理像素散点、最近 50 条流水。
- `widgets/`：`CollapsibleTaskCard`（折叠任务卡片）、`SideBar`、`FloatingWidget`、`HotkeyCaptureDialog`、`NavItem`。
- `styles/`：`colors.py`、`qss.py`、SVG 图标库 `icons.py`、`checkbox_style.py`（必须在 QApplication 创建后设置）。

## 关键设计约定

- **坐标/DPI**：`main.py` 强制 `QT_SCALE_FACTOR=1`，overlay / mss / win32api 共用物理像素坐标系。overlay 拖拽用逻辑坐标，`_finalize()` 乘 `devicePixelRatioF()` 转物理像素。看板散点用 `QApplication.primaryScreen().geometry() * devicePixelRatio` 得到物理尺寸，按 Letterbox 等比映射。新增截图/鼠标/看板坐标功能必须沿用此约定。
- **状态文本协议**：engine 发送纯中文句子（“运行中...”“匹配到「xx」, 延迟 Nms 后点击”“点击完成, 冷却 Nms”“截图失败, 1秒后重试...”“已停止”）。`main_window._on_status_update` 用关键词子串匹配（含“无可用任务”）；条件停止原因由 `_parse_stop_reason_lines` 正则结构化解析。改 engine 文案必须同步更新这两处。
- **远程状态协议**：`_remote_status_cache` 包含 `icon1/2/3`（`{"key","color"}` 对象）、`line1/2/3`、`is_running`、`stop_reason`、`run_duration`、`total_matches`。`_set_sidebar_icon` 是图标唯一写入口；桌面端与 `remote_server.py` 的 JS 渲染必须同步。
- **远程鉴权**：`start_server` 每次启动生成随机 token（`secrets.token_urlsafe(9)`，不持久化）。`/` 与 `/ping` 免鉴权，其余 `/status`、`/screenshot`、`/toggle` 必须带 `X-Auth-Token`；用 `hmac.compare_digest` 比较，空 token 无条件拒绝。手机端 token 通过 `http://ip:port/#tk=<token>` fragment 分发；401 时暂停轮询并弹令牌输入卡。鉴权 JSON、截图与页面响应统一加 `Cache-Control: no-store`。
- **线程安全**：engine、keyboard 钩子、HTTP 请求线程都不得直接操作 UI 控件；统一用 Qt 信号或 `QMetaObject.invokeMethod` 回主线程。`styles/icons.py` 的 QPixmap/QIcon 也仅允许主线程调用。
- **引擎生命周期**：`_start_engine` 先校验任务名（非空/不重复）、配置完整性（`is_configured` 要求 `enabled` + 图片 + 区域或跟随识别），再存盘并启动。`_stop_engine` 断开全部信号、`stop()`、最多等 3 秒；超时进入 `_engine_dying`，旧线程 finished 前拒绝新引擎。停止条件校验失败只警告并禁用该条件，不阻止启动。
- **遥测/看板单一信源**：`stats_updated` 每 500ms 最多一包，`task_triggered` 只在点击实际完成后发送。停机时主线程先断开信号，再读取 `final_stats_delta` 补账；不要在 worker 退出时再 emit 最后一包，否则会双倍累加。`on_engine_stopped` 将 session 合并进 history；`export_stats_history` 在加载损坏时返回 `{}` 保护原数据；改名通过 `on_task_renamed` 合并 session/history 统计。
- **任务字段/ROI**：`to_dict()` 字段为 `name, enabled, image_path, threshold, search_region, region, click_on_match, multi_region, regions, click_count, delay_min/max, cooldown_min/max`。`search_region` 是模板匹配的搜索 ROI；`region`/`regions` 是点击区域；`click_on_match` 表示点击匹配框。三者不要混淆。
- **配置与关闭清理**：配置原子写入；`_save_config` 会先同步设置并导出 `stats_history`。`closeEvent` 依次停止引擎、收割遥测、停止远程服务、关闭悬浮窗与高亮浮窗、注销热键、保存配置、`image_engine.close_thread_sct()`。
- **配置容错**：`_load_config` 不能假设 `settings`、`stop_conditions` 及其子字典一定是 dict；布尔、数值、任务名、图片路径必须做类型校验与默认回退。`config.json` 解析失败时先备份原文件并提示，不要静默覆盖。`CollapsibleTaskCard.from_dict` 的 `image_path` 必须先确认是 `str` 再交给 `QPixmap`。
- **窄窗口布局**：主窗口最小 550×500。数据看板 KPI 为 2×2，`_DashboardCard.minimumSizeHint()` 宽度置 0，历史卡片等宽 1:1；不要在窄视口引入固定最小宽度或横向滚动条。动态文本（如排行第三列）用 `QFontMetrics` 量宽或 `setMinimumWidth`，不要用 `setFixedWidth` 静默裁切。
- **防检测随机性**：engine 随机延迟、mouse_controller 随机取点/控制点偏移/路径抖动是产品核心，不要简化或改成确定性算法。
- **图标规范**：所有界面图标来自 `styles/icons.py` 的 `_BODY`，新增图标只扩展该字典；禁止 emoji 字符。桌面端用 `set_label_icon` / `button_icon` / `IconButton`，手机端用 `svg_element` + `currentColor`。

## 验收与回归检查

- 仓库没有测试套件或 lint；改动后至少对涉及文件执行 `python -m py_compile <file>`，并优先用 `QT_QPA_PLATFORM=offscreen` 做 UI 构造与布局冒烟。
- 离屏构造 `MainWindow` 时必须使用临时 config 路径并禁用真实热键注册，不能写入用户 `config.json`。
- 最低回归清单：
  1. 新建卡片、`to_dict` / `from_dict`、`enabled` / `search_region` 往返；
  2. `MainWindow` 五页构造、无启用任务分支、启动/停止控件锁定；
  3. 引擎多任务匹配与无匹配循环（用假截图/假点击，不触发真实鼠标）；
  4. 看板 420px 历史模式 4/6 位数行宽；
  5. overlay DPR 与 `get_region_with_image` 切片；
  6. 远程 token 校验（正确/错误/空 token）。
- 真机验收另行覆盖：UAC 提权、单实例、真实截图/鼠标、mss 失败回退、高 DPI overlay、局域网手机端 401 与网络恢复。
