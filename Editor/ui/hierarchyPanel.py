# -*- coding: utf-8 -*-
"""层级面板：以父子树显示场景中的物体，点击选中。

递归插入子物体；失活物体灰色显示（沿用旧版约定）。
已选中时跳过 selection_set，防止 TreeviewSelect 虚拟事件风暴（09-13 教训）。
"""

import tkinter as tk
from tkinter import ttk


class HierarchyPanel(tk.Frame):
    """层级树（V3：父子递归，根物体在「场景」节点下）。"""

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
        self.tree.tag_configure("inactive", foreground="#888")
        self._idToObj = {}   # tree iid → 物体映射
        self.refresh()

    def refresh(self):
        """重建树：根节点「场景」+ 根物体递归插入子物体。"""
        self.tree.delete(*self.tree.get_children())
        self._idToObj.clear()
        if self.scene is None:
            return
        root = self.tree.insert("", tk.END, text="场景", iid="root", open=True)
        for obj in self.scene.rootObjects():
            self._insertObject(root, obj)

    def _insertObject(self, parentIid, obj):
        """递归插入一个物体及其子树。"""
        oid = f"obj{id(obj)}"
        self._idToObj[oid] = obj
        tag = "" if obj.active else "inactive"
        self.tree.insert(parentIid, tk.END, text=obj.name, iid=oid, open=True,
                         tags=(tag,))
        for child in obj.children:
            self._insertObject(oid, child)

    def _onSelect(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        obj = self._idToObj.get(sel[0])
        self.selected = obj
        if self.onSelect:
            self.onSelect(obj)

    def selectObject(self, obj):
        """外部（如视口拾取）设置选中，联动高亮层级项。
        已选中则跳过 selection_set（防止再次触发 TreeviewSelect 事件风暴）。"""
        for oid, o in self._idToObj.items():
            if o is obj:
                cur = self.tree.selection()
                if len(cur) == 1 and self._idToObj.get(cur[0]) is obj:
                    return
                self.tree.selection_set(oid)
                return
