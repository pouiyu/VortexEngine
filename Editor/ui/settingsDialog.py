# -*- coding: utf-8 -*-
"""设置对话框：旋转速度 / 平移灵敏度 / 移动速度 / 自定义按键。

确认后写回偏好并通知 main 应用（onApply）。"""

import tkinter as tk
from tkinter import ttk

MOVE_ACTIONS = [
    ("forward", "向前"),
    ("back", "后退"),
    ("left", "向左"),
    ("right", "向右"),
    ("up", "上升"),
    ("down", "下降"),
]


class SettingsDialog(tk.Toplevel):
    """设置窗口：滑杆调节速度，输入框改按键绑定。"""

    def __init__(self, master, prefs, onApply):
        super().__init__(master)
        self.prefs = prefs
        self.onApply = onApply
        self.title("设置")
        self.geometry("380x320")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)
        self._build()
        self._slider("旋转视角速度", "orbitSpeed", 0.2, 6.0)
        self._slider("平移灵敏度", "panSensitivity", 0.2, 6.0)
        self._slider("浏览移动速度", "moveSpeed", 0.2, 10.0)
        self._buildKeys()
        btns = ttk.Frame(self)
        btns.pack(pady=10)
        ttk.Button(btns, text="确定", command=self._apply).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side=tk.LEFT)

    # ---- 构建 ----
    def _build(self):
        self.row = 0
        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        self.body = body

    def _slider(self, label, key, lo, hi):
        row = ttk.Frame(self.body)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text=label, width=14).pack(side=tk.LEFT)
        val = float(self.prefs.get(key, 1.0))
        var = tk.DoubleVar(value=val)
        ttk.Scale(row, from_=lo, to=hi, variable=var, command=lambda v, k=key: None).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(row, text=f"{val:.1f}", width=4).pack(side=tk.LEFT)
        setattr(self, f"_{key}_var", var)

    def _buildKeys(self):
        ttk.Separator(self.body).pack(fill=tk.X, pady=8)
        ttk.Label(self.body, text="按键绑定（浏览模式 WASD/QE）：").pack(anchor=tk.W)
        keys = self.prefs.get("keys") or {}
        self._keyVars = {}
        grid = ttk.Frame(self.body)
        grid.pack(fill=tk.X, pady=4)
        for i, (action, label) in enumerate(MOVE_ACTIONS):
            f = ttk.Frame(grid)
            f.grid(row=i // 3, column=i % 3, padx=6, pady=4, sticky=tk.W)
            ttk.Label(f, text=label).pack(side=tk.LEFT)
            var = tk.StringVar(value=str(keys.get(action, "")))
            ttk.Entry(f, textvariable=var, width=4).pack(side=tk.LEFT, padx=4)
            self._keyVars[action] = var

    def _apply(self):
        self.prefs["orbitSpeed"] = self._orbitSpeed_var.get()
        self.prefs["panSensitivity"] = self._panSensitivity_var.get()
        self.prefs["moveSpeed"] = self._moveSpeed_var.get()
        self.prefs.setdefault("keys", {})
        for action, var in self._keyVars.items():
            k = var.get().strip().lower()
            if len(k) == 1:          # 只接受单个字符的按键，其他忽略（保留默认）
                self.prefs["keys"][action] = k
        self.onApply(self.prefs)
        self.destroy()