"""
配置持久化与方案导入导出 (config_manager.py)
"""

import base64
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

if getattr(sys, "frozen", False):
    _app_dir = os.path.dirname(os.path.abspath(sys.executable))
else:
    _app_dir = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_app_dir, "config.json")
SCREENSHOTS_DIR = os.path.join(_app_dir, "screenshots")


def save_config(settings: dict, tasks: list[dict]) -> None:
    """将全局设置和任务列表写入 config.json。"""
    data = {"settings": settings, "tasks": tasks}
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存配置失败: {e}")


def load_config() -> dict | None:
    """
    从 config.json 读取配置，返回原始 dict。
    文件不存在返回 None，解析失败也返回 None（调用方负责处理默认值）。
    """
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        return None


def export_scheme(
    task_cards_data: list[dict],
    stop_conditions: dict,
    stop_image_path: str | None,
) -> dict:
    """
    将任务卡片数据 + 停止条件 + 停止图片序列化为可写入 .galt 文件的 dict。
    调用方负责弹文件对话框和写磁盘。
    """
    data = []
    for task_data in task_cards_data:
        task_data = dict(task_data)  # 浅拷贝，不污染调用方传入的原始 dict
        img_path = task_data.get("image_path", "")
        if img_path and os.path.exists(img_path):
            task_data["image_filename"] = os.path.basename(img_path)
            try:
                with open(img_path, "rb") as img_f:
                    task_data["image_data"] = base64.b64encode(
                        img_f.read()
                    ).decode("utf-8")
            except Exception:
                pass
        data.append(task_data)

    export_obj: dict = {"tasks": data}

    sc = dict(stop_conditions)
    if "image_match_stop" in sc:
        sc["image_match_stop"] = {
            k: v for k, v in sc["image_match_stop"].items() if k != "image_path"
        }
    export_obj["stop_conditions"] = sc

    if stop_image_path and os.path.exists(stop_image_path):
        export_obj["stop_image_filename"] = os.path.basename(stop_image_path)
        try:
            with open(stop_image_path, "rb") as img_f:
                export_obj["stop_image_data"] = base64.b64encode(
                    img_f.read()
                ).decode("utf-8")
        except Exception:
            pass

    return export_obj


def write_scheme_file(path: str, export_obj: dict) -> None:
    """将 export_obj 写入磁盘。自动创建目标目录（如不存在）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export_obj, f, ensure_ascii=False, indent=2)


def parse_scheme_file(path: str) -> tuple[list[dict], dict | None, str, str]:
    """
    解析 .galt 文件，返回：
      (tasks_data, stop_conditions, stop_image_filename, stop_image_data)
    解析失败抛出异常，由调用方捕获并弹错误对话框。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        tasks_data = data.get("tasks", [])
        stop_image_filename = data.get("stop_image_filename", "")
        stop_image_data = data.get("stop_image_data", "")
        stop_conditions = data.get("stop_conditions")
    elif isinstance(data, list) and all(isinstance(i, dict) for i in data):
        tasks_data = data
        stop_image_filename = ""
        stop_image_data = ""
        stop_conditions = None
    else:
        raise ValueError("文件格式不正确，需要是有效的方案文件。")

    return tasks_data, stop_conditions, stop_image_filename, stop_image_data


def restore_task_image(item: dict) -> dict:
    """
    检查单条任务配置里的图片路径是否有效，若丢失则尝试：
      1. screenshots/ 目录下同名文件
      2. base64 解码还原
    返回修改后的 item（原地修改并返回）。
    """
    img_path = item.get("image_path", "")
    if img_path and os.path.exists(img_path):
        return item  # 原图还在，直接用

    img_filename = item.get("image_filename", "")
    if not img_filename:
        return item

    restored_path = os.path.join(SCREENSHOTS_DIR, img_filename)
    if os.path.exists(restored_path):
        item["image_path"] = restored_path
        return item

    if item.get("image_data"):
        try:
            img_bytes = base64.b64decode(item["image_data"])
            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
            with open(restored_path, "wb") as img_f:
                img_f.write(img_bytes)
            item["image_path"] = restored_path
        except Exception as e:
            logger.error(f"从方案还原图片失败: {e}")

    return item


def restore_stop_image(
    stop_image_filename: str,
    stop_image_data: str,
    current_stop_image_path: str | None,
) -> str | None:
    """
    尝试还原停止条件图片，返回有效路径或 None。
    """
    if not stop_image_filename:
        return current_stop_image_path

    if current_stop_image_path and os.path.exists(current_stop_image_path):
        return current_stop_image_path

    restored_path = os.path.join(SCREENSHOTS_DIR, stop_image_filename)
    if os.path.exists(restored_path):
        return restored_path

    if stop_image_data:
        try:
            img_bytes = base64.b64decode(stop_image_data)
            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
            with open(restored_path, "wb") as img_f:
                img_f.write(img_bytes)
            return restored_path
        except Exception as e:
            logger.error(f"从方案还原停止条件图片失败: {e}")

    return None
