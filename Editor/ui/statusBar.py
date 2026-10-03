# -*- coding: utf-8 -*-
"""状态栏：项目路径 + FPS。"""

import tkinter as tk
from tkinter import ttk


class StatusBar(tk.Frame):
    """底部状态栏。"""

    def __init__(self, master, projectPath="", **kw):
        super().__init__(master, **kw)
        pathLabel = ttk.Label(self, text=f"路径：{projectPath}", padding=(8, 2))
        pathLabel.pack(side=tk.LEFT)
        self.msgVar = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.msgVar, padding=(8, 2)).pack(side=tk.LEFT)
        self.fpsVar = tk.StringVar(value="FPS --")
        ttk.Label(self, textvariable=self.fpsVar, padding=(8, 2)).pack(side=tk.RIGHT)

    def showFPS(self, fps):
        self.fpsVar.set(f"FPS {fps:.0f}")

    def showMessage(self, text):
        """临时消息（保存/打开结果提示）。"""
        self.msgVar.set(text)
        self.after(3000, lambda: self.msgVar.set("") if self.msgVar.get() == text else None)