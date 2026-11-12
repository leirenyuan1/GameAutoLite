"""
模块一: 鼠标控制器 (mouse_controller.py)
===============================
功能: 专门负责所有鼠标操作, 是软件防检测的核心.
对外接口: click_in_region(x, y, w, h) -- 在矩形区域内随机取点, 贝塞尔曲线移动过去, 执行真实按压点击.

内部实现:
  1. 区域内随机取点
  2. 四阶贝塞尔曲线路径移动(物理惯性速度曲线 + 路径抖动)
  3. 拆分为 mouseDown + 随机停留 + mouseUp 的真实点击
"""

from contextlib import contextmanager
import ctypes
import logging
import math
import random
import time

import win32api
import win32con


logger = logging.getLogger(__name__)


@contextmanager
def _high_res_timer():
    """临时开启 Windows 1ms 高精度多媒体定时器，确保贝塞尔采样帧率跑满不跳帧."""
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass
    try:
        yield
    finally:
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass


def _real_click(speed: float = 1.0) -> bool:
    """
    执行真实按压点击.
    严禁使用任何封装好的 click() 函数, 必须拆分为:
      1. mouse_event LEFTDOWN   -- 按下
      2. sleep(50~150ms)        -- 随机停留
      3. mouse_event LEFTUP     -- 松开（try...finally 保证 100% 触发）
    返回 True 表示点击成功，False 表示底层 API 失败。
    """
    try:
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        try:
            time.sleep(random.uniform(0.05, 0.15) / max(0.1, float(speed)))
        finally:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        return True
    except Exception as e:
        logger.error(f"鼠标点击事件失败: {e}")
        return False


def _bezier_move(tx: int, ty: int, speed: float = 1.0, stop_event=None) -> bool:
    """
    四阶贝塞尔曲线移动鼠标到目标点(tx, ty).
    包含: 随机控制点偏移 + 物理惯性速度曲线 + 路径抖动 + 动态耗时.
    支持通过 stop_event 在移动过程中毫秒级打断并返回 False.
    """
    if stop_event and stop_event.is_set():
        return False

    try:
        sx, sy = win32api.GetCursorPos()
    except Exception as e:
        logger.error(f"获取鼠标位置失败: {e}")
        return False

    # 计算起点到终点的像素距离
    dist = math.hypot(tx - sx, ty - sy)

    # 按距离动态分配总耗时, speed 越大越快
    safe_speed = max(0.1, float(speed))
    if dist < 200:
        total_time = random.uniform(0.15, 0.3) / safe_speed
    else:
        total_time = random.uniform(0.4, 0.65) / safe_speed

    # 采样点数: 60~80 个
    num_samples = random.randint(60, 80)

    # 生成 3 个随机控制点, 在起点和终点连线的等分点附近动态偏移
    max_offset = max(2, min(120, int(dist * 0.35)))
    control_points = []
    for i in range(1, 4):  # i = 1, 2, 3
        base_x = sx + (tx - sx) * i / 4
        base_y = sy + (ty - sy) * i / 4
        cp_x = int(base_x + random.randint(-max_offset, max_offset))
        cp_y = int(base_y + random.randint(-max_offset, max_offset))
        control_points.append((cp_x, cp_y))

    # 5 个控制点: P0(起点) + P1,P2,P3(随机) + P4(终点)
    P = [(sx, sy)] + control_points + [(tx, ty)]

    # 预计算每一步的速度系数(物理惯性曲线)
    speed_factors = []
    for i in range(num_samples):
        t = i / (num_samples - 1) if num_samples > 1 else 0
        if t < 0.2:
            # 前 20%: 起步慢, 间隔较长
            factor = 2.0
        elif t < 0.8:
            # 中间 60%: 匀速快, 间隔较短
            factor = 0.6
        else:
            # 后 20%: 临近减速, 间隔逐渐变长
            progress = (t - 0.8) / 0.2
            factor = 0.6 + 1.4 * progress
        speed_factors.append(factor)

    total_speed = sum(speed_factors)
    cum_times = []
    acc = 0.0
    for factor in speed_factors:
        acc += factor
        cum_times.append(acc / total_speed)
    if cum_times:
        cum_times[-1] = 1.0

    points = []
    for i in range(num_samples):
        t = i / (num_samples - 1) if num_samples > 1 else 1.0
        mt = 1 - t
        mt2 = mt * mt
        mt3 = mt2 * mt
        mt4 = mt3 * mt
        t2 = t * t
        t3 = t2 * t
        t4 = t3 * t

        px = (mt4 * P[0][0] +
              4 * mt3 * t * P[1][0] +
              6 * mt2 * t2 * P[2][0] +
              4 * mt * t3 * P[3][0] +
              t4 * P[4][0])
        py = (mt4 * P[0][1] +
              4 * mt3 * t * P[1][1] +
              6 * mt2 * t2 * P[2][1] +
              4 * mt * t3 * P[3][1] +
              t4 * P[4][1])

        # 中间采样点叠加 ±1~2px 随机抖动(首尾端点不抖)
        if 0 < i < num_samples - 1:
            px += random.randint(-2, 2)
            py += random.randint(-2, 2)
        points.append((int(px), int(py)))

    with _high_res_timer():
        start_perf = time.perf_counter()
        last_idx = -1

        while True:
            if stop_event and stop_event.is_set():
                return False
            elapsed = time.perf_counter() - start_perf
            if elapsed >= total_time:
                break

            idx = 0
            for j in range(num_samples - 1):
                if elapsed >= total_time * cum_times[j]:
                    idx = j + 1
                else:
                    break

            if idx != last_idx:
                try:
                    win32api.SetCursorPos(points[idx])
                except Exception as e:
                    logger.error(f"设置鼠标位置失败: {e}")
                    return False
                last_idx = idx

            next_target = total_time * cum_times[idx]
            remain = next_target - (time.perf_counter() - start_perf)
            if remain > 0:
                wait_sec = min(0.002, remain)
                if stop_event:
                    if stop_event.wait(timeout=wait_sec):
                        return False
                else:
                    time.sleep(wait_sec)

        if stop_event and stop_event.is_set():
            return False
        try:
            win32api.SetCursorPos((int(tx), int(ty)))
        except Exception as e:
            logger.error(f"设置鼠标终点位置失败: {e}")
            return False
    return True


