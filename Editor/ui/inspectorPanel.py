# -*- coding: utf-8 -*-
"""检查器面板：显示选中物体的属性（V2 只读展示，V3 支持编辑）。"""

import tkinter as tk
from tkinter import ttk


class InspectorPanel(ttk.Frame):
    """显示选中物体的名称 / 激活 / 变换。"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.selected = None

        ttk.Label(self, text="检查器", padding=(6, 3)).pack(fill=tk.X)
        self.proxy = ttk.Frame(self)
        self.proxy.pack(fill=tk.BOTH, expand=True)
        self._buildEmpty()

    def showObject(self, obj):
        """显示物体的属性；obj 为 None 时显示空提示。"""
        self.selected = obj
        for child in self.proxy.winfo_children():
            child.destroy()
        if obj is None:
            self._buildMessage("请选择物体")
            return
        ttk.Label(self.proxy, text=obj.name, font=("Segoe UI", 11, "bold")).pack(padx=8, pady=(6, 2), anchor=tk.W)
        ttk.Label(self.proxy, text="激活" if obj.active else "未激活").pack(padx=8, anchor=tk.W)
        t = obj.transform
        for label, vec in (("位置", t.position), ("旋转", t.rotation), ("缩放", t.scale)):
            ttk.Label(self.proxy, text=f"{label} {vec[0]:.2f}, {vec[1]:.2f}, {vec[2]:.2f}").pack(padx=8, anchor=tk.W)

    def _buildEmpty(self):
        self._buildMessage("请选择物体")

    def _buildMessage(self, text):
        ttk.Label(self.proxy, text=text, foreground="#666").pack(padx=8, pady=12, anchor=tk.NW)