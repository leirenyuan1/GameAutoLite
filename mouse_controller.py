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

import random
import time
import math

import win32api
import win32con


def _real_click(speed: float = 1.0) -> None:
    """
    执行真实按压点击.
    严禁使用任何封装好的 click() 函数, 必须拆分为:
      1. mouse_event LEFTDOWN   -- 按下
      2. sleep(50~150ms)        -- 随机停留
      3. mouse_event LEFTUP     -- 松开
    """
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    time.sleep(random.uniform(0.05, 0.15) / speed)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)


def _bezier_move(tx: int, ty: int, speed: float = 1.0) -> None:
    """
    四阶贝塞尔曲线移动鼠标到目标点(tx, ty).
    包含: 随机控制点偏移 + 物理惯性速度曲线 + 路径抖动 + 动态耗时.
    """
    sx, sy = win32api.GetCursorPos()

    # 计算起点到终点的像素距离
    dist = math.hypot(tx - sx, ty - sy)

    # 按距离动态分配总耗时, speed 越大越快
    if dist < 200:
        total_time = random.uniform(0.15, 0.3) / speed
    else:
        total_time = random.uniform(0.4, 0.65) / speed

    # 采样点数: 60~80 个
    num_samples = random.randint(60, 80)

    # 生成 3 个随机控制点, 在起点和终点连线的等分点附近随机偏移 ±120px
    control_points = []
    for i in range(1, 4):  # i = 1, 2, 3
        base_x = sx + (tx - sx) * i / 4
        base_y = sy + (ty - sy) * i / 4
        cp_x = int(base_x + random.randint(-120, 120))
        cp_y = int(base_y + random.randint(-120, 120))
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

    # 逐点移动
    for i in range(num_samples):
        t = i / (num_samples - 1) if num_samples > 1 else 0

        # 四阶贝塞尔公式: B(t) = (1-t)^4*P0 + 4(1-t)^3*t*P1 + 6(1-t)^2*t^2*P2 + 4(1-t)*t^3*P3 + t^4*P4
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
        if i > 0 and i < num_samples - 1:
            px += random.randint(-2, 2)
            py += random.randint(-2, 2)

        # 本步耗时 = 总耗时 * (当前速度系数 / 总速度系数)
        step_time = total_time * speed_factors[i] / total_speed

        win32api.SetCursorPos((int(px), int(py)))
        time.sleep(step_time)


def click_in_region(x: int, y: int, w: int, h: int, move_speed: float = 1.0, click_speed: float = 1.0) -> None:
    """
    在矩形区域内随机取点, 贝塞尔曲线移动过去, 执行真实按压点击.
    调用方只需传入区域坐标, 内部自动完成全部步骤.

    参数:
        x, y: 矩形左上角坐标
        w, h: 矩形宽高
    """
    # 第一步: 在区域内均匀随机取点(禁止取中心点)
    tx = random.randint(x, x + w)
    ty = random.randint(y, y + h)

    # 第二步: 贝塞尔曲线移动到目标点
    _bezier_move(tx, ty, move_speed)

    # 第三步: 真实按压点击
    _real_click(click_speed)


def click_in_regions(
    regions: list,
    move_speed: float = 1.0,
    click_speed: float = 1.0,
) -> None:
    """
    从多个区域中按面积加权随机选一个, 再在其中随机取点点击.
    大区域被选中的概率更高, 行为更自然.
    """
    if not regions:
        return
    weights = [w * h for _, _, w, h in regions]
    x, y, w, h = random.choices(regions, weights=weights, k=1)[0]
    tx = random.randint(x, x + w)
    ty = random.randint(y, y + h)
    _bezier_move(tx, ty, move_speed)
    _real_click(click_speed)


def click_in_region_multi(
    x: int, y: int, w: int, h: int,
    count: int,
    interval_range: tuple = (0.15, 0.25),
    offset_range: int = 4,
    stop_event=None,
    move_speed: float = 1.0,
    click_speed: float = 1.0,
) -> None:
    """
    在区域内多次点击, 用于双击/连击.
    第一次: 随机取点 + 贝塞尔移动 + 真实点击(无偏移).
    后续每次: 随机间隔 + 随机偏移(钳制在区域内) + 贝塞尔移动 + 真实点击.
    """
    tx = random.randint(x, x + w)
    ty = random.randint(y, y + h)
    _bezier_move(tx, ty, move_speed)
    _real_click(click_speed)

    for i in range(1, count):
        if stop_event and stop_event.is_set():
            break

        interval = random.uniform(interval_range[0], interval_range[1]) / click_speed
        end = time.time() + interval
        while time.time() < end:
            if stop_event and stop_event.is_set():
                return
            time.sleep(0.05)

        if stop_event and stop_event.is_set():
            break

        dx = random.randint(-offset_range, offset_range)
        dy = random.randint(-offset_range, offset_range)
        tx = max(x, min(x + w, tx + dx))
        ty = max(y, min(y + h, ty + dy))

        _bezier_move(tx, ty, move_speed)
        _real_click(click_speed)