def _micro_move(tx: int, ty: int, speed: float = 1.0, stop_event=None) -> bool:
    """连击微距平滑步进（用于双击/连击的第 2~N 次微偏移移动，含中间步微颤防直线特征与防大甩尾）."""
    if stop_event and stop_event.is_set():
        return False
    try:
        sx, sy = win32api.GetCursorPos()
    except Exception as e:
        logger.error(f"获取鼠标位置失败: {e}")
        return False

    steps = random.randint(2, 4)
    total_time = random.uniform(0.015, 0.035) / max(0.1, float(speed))
    step_wait = total_time / steps
    with _high_res_timer():
        for s in range(1, steps + 1):
            if stop_event and stop_event.is_set():
                return False
            ratio = s / steps
            nx = int(round(sx + (tx - sx) * ratio))
            ny = int(round(sy + (ty - sy) * ratio))
            if s < steps:
                nx += random.choice([-1, 0, 1])
                ny += random.choice([-1, 0, 1])
            try:
                win32api.SetCursorPos((nx, ny))
            except Exception as e:
                logger.error(f"设置鼠标微距位置失败: {e}")
                return False
            if stop_event:
                if stop_event.wait(timeout=max(0.0, step_wait)):
                    return False
            else:
                time.sleep(max(0.0, step_wait))
    return True


def click_in_region(
    x: int, y: int, w: int, h: int,
    move_speed: float = 1.0,
    click_speed: float = 1.0,
    stop_event=None,
) -> list[tuple[int, int, float, float]]:
    """
    在矩形区域内随机取点, 贝塞尔曲线移动过去, 执行真实按压点击.
    调用方只需传入区域坐标, 内部自动完成全部步骤.
    若移动途中被 stop_event 打断, 则立即返回已记录的 clicks 并不执行真实点击.
    返回 list[tuple[int, int, float, float]], 元素为 (tx, ty, norm_x, norm_y).
    """
    clicks: list[tuple[int, int, float, float]] = []
    # 第一步: 在区域内均匀随机取点(禁止取中心点)
    tx = random.randint(x, x + max(0, w - 1))
    ty = random.randint(y, y + max(0, h - 1))

    # 第二步: 贝塞尔曲线移动到目标点
    if not _bezier_move(tx, ty, move_speed, stop_event=stop_event):
        return clicks

    # 第三步: 真实按压点击
    if not _real_click(click_speed):
        return clicks
    norm_x = (tx - x) / max(1, w)
    norm_y = (ty - y) / max(1, h)
    clicks.append((tx, ty, float(norm_x), float(norm_y)))
    return clicks


