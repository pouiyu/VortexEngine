# -*- coding: utf-8 -*-
"""工具栏：项目名 + 创建物体下拉列表 + Gizmo 模式切换 + 播放/停止（V5）。

创建物体改为「选择列表」：点按钮弹菜单，列出空物体 / 立方体 / 球体 /
方向光 / 点光源（kind 交给 main.createObject 处理）。
Gizmo 模式：移动 / 旋转 / 缩放三个互斥按钮（onGizmoMode 回调给 main）。
播放：▶ 播放 / ⏹ 停止（onPlay 回调给 main，播放中按钮文字变化）。
"""

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

# 创建列表：显示名 → kind（与 main.CREATE_OPTIONS 保持一致）
CREATE_ITEMS = [
    ("空物体", "empty"),
    ("立方体", "cube"),
    ("球体", "sphere"),
    ("摄像机", "camera"),
    ("方向光", "directional"),
    ("点光源", "point"),
]

# Gizmo 模式按钮：显示名 → mode（与 GLViewport.gizmoMode 一致）
GIZMO_MODES = [
    ("移动", "move"),
    ("旋转", "rotate"),
    ("缩放", "scale"),
]


class Toolbar(ttk.Frame):
    """编辑器顶部工具栏。

    onCreate(kind)：由 main 提供，kind 为 CREATE_ITEMS 中的值。
    onGizmoMode(mode)：由 main 提供，切换视口 Gizmo 模式。
    onPlay()：由 main 提供，切换播放/停止。
    """

    def __init__(self, master, projectName="未命名项目", onCreate=None,
                 onGizmoMode=None, onPlay=None, **kw):
        super().__init__(master, **kw)
        self._images = {}
        self.onCreate = onCreate
        self.onGizmoMode = onGizmoMode
        self.onPlay = onPlay
        self._gizmoButtons = {}
        self._gizmoModeVar = tk.StringVar(value="move")
        ttk.Label(self, text=f"项目：{projectName}", padding=(8, 4)).pack(side=tk.LEFT)

        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._createMenu()
        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._gizmoButtonsRow()
        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._playBtn = ttk.Button(self, text="▶ 播放", command=self._togglePlay)
        self._playBtn.pack(side=tk.LEFT, padx=2)

    def _togglePlay(self):
        if self.onPlay:
            self.onPlay()

    def setPlaying(self, playing):
        """播放状态切换：按钮文字 ▶ 播放 / ⏹ 停止。"""
        self._playBtn.config(text="⏹ 停止" if playing else "▶ 播放")

    def _createMenu(self):
        """「创建物体」下拉：选项来自 CREATE_ITEMS（选择列表）。"""
        menubtn = ttk.Menubutton(self, text="创建物体 ▼")
        menu = tk.Menu(menubtn, tearoff=0)
        for label, kind in CREATE_ITEMS:
            menu.add_command(label=label, command=lambda k=kind: self._trigger(k, label))
        menubtn.config(menu=menu)
        menubtn.pack(side=tk.LEFT, padx=2)

    def _gizmoButtonsRow(self):
        """Gizmo 模式互斥按钮（移动/旋转/缩放），选中项高亮。"""
        for label, mode in GIZMO_MODES:
            rb = ttk.Radiobutton(self, text=label, value=mode,
                                 variable=self._gizmoModeVar,
                                 command=lambda m=mode: self._triggerGizmo(m))
            rb.pack(side=tk.LEFT, padx=2)
            self._gizmoButtons[mode] = rb

    def _triggerGizmo(self, mode):
        if self.onGizmoMode:
            self.onGizmoMode(mode)

    def setGizmoMode(self, mode):
        """外部（键盘 W/E/R 切换）同步按钮状态。"""
        if mode in self._gizmoButtons:
            self._gizmoModeVar.set(mode)

    def _trigger(self, kind, text):
        if self.onCreate:
            self.onCreate(kind)
        else:
            messagebox.showinfo("Vortex 编辑器", f"「{text}」创建功能未接线。")
