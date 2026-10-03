# -*- coding: utf-8 -*-
"""工具栏：项目名 + 常用操作按钮（V3 起启用创建物体等）。"""

import tkinter as tk
from tkinter import messagebox, ttk


class Toolbar(ttk.Frame):
    """编辑器顶部工具栏。"""

    def __init__(self, master, projectName="未命名项目", **kw):
        super().__init__(master, **kw)
        ttk.Label(self, text=f"项目：{projectName}", padding=(8, 4)).pack(side=tk.LEFT)

        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._addButton("创建立方体", "V3 实现")
        self._addButton("创建球体", "V3 实现")
        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._addButton("播放 ▶", "播放模式 V4 实现")

    def _addButton(self, text, hint):
        ttk.Button(self, text=text,
                   command=lambda: messagebox.showinfo("Vortex 编辑器", f"「{text}」{hint}。")).pack(side=tk.LEFT, padx=2)