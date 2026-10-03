# -*- coding: utf-8 -*-
"""工具栏：项目名 + 创建物体按钮（V3 起可用）+ 播放占位。按钮使用 PNG 小图标。"""

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"


class Toolbar(ttk.Frame):
    """编辑器顶部工具栏。

    onCreate(kind)：由 main 提供，kind 为 "empty" / "cube" / "sphere"。
    """

    def __init__(self, master, projectName="未命名项目", onCreate=None, **kw):
        super().__init__(master, **kw)
        self._images = {}
        self.onCreate = onCreate
        ttk.Label(self, text=f"项目：{projectName}", padding=(8, 4)).pack(side=tk.LEFT)

        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._iconButton("创建立方体", "cube.png", "cube")
        self._iconButton("创建球体", "sphere.png", "sphere")
        self._textButton("空物体", "empty")
        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._textButton("播放", None, hint="播放模式 V5 实现")

    def _iconButton(self, text, iconName, kind):
        """带 PNG 小图标的创建按钮；图标缺失时退化为纯文字。"""
        btn = ttk.Button(self, text=text, compound=tk.LEFT)
        iconPath = ICONS_DIR / iconName
        if iconPath.exists():
            self._images[iconName] = tk.PhotoImage(file=str(iconPath))
            btn.config(image=self._images[iconName])
        btn.config(command=lambda: self._trigger(kind, text))
        btn.pack(side=tk.LEFT, padx=2)

    def _textButton(self, text, kind, hint=None):
        """纯文字按钮（空物体 / 播放占位）。"""
        btn = ttk.Button(self, text=text)
        btn.config(command=lambda: self._trigger(kind, text, hint))
        btn.pack(side=tk.LEFT, padx=2)

    def _trigger(self, kind, text, hint=None):
        if kind is None:
            messagebox.showinfo("Vortex 编辑器", f"「{text}」{hint or '待实现'}。")
        elif self.onCreate:
            self.onCreate(kind)
        else:
            messagebox.showinfo("Vortex 编辑器", f"「{text}」创建功能未接线。")
