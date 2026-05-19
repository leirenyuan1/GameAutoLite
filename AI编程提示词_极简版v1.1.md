# AI 编程提示词 — 极简游戏自动化助手 (基础核心版 v1.1)

---

## 【总纲】项目初始化

```
你是一位资深的 Python 桌面应用开发专家。
请帮我用 Python 搭建一个 Windows PC 桌面应用，项目名为 GameAutoLite。

【技术栈】
- GUI 框架：PyQt6
- 图像识别：opencv-python (cv2) + mss（屏幕截图，比 pyautogui 更快）
- 鼠标控制：pywin32（win32api，DirectInput 级别）
- 全局热键：keyboard 库

【项目文件结构（共 4 个核心文件，不得增加）】

GameAutoLite/
├── main_ui.py           # 主界面 UI + F8 热键逻辑
├── overlay_selector.py  # 全屏遮罩拖拽选区工具
├── image_engine.py      # 截图 + OpenCV 模板匹配
└── mouse_controller.py  # 贝塞尔曲线移动 + 真实按压点击

【依赖清单 requirements.txt】
PyQt6
opencv-python
mss
pywin32
keyboard
numpy

请先输出完整的目录结构说明和 requirements.txt，
再在每个 .py 文件中写好模块顶部的功能注释和 import 占位，不写具体实现。
```

---

## 【模块一】鼠标控制 — mouse_controller.py

```
请实现 GameAutoLite 项目的 mouse_controller.py 文件。

【功能描述】
专门负责所有鼠标操作，是软件防检测的核心。对外只暴露一个主函数：
click_in_region(x, y, w, h)

【内部实现要求，缺一不可】

─── 第一步：在区域内随机取点 ───
在传入的矩形 (x, y, w, h) 内随机生成一个目标像素点 (tx, ty)。
禁止取中心点，必须在整个矩形范围内均匀随机取点。

─── 第二步：贝塞尔曲线移动到目标点 ───
函数签名：_bezier_move(tx, ty)

1. 获取当前鼠标位置作为起点 (sx, sy)。
2. 生成一条四阶贝塞尔曲线路径：
   - 在起点和终点之间随机生成 3 个控制点，每个控制点在连线附近
     随机偏移（x、y 各自偏移 -120px ~ +120px），产生自然弧度。
3. 将曲线等分为 60~80 个采样点（随机），逐点移动鼠标。
4. 速度曲线符合物理惯性：
   - 前 20% 采样点：间隔较长（起步慢）
   - 中间 60% 采样点：间隔较短（匀速快）
   - 后 20% 采样点：间隔逐渐变长（临近减速）
5. 路径抖动：每个中间采样点（首尾除外）叠加 ±1~2px 随机偏移，
   x 和 y 方向各自独立随机，模拟人手自然微抖。
6. 移动总耗时根据距离动态控制：
   - 起点到终点像素距离 < 200px：总耗时随机 150~300ms
   - 距离 >= 200px：总耗时随机 400~650ms
   将总耗时均分到每个采样点间隔，配合速度曲线系数动态调整每步 sleep 时长。
7. 使用 win32api.SetCursorPos() 逐点移动光标。

─── 第三步：真实按压点击 ───
函数签名：_real_click()

严禁使用任何封装好的 click() 函数。必须拆分为：
1. win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)  # 按下
2. time.sleep(random.uniform(0.05, 0.15))                      # 随机停留 50~150ms
3. win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)    # 松开

【对外接口（唯一出口）】
def click_in_region(x: int, y: int, w: int, h: int) -> None:
    """
    在矩形区域内随机取点，贝塞尔曲线移动过去，执行真实按压点击。
    调用方只需传入区域坐标，内部自动完成全部步骤。
    """

请实现完整的 mouse_controller.py，含详细中文注释。
```

---

## 【模块二】图像引擎 — image_engine.py

