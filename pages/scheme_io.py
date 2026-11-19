from __future__ import annotations
from typing import TYPE_CHECKING

import os
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from config_manager import (
    export_scheme, write_scheme_file, parse_scheme_file,
    restore_task_image, restore_stop_image,
)
from styles.colors import (
    CLR_CARD_BG, CLR_CARD_BORDER, CLR_TEXT_MAIN, CLR_BTN_PRIMARY,
)

if TYPE_CHECKING:
    from main_window import MainWindow


def styled_msgbox(main_win: MainWindow) -> QMessageBox:
    """创建置顶且采用项目统一配色的提示框。"""
    msg = QMessageBox(main_win)
    msg.setWindowFlags(msg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    msg.setStyleSheet(f"""
        QMessageBox {{ background: {CLR_CARD_BG}; }}
        QMessageBox QLabel {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
        QPushButton {{
            background: {CLR_CARD_BG}; border: 1px solid {CLR_CARD_BORDER};
            border-radius: 6px; padding: 6px 16px; font-size: 12px;
            color: {CLR_TEXT_MAIN}; min-width: 60px;
        }}
        QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
    """)
    return msg


def exec_msgbox_centered(main_win: MainWindow, msg: QMessageBox) -> None:
    """显示消息框并在主屏幕居中。"""
    msg.adjustSize()
    screen = QApplication.screenAt(main_win.geometry().center()) or QApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        msg.move(geo.center().x() - msg.width() // 2, geo.center().y() - msg.height() // 2)
    msg.exec()


def export_scheme_dialog(main_win: MainWindow) -> None:
    """导出当前任务、停止条件及其图片为方案文件。"""
    if not main_win._task_cards:
        msg = styled_msgbox(main_win)
        msg.setWindowTitle("提示")
        msg.setText("当前没有任务可导出。")
        exec_msgbox_centered(main_win, msg)
        return

    if len(main_win._task_cards) == 1:
        name = main_win._task_cards[0].name_edit.text().strip() or "方案"
        default_name = f"{name}.galt"
    else:
        default_name = f"方案_{int(time.time())}.galt"
    path, _ = QFileDialog.getSaveFileName(
        main_win, "导出方案", default_name, "方案文件 (*.galt);;所有文件 (*)"
    )
    if not path:
        return

    task_data = [card.to_dict() for card in main_win._task_cards]
    stop_conditions = main_win._collect_stop_conditions()
    export_obj = export_scheme(task_data, stop_conditions, main_win._stop_image_path)
    try:
        write_scheme_file(path, export_obj)
        msg = styled_msgbox(main_win)
        msg.setWindowTitle("导出成功")
        msg.setText(f"方案已保存到:\n{path}")
        exec_msgbox_centered(main_win, msg)
    except Exception as exc:
        msg = styled_msgbox(main_win)
        msg.setWindowTitle("导出失败")
        msg.setText(f"保存文件时出错:\n{exc}")
        exec_msgbox_centered(main_win, msg)


def import_scheme_dialog(main_win: MainWindow) -> None:
    """导入方案，先验证任务结构，再按用户选择应用任务与停止条件。"""
    path, _ = QFileDialog.getOpenFileName(
        main_win, "导入方案", "", "方案文件 (*.galt);;所有文件 (*)"
    )
    if not path:
        return

    try:
        tasks_data, imported_stop_conditions, stop_image_filename, stop_image_data = parse_scheme_file(path)
    except Exception as exc:
        msg = styled_msgbox(main_win)
        msg.setWindowTitle("导入失败")
        msg.setText(f"无法读取文件:\n{exc}")
        exec_msgbox_centered(main_win, msg)
        return

    if not isinstance(tasks_data, list):
        msg = styled_msgbox(main_win)
        msg.setWindowTitle("导入失败")
        msg.setText("方案文件格式无效：tasks 字段不是列表")
        exec_msgbox_centered(main_win, msg)
        return

    msg = styled_msgbox(main_win)
    msg.setWindowTitle("导入方案")
    msg.setText("请选择导入方式：")
    msg.setInformativeText("替换：清空当前任务后导入\n新增：追加到当前任务末尾")
    btn_replace = msg.addButton("替换", QMessageBox.ButtonRole.AcceptRole)
    btn_append = msg.addButton("新增", QMessageBox.ButtonRole.ActionRole)
    msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    exec_msgbox_centered(main_win, msg)
    clicked = msg.clickedButton()
    if clicked not in (btn_replace, btn_append):
        return

    is_replace = clicked == btn_replace
    apply_stop_conditions = is_replace
    if is_replace:
        main_win._clear_tasks_no_anim()
        main_win._stop_conditions_page.stop_image_path = None

    if (clicked == btn_append and isinstance(imported_stop_conditions, dict)
            and imported_stop_conditions.get("enabled", False)):
        msg_sc = styled_msgbox(main_win)
        msg_sc.setWindowTitle("导入停止条件")
        msg_sc.setText("新增方案包含停止条件，是否覆盖当前的停止条件？")
        msg_sc.setInformativeText(
            "是：将当前的停止条件替换为新增方案的停止条件\n"
            "否：保留当前的停止条件，不做改动"
        )
        btn_sc_yes = msg_sc.addButton("是", QMessageBox.ButtonRole.AcceptRole)
        btn_sc_no = msg_sc.addButton("否", QMessageBox.ButtonRole.NoRole)
        msg_sc.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        exec_msgbox_centered(main_win, msg_sc)
        if msg_sc.clickedButton() not in (btn_sc_yes, btn_sc_no):
            return
        apply_stop_conditions = msg_sc.clickedButton() == btn_sc_yes

    kept_names: set[str] = set()
    renamed_map: dict[str, str] = {}
    for item in tasks_data:
        if not isinstance(item, dict):
            continue
        restore_task_image(item)
        raw_name = item.get("name")
        orig_name = raw_name.strip() if isinstance(raw_name, str) else ""
        new_name = orig_name
        existing = {card.name_edit.text().strip() for card in main_win._task_cards}
        if not new_name:
            new_name = main_win._next_task_name()
        elif new_name in existing:
            suffix = 2
            while f"{new_name}({suffix})" in existing:
                suffix += 1
            new_name = f"{new_name}({suffix})"
        item["name"] = new_name
        if orig_name and new_name == orig_name:
            kept_names.add(orig_name)
        elif (orig_name and new_name != orig_name and orig_name not in kept_names
              and orig_name not in renamed_map):
            renamed_map[orig_name] = new_name
        main_win._add_task(item, refresh_combo=False)

    main_win._refresh_stop_task_combo()

    if apply_stop_conditions:
        if isinstance(imported_stop_conditions, dict):
            tc = imported_stop_conditions.get("task_exec_count")
            if isinstance(tc, dict) and isinstance(tc.get("task_name"), str):
                stripped = tc["task_name"].strip()
                if stripped in renamed_map:
                    tc["task_name"] = renamed_map[stripped]
        restored = restore_stop_image(stop_image_filename, stop_image_data, None)
        main_win._stop_conditions_page.apply_stop_conditions(
            imported_stop_conditions,
            stop_image_path=restored or "",
            is_replace_mode=is_replace,
        )
        main_win._global_settings["stop_conditions"] = (
            main_win._stop_conditions_page.collect_stop_conditions()
        )

    main_win._save_config()
