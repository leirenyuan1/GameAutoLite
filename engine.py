"""
引擎调度线程 (engine.py)
"""

import logging
import random
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

import image_engine
import mouse_controller

logger = logging.getLogger(__name__)


class EngineThread(QThread):
    """引擎调度线程：循环截图 → 匹配 → 点击。"""

    status_update = pyqtSignal(str)
    stop_condition_met = pyqtSignal(str)
    # ↑ 停止条件触发，参数为原因描述（空字符串表示正常停止）

    def __init__(self, task_configs: list[dict], scan_interval: int = 200,
                 move_speed: float = 1.0, click_speed: float = 1.0,
                 stop_conditions: dict | None = None, parent=None):
        super().__init__(parent)
        self._task_configs = task_configs
        self._scan_interval = scan_interval
        self._move_speed = move_speed
        self._click_speed = click_speed
        self._stop_conditions = stop_conditions or {}
        self._stop_event = threading.Event()
        self._template_cache: dict[str, object] = {}

    def run(self) -> None:
        self.status_update.emit("● 运行中...")
        start_time = time.time()
        task_match_counts: dict[str, int] = {}
        last_match_time = time.time()
        stop_image_template = None

        sc = self._stop_conditions
        sc_enabled = sc.get("enabled", False)
        cond1 = sc.get("task_exec_count", {})
        cond2 = sc.get("run_time_limit", {})
        cond3 = sc.get("image_match_stop", {})
        cond4 = sc.get("no_match_timeout", {})

        # 预加载条件三的模板
        if cond3.get("enabled"):
            img_path = cond3.get("image_path", "")
            if img_path:
                stop_image_template = image_engine.load_template(img_path)

        while not self._stop_event.is_set():
            # ===== 停止条件检查（总开关开启时才检查）=====
            if sc_enabled:
                # 条件二：运行时间
                if cond2.get("enabled"):
                    elapsed_min = (time.time() - start_time) / 60.0
                    if elapsed_min >= cond2["minutes"]:
                        self.stop_condition_met.emit(
                            f"已运行 {cond2['minutes']} 分钟，自动停止"
                        )
                        break

                # 条件四：无匹配超时
                if cond4.get("enabled"):
                    idle_min = (time.time() - last_match_time) / 60.0
                    if idle_min >= cond4["minutes"]:
                        self.stop_condition_met.emit(
                            f"{cond4['minutes']} 分钟无匹配，自动停止"
                        )
                        break
            # 1. 截全屏
            try:
                screenshot = image_engine.take_screenshot()
            except Exception as e:
                logger.error(f"截图失败: {e}")
                self.status_update.emit("● 截图失败, 1秒后重试...")
                time.sleep(1)
                continue

            # 条件三：识别到指定图片（截图成功后、遍历任务前）
            if sc_enabled and cond3.get("enabled") and stop_image_template is not None:
                threshold = cond3.get("threshold", 90) / 100.0
                if image_engine.find_template(screenshot, stop_image_template, threshold):
                    self.stop_condition_met.emit("识别到指定停止图片，自动停止")
                    break

            # 2. 按列表从上到下顺序扫描
            matched = False
            for cfg in self._task_configs:
                if self._stop_event.is_set():
                    break

                img_path = cfg["image_path"]
                if img_path in self._template_cache:
                    template = self._template_cache[img_path]
                else:
                    template = image_engine.load_template(img_path)
                    if template is not None:
                        self._template_cache[img_path] = template
                    else:
                        template = None
                if template is None:
                    continue

                result = image_engine.find_template(
                    screenshot, template, cfg["threshold"] / 100.0
                )
                if result is not None:
                    # 3. 匹配成功 → 随机延迟
                    _dmin, _dmax = cfg["delay_min"], cfg["delay_max"]
                    delay_ms = random.randint(_dmin, max(_dmin, _dmax))
                    self.status_update.emit(
                        f"● 匹配到「{cfg['name']}」, 延迟 {delay_ms}ms 后点击"
                    )
                    self._sleep_interruptible(delay_ms / 1000.0)
                    if self._stop_event.is_set():
                        break

                    # 4. 执行点击
                    try:
                        click_count = cfg.get("click_count", 1)
                        if cfg.get("multi_region", False):
                            regions = cfg["regions"]
                            for ci in range(click_count):
                                if self._stop_event.is_set():
                                    break
                                if ci > 0:
                                    _interval = random.uniform(0.15, 0.25) / self._click_speed
                                    self._sleep_interruptible(_interval)
                                mouse_controller.click_in_regions(
                                    regions,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                )
                        elif cfg.get("click_on_match", False):
                            rx, ry, rw, rh = result
                            if click_count <= 1:
                                mouse_controller.click_in_region(
                                    rx, ry, rw, rh,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                )
                            else:
                                mouse_controller.click_in_region_multi(
                                    rx, ry, rw, rh, count=click_count,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                    stop_event=self._stop_event,
                                )
                        else:
                            rx, ry, rw, rh = cfg["region"]
                            if click_count <= 1:
                                mouse_controller.click_in_region(
                                    rx, ry, rw, rh,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                )
                            else:
                                mouse_controller.click_in_region_multi(
                                    rx, ry, rw, rh, count=click_count,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                    stop_event=self._stop_event,
                                )
                    except Exception as e:
                        logger.error(f"点击失败: {e}")

                    # 5. 点击后冷却
                    _cmin = cfg.get("cooldown_min", 0)
                    _cmax = cfg.get("cooldown_max", 0)
                    cooldown_ms = random.randint(_cmin, max(_cmin, _cmax))
                    if not self._stop_event.is_set():
                        self.status_update.emit(
                            f"● 点击完成, 冷却 {cooldown_ms}ms"
                        )
                        if cooldown_ms > 0:
                            self._sleep_interruptible(cooldown_ms / 1000.0)

                    matched = True

                    # 匹配成功后重置无匹配计时器
                    last_match_time = time.time()

                    # 条件一：任务执行次数
                    if sc_enabled and cond1.get("enabled"):
                        task_name = cfg["name"]
                        target_name = cond1.get("task_name", "")
                        if task_name == target_name:
                            task_match_counts[task_name] = task_match_counts.get(task_name, 0) + 1
                            if task_match_counts[task_name] >= cond1["count"]:
                                self.stop_condition_met.emit(
                                    f"「{task_name}」已执行 {cond1['count']} 次，自动停止"
                                )
                                self._stop_event.set()
                                break

                    # 6. 本轮结束, 回到步骤1
                    break

            if not matched and not self._stop_event.is_set():
                self.status_update.emit("● 运行中...")
                if self._scan_interval > 0:
                    self._sleep_interruptible(self._scan_interval / 1000.0)

        self.status_update.emit("● 已停止")

    def _sleep_interruptible(self, seconds: float) -> None:
        """可被打断的 sleep, 每 50ms 检查一次停止标志."""
        end = time.time() + seconds
        while time.time() < end and not self._stop_event.is_set():
            time.sleep(0.05)

    def stop(self) -> None:
        self._stop_event.set()
