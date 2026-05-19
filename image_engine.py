"""
模块二: 图像引擎 (image_engine.py)
===============================
功能: 封装屏幕截图与 OpenCV 模板匹配, 供主引擎循环调用.
所有函数保持无状态(stateless), 不在模块内存储全局变量.

对外接口:
  - take_screenshot() -> numpy.ndarray       # 截全屏, 返回 BGR 数组
  - load_template(image_path) -> numpy.ndarray | None  # 加载模板图
  - find_template(screenshot, template, threshold) -> (x,y,w,h) | None  # 模板匹配
"""

import logging

import cv2
import numpy as np
import mss

logger = logging.getLogger(__name__)


def take_screenshot() -> np.ndarray:
    """
    使用 mss 截取全屏, 返回 BGR 格式的 numpy 数组.
    若 mss 初始化失败, fallback 到 pyautogui.screenshot().
    mss 对象在函数内部创建和销毁, 避免长时间占用资源.
    """
    try:
        with mss.mss() as sct:
            # monitors[1] 为主显示器
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            img = np.array(sct_img)
            # mss 返回 BGRA 格式, 丢弃 alpha 通道, 保留 BGR
            # ascontiguousarray 确保内存连续, 防止 OpenCV 底层崩溃
            return np.ascontiguousarray(img[:, :, :3])
    except Exception as e:
        logger.warning(f"mss 截图失败, 尝试 pyautogui fallback: {e}")
        try:
            import pyautogui
            pil_img = pyautogui.screenshot()
            # pyautogui 返回 RGB PIL Image, 转为 BGR 的 numpy 数组
            img = np.array(pil_img)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return np.ascontiguousarray(img)
        except Exception as e2:
            logger.error(f"pyautogui fallback 也失败了: {e2}")
            raise RuntimeError("无法截取屏幕: mss 和 pyautogui 均失败") from e2


def load_template(image_path: str) -> np.ndarray | None:
    """
    从路径加载模板图, 转为 BGR 格式.
    使用 np.fromfile + cv2.imdecode 绕开 cv2.imread 不支持中文路径的问题.
    加载失败时返回 None, 打印错误信息, 不抛出异常.
    """
    try:
        data = np.fromfile(image_path, dtype=np.uint8)
        if data.size == 0:
            logger.error(f"无法加载模板图片(文件为空或不存在): {image_path}")
            return None
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            logger.error(f"无法解码模板图片: {image_path}")
            return None
        return img
    except Exception as e:
        logger.error(f"加载模板图片异常: {image_path}, {e}")
        return None


def find_template(
    screenshot: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.8,
) -> tuple[int, int, int, int] | None:
    """
    使用 cv2.matchTemplate + TM_CCOEFF_NORMED 进行模板匹配.
    若最高匹配分数 >= threshold, 返回匹配区域 (x, y, w, h).
    否则返回 None.
    匹配过程出错时返回 None 并记录日志, 不崩溃.
    """
    try:
        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val >= threshold:
            h, w = template.shape[:2]
            return (max_loc[0], max_loc[1], w, h)
        return None
    except Exception as e:
        logger.error(f"模板匹配过程出错: {e}")
        return None