```
请实现 GameAutoLite 项目的 image_engine.py 文件。

【功能描述】
封装屏幕截图与 OpenCV 模板匹配，供主引擎循环调用。

【具体实现要求】

1. 截图函数：
   def take_screenshot() -> numpy.ndarray
   - 使用 mss 库截取全屏（速度优先）
   - 返回 BGR 格式的 numpy 数组（OpenCV 标准格式）
   - 若 mss 初始化失败，fallback 到 pyautogui.screenshot()

2. 模板加载函数：
   def load_template(image_path: str) -> numpy.ndarray | None
   - 从路径加载模板图，转为 BGR 格式
   - 加载失败时返回 None，并打印错误信息，不抛出异常

3. 核心匹配函数：
   def find_template(screenshot: numpy.ndarray,
                     template: numpy.ndarray,
                     threshold: float = 0.8) -> tuple[int, int, int, int] | None
   - 使用 cv2.matchTemplate + cv2.TM_CCOEFF_NORMED 方法
   - 若最高匹配分数 >= threshold，返回匹配区域 (x, y, w, h)
   - 否则返回 None
   - 整个函数用 try/except 包裹，匹配过程出错时返回 None 并记录日志，不崩溃

【注意】
- 所有函数保持无状态（stateless），不在模块内存储全局变量
- mss 对象在 take_screenshot 内部创建和销毁（with mss.mss() as sct:），
  避免长时间占用资源

请实现完整的 image_engine.py，含详细中文注释。
```

---

## 【模块三】区域选择器 — overlay_selector.py

```
请实现 GameAutoLite 项目的 overlay_selector.py 文件。

【功能描述】
用户点击"设定点击区域"后，全屏弹出半透明遮罩，供用户用鼠标拖拽
划定一个红色矩形，系统记录该矩形的绝对坐标并返回。

【具体实现要求】

1. 弹出全屏无边框 PyQt6 窗口：
   - 背景：半透明黑色蒙版，透明度约 40%（rgba 0,0,0,100）
   - 始终置顶（Qt.WindowType.WindowStaysOnTopHint）
   - 顶部居中显示提示文字：「拖拽鼠标划定点击区域，按 Esc 取消」
     文字白色，带黑色描边，字号 16px

2. 鼠标交互：
   - mousePressEvent：记录起始坐标
   - mouseMoveEvent：实时更新红色矩形，触发 repaint()
   - mouseReleaseEvent：记录终止坐标，计算最终矩形，关闭窗口
   - keyPressEvent：按 Esc 时设置 result = None，关闭窗口

3. paintEvent 绘制红框：
   - 描边颜色：纯红色 (#FF0000)，线宽 2px
   - 内部填充：半透明红色（rgba 255,0,0,30）
   - 仅在用户开始拖拽后才绘制（按下前不显示任何矩形）

4. 坐标归一化：
   支持从右向左、从下向上拖拽，松开后自动转换为标准形式：
   x = min(start_x, end_x)
   y = min(start_y, end_y)
   w = abs(end_x - start_x)
   h = abs(end_y - start_y)
   若 w 或 h < 10，视为误操作，返回 None。

5. 对外接口（阻塞式调用）：
   def get_region() -> tuple[int, int, int, int] | None:
       """
       阻塞调用，弹出选择窗口，等待用户操作完成后返回结果。
       返回 (x, y, w, h) 或 None（用户取消时）。
       """
   内部使用独立 QEventLoop 实现阻塞等待，窗口关闭时退出 loop 并返回结果。

请实现完整的 overlay_selector.py，含详细中文注释。
```

---

## 【模块四】主界面 — main_ui.py

