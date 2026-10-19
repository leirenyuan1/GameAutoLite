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
    stats_updated = pyqtSignal(dict)    # 增量遥测包
    task_triggered = pyqtSignal(dict)   # 单次任务触发包

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
        self._last_status_text: str = ""
        self.final_stats_delta: dict = {}

    def _emit_status(self, text: str) -> None:
        """相同状态文本不重复 emit 信号，防止高频重绘 (BUG-10)."""
        if text != self._last_status_text:
            self._last_status_text = text
            self.status_update.emit(text)

    def run(self) -> None:
        self._emit_status("运行中...")
        start_time = time.time()
        task_match_counts: dict[str, int] = {}
        last_match_time = time.time()
        stop_image_template = None

        # 遥测增量计数器与节流时间戳
        cycle_scan_delta = 0
        cycle_scan_cost_ms = 0.0
        last_scan_cost_ms = 0.0
        last_stats_emit_time = time.time()

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

            # 1. 截全屏 (开始记录纯扫描耗时起点)
            t_scan_start = time.perf_counter()
            try:
                screenshot = image_engine.take_screenshot()
            except Exception as e:
                logger.error(f"截图失败: {e}")
                self._emit_status("截图失败, 1秒后重试...")
                self._sleep_interruptible(1.0)
                continue

            # 条件三：识别到指定图片（截图成功后、遍历任务前）
            if sc_enabled and cond3.get("enabled") and stop_image_template is not None:
                threshold = cond3.get("threshold", 90) / 100.0
                if image_engine.find_template(screenshot, stop_image_template, threshold):
                    cost_ms = (time.perf_counter() - t_scan_start) * 1000.0
                    cycle_scan_delta += 1
                    cycle_scan_cost_ms += cost_ms
                    last_scan_cost_ms = cost_ms
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

                result = image_engine.find_template_with_score(
                    screenshot, template, cfg["threshold"] / 100.0
                )
                if result is not None:
                    rx, ry, rw, rh = result[:4]
                    score = result[4]

                    # 纯扫描耗时统计终点：严格在延迟/移动/点击前采样
                    cost_ms = (time.perf_counter() - t_scan_start) * 1000.0
                    cycle_scan_delta += 1
                    cycle_scan_cost_ms += cost_ms
                    last_scan_cost_ms = cost_ms

                    if time.time() - last_stats_emit_time >= 0.5 and cycle_scan_delta > 0:
                        self.stats_updated.emit({
                            "scan_delta": cycle_scan_delta,
                            "scan_cost_delta_ms": cycle_scan_cost_ms,
                            "last_cost_ms": last_scan_cost_ms,
                            "elapsed_sec": time.time() - start_time,
                        })
                        cycle_scan_delta = 0
                        cycle_scan_cost_ms = 0.0
                        last_stats_emit_time = time.time()

                    # 3. 匹配成功 → 随机延迟
                    _dmin, _dmax = cfg["delay_min"], cfg["delay_max"]
                    delay_ms = random.randint(_dmin, max(_dmin, _dmax))
                    self._emit_status(
                        f"匹配到「{cfg['name']}」, 延迟 {delay_ms}ms 后点击"
                    )
                    self._sleep_interruptible(delay_ms / 1000.0)
                    if self._stop_event.is_set():
                        break

                    # 预先计算冷却时间
                    _cmin = cfg.get("cooldown_min", 0)
                    _cmax = cfg.get("cooldown_max", 0)
                    cooldown_ms = random.randint(_cmin, max(_cmin, _cmax))

                    # 4. 执行点击并采集物理落点列表
                    click_results: list[tuple[int, int, float, float]] = []
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
                                    if self._stop_event.is_set():
                                        break
                                c = mouse_controller.click_in_regions(
                                    regions,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                    stop_event=self._stop_event,
                                )
                                if c:
                                    click_results.extend(c)
                        elif cfg.get("click_on_match", False):
                            if click_count <= 1:
                                c = mouse_controller.click_in_region(
                                    rx, ry, rw, rh,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                    stop_event=self._stop_event,
                                )
                                if c:
                                    click_results.extend(c)
                            else:
                                c = mouse_controller.click_in_region_multi(
                                    rx, ry, rw, rh, count=click_count,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                    stop_event=self._stop_event,
                                )
                                if c:
                                    click_results.extend(c)
                        else:
                            rx_reg, ry_reg, rw_reg, rh_reg = cfg["region"]
                            if click_count <= 1:
                                c = mouse_controller.click_in_region(
                                    rx_reg, ry_reg, rw_reg, rh_reg,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                    stop_event=self._stop_event,
                                )
                                if c:
                                    click_results.extend(c)
                            else:
                                c = mouse_controller.click_in_region_multi(
                                    rx_reg, ry_reg, rw_reg, rh_reg, count=click_count,
                                    move_speed=self._move_speed,
                                    click_speed=self._click_speed,
                                    stop_event=self._stop_event,
                                )
                                if c:
                                    click_results.extend(c)
                    except Exception as e:
                        logger.error(f"点击失败: {e}")

                    # 移动或点击途中若被打断，立即跳出循环，绝不误发射触发包
                    if self._stop_event.is_set():
                        break

                    # 若未产生任何有效点击（如中途打断或底层失败），不发射触发记录
                    if not click_results:
                        continue

                    # 紧贴点击完成之后立即发射单次任务触发包
                    self.task_triggered.emit({
                        "name": cfg["name"],
                        "score": round(score * 100, 1),
                        "clicks": click_results,
                        "delay_ms": delay_ms,
                        "cooldown_ms": cooldown_ms,
                    })

                    if self._stop_event.is_set():
                        break

                    # 5. 点击后冷却
                    self._emit_status(
                        f"点击完成, 冷却 {cooldown_ms}ms"
                    )
                    if cooldown_ms > 0:
                        self._sleep_interruptible(cooldown_ms / 1000.0)
                    if self._stop_event.is_set():
                        break

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
                cost_ms = (time.perf_counter() - t_scan_start) * 1000.0
                cycle_scan_delta += 1
                cycle_scan_cost_ms += cost_ms
                last_scan_cost_ms = cost_ms

                if time.time() - last_stats_emit_time >= 0.5 and cycle_scan_delta > 0:
                    self.stats_updated.emit({
                        "scan_delta": cycle_scan_delta,
                        "scan_cost_delta_ms": cycle_scan_cost_ms,
                        "last_cost_ms": last_scan_cost_ms,
                        "elapsed_sec": time.time() - start_time,
                    })
                    cycle_scan_delta = 0
                    cycle_scan_cost_ms = 0.0
                    last_stats_emit_time = time.time()

                self._emit_status("运行中...")
                if self._scan_interval > 0:
                    self._sleep_interruptible(self._scan_interval / 1000.0)

        # 循环退出后若有余量，缓存到实例属性供主线程原子结算，无需重复 emit 避免多线程时序下重复累加
        if cycle_scan_delta > 0:
            delta_pkt = {
                "scan_delta": cycle_scan_delta,
                "scan_cost_delta_ms": cycle_scan_cost_ms,
                "last_cost_ms": last_scan_cost_ms,
                "elapsed_sec": time.time() - start_time,
            }
            self.final_stats_delta = delta_pkt
            cycle_scan_delta = 0
            cycle_scan_cost_ms = 0.0

        self._emit_status("已停止")

    def _sleep_interruptible(self, seconds: float) -> None:
        """可被打断的 sleep，使用 Event.wait 实现毫秒级精确等待与即时响应 (BUG-07, BUG-10)."""
        self._stop_event.wait(timeout=max(0.0, seconds))

    def stop(self) -> None:
        self._stop_event.set()