def click_in_regions(
    regions: list,
    move_speed: float = 1.0,
    click_speed: float = 1.0,
    stop_event=None,
    count: int = 1,
) -> list[tuple[int, int, float, float]]:
    """
    从多个区域中按面积加权随机选一个, 再在其中随机取点点击.
    大区域被选中的概率更高, 行为更自然.
    若移动途中被 stop_event 打断, 则立即返回已记录的 clicks.
    返回 list[tuple[int, int, float, float]], 元素为 (tx, ty, norm_x, norm_y).
    """
    if not regions or count <= 0:
        return []
    valid_regions = []
    for r in regions:
        if isinstance(r, (list, tuple)) and len(r) == 4:
            try:
                rx, ry, rw, rh = int(r[0]), int(r[1]), int(r[2]), int(r[3])
                if rw > 0 and rh > 0:
                    valid_regions.append((rx, ry, rw, rh))
            except (ValueError, TypeError):
                continue
    if not valid_regions:
        return []
    weights = [rw * rh for _, _, rw, rh in valid_regions]
    x, y, w, h = random.choices(valid_regions, weights=weights, k=1)[0]
    if count == 1:
        return click_in_region(
            x, y, w, h,
            move_speed=move_speed,
            click_speed=click_speed,
            stop_event=stop_event,
        )
    return click_in_region_multi(
        x, y, w, h,
        count=count,
        move_speed=move_speed,
        click_speed=click_speed,
        stop_event=stop_event,
    )


def click_in_region_multi(
    x: int, y: int, w: int, h: int,
    count: int,
    interval_range: tuple = (0.15, 0.25),
    offset_range: int = 4,
    stop_event=None,
    move_speed: float = 1.0,
    click_speed: float = 1.0,
) -> list[tuple[int, int, float, float]]:
    """
    在区域内多次点击, 用于双击/连击.
    第一次: 随机取点 + 贝塞尔移动 + 真实点击(无偏移).
    后续每次: 随机间隔 + 随机偏移(钳制在区域内) + 微距移动 + 真实点击.
    返回已实际完成点击的落点列表 clicks.
    """
    clicks: list[tuple[int, int, float, float]] = []
    if count <= 0:
        return clicks
    offset_range = max(0, int(offset_range))
    tx = random.randint(x, x + max(0, w - 1))
    ty = random.randint(y, y + max(0, h - 1))
    if not _bezier_move(tx, ty, move_speed, stop_event=stop_event):
        return clicks
    if not _real_click(click_speed):
        return clicks
    norm_x = (tx - x) / max(1, w)
    norm_y = (ty - y) / max(1, h)
    clicks.append((tx, ty, float(norm_x), float(norm_y)))

    for i in range(1, count):
        if stop_event and stop_event.is_set():
            break

        interval = random.uniform(interval_range[0], interval_range[1]) / max(0.1, float(click_speed))
        if stop_event:
            if stop_event.wait(timeout=max(0.0, interval)):
                return clicks
        else:
            time.sleep(max(0.0, interval))

        if stop_event and stop_event.is_set():
            break

        dx = random.randint(-offset_range, offset_range)
        dy = random.randint(-offset_range, offset_range)
        tx = max(x, min(x + max(0, w - 1), tx + dx))
        ty = max(y, min(y + max(0, h - 1), ty + dy))

        if not _micro_move(tx, ty, move_speed, stop_event=stop_event):
            return clicks
        if not _real_click(click_speed):
            return clicks
        norm_x = (tx - x) / max(1, w)
        norm_y = (ty - y) / max(1, h)
        clicks.append((tx, ty, float(norm_x), float(norm_y)))

    return clicks