```
请实现 GameAutoLite 项目的 main_ui.py 文件，这也是程序唯一入口。

【整体界面布局】

窗口标题：GameAutoLite | 固定宽度 480px | 高度自适应
背景浅灰，整体风格简洁现代。

─── 顶部标题区 ───
大号标题文字「🎮 GameAutoLite」，副标题「极简游戏自动化助手」，居中显示。

─── 任务列表区（可滚动）───
每个任务以圆角卡片形式展示，卡片内布局如下：

  行1：[任务名称输入框（可编辑）]  [↑] [↓] [🗑删除] 按钮
  行2：[🖼 上传识别图] 按钮  →  图片缩略图预览（60×60px，无图时显示占位虚线框）
  行3：匹配精确度：[滑块 50%~99%] 当前值：XX%
  行4：[⊕ 设定点击区域] 按钮  →  坐标显示标签（未设定显示"未设定"，设定后显示"X,Y W×H"）
  行5：识别后随机延迟：最小[___]ms ~ 最大[___]ms（默认 200 ~ 500）

列表底部：[＋ 添加任务] 按钮，居中，点击后在列表末尾新增一张空白任务卡片。

─── 启停控制区 ───
[ √ ] 启用 F8 快捷键启停（勾选框，默认勾选）

[     ▶  开 始     ]   ←  绿色大按钮，宽度占满
启动后切换为：
[     ⏹  停 止     ]   ←  红色大按钮，宽度占满

状态标签（按钮下方）：
  就绪状态 → 灰色文字「● 就绪」
  运行状态 → 绿色文字「● 运行中...」
  停止状态 → 红色文字「● 已停止」

─── 底部提示栏（固定，不随滚动消失）───
💡 提示：如点击无效，请右键本软件选择"以管理员身份运行"

【引擎调度逻辑（在本文件内实现，用 QThread）】

引擎线程 EngineThread(QThread)：
  - 收集所有已启用且配置完整（有图片、有区域）的任务
  - 按列表从上到下顺序循环扫描：
    1. 调用 image_engine.take_screenshot() 截全屏
    2. 对每个任务调用 image_engine.find_template()
    3. 匹配成功 → 等待该任务配置的随机延迟（在 min~max 区间内随机取值）
    4. 延迟结束 → 调用 mouse_controller.click_in_region() 执行点击
    5. 本轮结束，回到步骤1，继续下一轮循环
  - 通过 pyqtSignal 向主界面推送状态文字（用于更新状态标签）
  - 线程外调用 stop() 方法可安全退出循环（使用 threading.Event 实现）

【F8 热键逻辑】
- 使用 keyboard 库注册全局热键（在主界面初始化时注册）
- F8 按下 → 若引擎未运行则调用开始逻辑，若正在运行则调用停止逻辑（双向切换）
- 勾选框取消勾选时，立即调用 keyboard.remove_hotkey('f8') 注销热键
- 勾选框重新勾选时，重新注册 F8 热键
- 热键回调必须通过 QMetaObject.invokeMethod 转发到主线程，不直接操作 UI

【输入验证】
- 延迟 min/max 输入框：使用 QIntValidator(0, 9999) 限制，
  editingFinished 时验证 min <= max，若 min > max 则自动将 max 修正为 min + 100
- 任务卡片的上移/下移按钮：边界处（第一个不能再上移，最后一个不能再下移）自动禁用

【配置持久化】
- 所有任务配置在程序退出时（closeEvent）保存到 config.json
- 启动时若存在 config.json 则自动读取并恢复任务列表
- 图片以绝对路径存储，若路径失效则在卡片上显示红色警告「⚠ 图片文件已丢失」

【程序入口】
if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

请实现完整的 main_ui.py，含详细中文注释。
```

---

## 【最终验证清单】

```
GameAutoLite 全部 4 个模块开发完毕后，请逐一核查以下清单，
对每一条给出"✅ 已实现"或"❌ 缺失，在 XXX 文件第 XX 行补充"：

鼠标防检测（mouse_controller.py）：
[ ] 点击落点在红框内随机取点，禁止取中心
[ ] 鼠标路径为贝塞尔曲线，禁止直线瞬移
[ ] 曲线控制点有随机偏移，产生自然弧度
[ ] 中间采样点叠加 ±1~2px 抖动，首尾端点不抖
[ ] 移动耗时按距离动态分配（短距 150~300ms，长距 400~650ms）
[ ] 点击拆分为 mouseDown + sleep(50~150ms) + mouseUp，禁止瞬间点击

图像引擎（image_engine.py）：
[ ] 截图使用 mss，fallback 到 pyautogui
[ ] 匹配使用 TM_CCOEFF_NORMED 方法
[ ] 匹配失败返回 None，不抛出异常，不崩溃

区域选择器（overlay_selector.py）：
[ ] 全屏半透明遮罩，始终置顶
[ ] 支持任意方向拖拽，自动归一化坐标
[ ] 拖拽范围 < 10px 视为误操作返回 None
[ ] get_region() 为阻塞式调用，窗口关闭后才返回结果
[ ] Esc 键取消返回 None

主界面与调度（main_ui.py）：
[ ] 引擎运行在 QThread，不阻塞 UI
[ ] 停止机制使用 threading.Event，可安全退出循环
[ ] F8 热键双向切换启停
[ ] 取消勾选 F8 时立即注销热键，重新勾选时重新注册
[ ] 热键回调通过 invokeMethod 转发主线程，不直接操作 UI
[ ] 延迟 min > max 时自动修正
[ ] 任务上移/下移边界时对应按钮禁用
[ ] 退出时保存 config.json，启动时自动恢复
[ ] 图片路径丢失时显示红色警告
```
