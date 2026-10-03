# -*- coding: utf-8 -*-
"""层级面板：显示场景中的物体树，点击选中。"""

import tkinter as tk
from tkinter import ttk


class HierarchyPanel(tk.Frame):
    """层级树（V2 骨架：平面列表，V3 启用父子层级）。"""

    def __init__(self, master, scene=None, onSelect=None, **kw):
        super().__init__(master, **kw)
        self.scene = scene
        self.onSelect = onSelect
        self.selected = None

        header = ttk.Label(self, text="层级", padding=(6, 3))
        header.pack(fill=tk.X)
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._onSelect)
        self._idToObj = {}   # tree iid → 物体映射
        self.refresh()

    def refresh(self):
        """重建树（根节点「场景」+ 物体列表）。"""
        self.tree.delete(*self.tree.get_children())
        self._idToObj.clear()
        if self.scene is None:
            return
        root = self.tree.insert("", tk.END, text="场景", iid="root", open=True)
        for obj in self.scene.objects:
            oid = f"obj{id(obj)}"
            self._idToObj[oid] = obj
            tag = "" if obj.active else "inactive"
            self.tree.insert(root, tk.END, text=obj.name, iid=oid, open=True)
            self.tree.item(oid, tags=(tag,))
            self.tree.tag_configure("inactive", foreground="#888")

    def _onSelect(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        obj = self._idToObj.get(sel[0])
        self.selected = obj
        if self.onSelect:
            self.onSelect(obj)