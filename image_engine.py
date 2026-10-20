"""
模块二: 图像引擎 (image_engine.py)
===============================
功能: 封装屏幕截图与 OpenCV 模板匹配, 供主引擎与后台线程调用.
支持基于线程本地存储 (TLS) 的 mss 句柄复用与释放机制, 避免多线程句柄冲突与频繁创建销毁.

对外接口:
  - take_screenshot() -> numpy.ndarray       # 截全屏, 返回 BGR 数组 (带重建重试与 fallback)
  - close_thread_sct() -> None               # 显式释放当前线程本地 mss 实例与 GDI 资源
  - load_template(image_path) -> numpy.ndarray | None  # 加载模板图
  - find_best_match(screenshot, template, search_region=None) -> (x,y,w,h,score) | None # 无阈值最佳匹配
  - find_template_with_score(screenshot, template, threshold, search_region=None) -> (x,y,w,h,score) | None
  - find_template(screenshot, template, threshold) -> (x,y,w,h) | None  # 模板匹配
"""

import logging
import threading

import cv2
import numpy as np
import mss

logger = logging.getLogger(__name__)

_tls = threading.local()


def _get_thread_sct() -> mss.mss:
    """获取当前线程绑定的 mss 实例, 若不存在则初始化."""
    sct = getattr(_tls, "sct", None)
    if sct is None:
        sct = mss.mss()
        _tls.sct = sct
    return sct


def close_thread_sct() -> None:
    """显式释放当前线程绑定的 mss 实例与 GDI 资源 (FEAT-05)."""
    sct = getattr(_tls, "sct", None)
    if sct is not None:
        try:
            sct.close()
        except Exception:
            pass
        _tls.sct = None


def take_screenshot() -> np.ndarray:
    """
    使用 mss 截取全屏, 返回 BGR 格式的 numpy 数组.
    基于 TLS 缓存复用 mss 实例; 若捕获异常, 自动关闭句柄并重建重试一次;
    若重试仍然失败, 则安全回退至 pyautogui.screenshot() 兜底 (FEAT-05).
    """
    def _grab() -> np.ndarray:
        sct = _get_thread_sct()
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        img = np.array(sct_img)
        # mss 返回 BGRA 格式, 丢弃 alpha 通道, 保留 BGR
        # ascontiguousarray 确保内存连续, 防止 OpenCV 底层崩溃
        return np.ascontiguousarray(img[:, :, :3])

    try:
        return _grab()
    except Exception as e:
        logger.warning(f"mss 截图初次失败, 尝试重建句柄重试: {e}")
        close_thread_sct()
        try:
            return _grab()
        except Exception as e2:
            logger.warning(f"mss 重建重试仍失败, 降级至 pyautogui: {e2}")
            try:
                import pyautogui
                pil_img = pyautogui.screenshot()
                img = np.array(pil_img)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                return np.ascontiguousarray(img)
            except Exception as e3:
                logger.error(f"pyautogui fallback 也失败了: {e3}")
                raise RuntimeError("无法截取屏幕: mss 和 pyautogui 均失败") from e3


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


def find_best_match(
    screenshot: np.ndarray,
    template: np.ndarray,
    search_region: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int, float] | None:
    """
    支持限定 search_region 的全图最高分无阈值匹配接口 (FEAT-02, FEAT-04).
    若指定 search_region (x, y, w, h)，将在截图切片内匹配，但返回值始终加上 (offset_x, offset_y)，
    确保返回的 (x, y, w, h, score) 始终为全屏绝对物理像素坐标.
    若模板图尺寸大于搜索区域或全屏截图, 返回 None.
    """
    if template is None or screenshot is None:
        return None

    img_h, img_w = screenshot.shape[:2]
    if search_region is not None:
        try:
            rx, ry, rw, rh = search_region
            x1 = max(0, min(int(rx), img_w))
            y1 = max(0, min(int(ry), img_h))
            x2 = max(0, min(int(rx + rw), img_w))
            y2 = max(0, min(int(ry + rh), img_h))
            if x2 <= x1 or y2 <= y1:
                return None
            crop = screenshot[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1
        except Exception as e:
            logger.error(f"search_region 解析异常: {e}")
            return None
    else:
        crop = screenshot
        offset_x, offset_y = 0, 0

    th, tw = template.shape[:2]
    ch, cw = crop.shape[:2]
    if tw > cw or th > ch:
        return None

    try:
        result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        score = max(0.0, min(1.0, float(max_val))) if np.isfinite(max_val) else 0.0
        return (max_loc[0] + offset_x, max_loc[1] + offset_y, tw, th, score)
    except Exception as e:
        logger.error(f"模板匹配过程出错: {e}")
        return None


def find_template_with_score(
    screenshot: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.8,
    search_region: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int, float] | None:
    """支持 search_region 的模板匹配，保持全代码库单一数据源 (FEAT-02, FEAT-04)."""
    res = find_best_match(screenshot, template, search_region=search_region)
    if res and res[4] >= threshold:
        return res
    return None


def find_template(
    screenshot: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.8,
) -> tuple[int, int, int, int] | None:
    """
    使用 cv2.matchTemplate + TM_CCOEFF_NORMED 进行模板匹配.
    若最高匹配分数 >= threshold, 返回匹配区域 (x, y, w, h). 否则返回 None.
    """
    res = find_template_with_score(screenshot, template, threshold)
    if res:
        return res[:4]
    return None

