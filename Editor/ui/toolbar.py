# -*- coding: utf-8 -*-
"""工具栏：项目名 + 常用操作按钮（V3 起启用功能）。按钮使用 PNG 小图标。"""

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"


class Toolbar(ttk.Frame):
    """编辑器顶部工具栏。"""

    def __init__(self, master, projectName="未命名项目", **kw):
        super().__init__(master, **kw)
        self._images = {}
        ttk.Label(self, text=f"项目：{projectName}", padding=(8, 4)).pack(side=tk.LEFT)

        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._iconButton("创建立方体", "cube.png", "V3 实现：创建物体")
        self._iconButton("创建球体", "sphere.png", "V3 实现：创建物体")
        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._iconButton("播放", "play.png", "播放模式 V4 实现")

    def _iconButton(self, text, iconName, hint):
        """带 PNG 小图标的按钮；图标缺失时退化为纯文字。"""
        btn = ttk.Button(self, text=text, compound=tk.LEFT)
        iconPath = ICONS_DIR / iconName
        if iconPath.exists():
            self._images[iconName] = tk.PhotoImage(file=str(iconPath))
            btn.config(image=self._images[iconName])
        btn.config(command=lambda: messagebox.showinfo("Vortex 编辑器", f"「{text}」{hint}。"))
        btn.pack(side=tk.LEFT, padx=2)