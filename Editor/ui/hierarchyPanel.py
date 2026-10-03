# -*- coding: utf-8 -*-
"""层级面板：以父子树显示场景中的物体，点击选中，拖拽设置父子。

拖拽约定：按住左键拖动到目标物体上释放 → 源物体成为目标物体的子物体。
- 位移 < 5px 视为点击（仅选中）
- 不能拖到自身、自身子孙、或「场景」根节点（允许拖回根）
- 拖到根节点「场景」= 设为根物体
"""

import tkinter as tk
from tkinter import ttk


class HierarchyPanel(tk.Frame):
    """层级树（V4：父子递归 + 拖拽设父子）。"""

    def __init__(self, master, scene=None, onSelect=None, onStructure=None, **kw):
        super().__init__(master, **kw)
        self.scene = scene
        self.onSelect = onSelect
        self.onStructure = onStructure   # 结构变化回调（main 刷新其它面板/视图）
        self.selected = None

        header = ttk.Label(self, text="层级", padding=(6, 3))
        header.pack(fill=tk.X)
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._onSelect)
        self.tree.bind("<ButtonPress-1>", self._onPress)
        self.tree.bind("<ButtonRelease-1>", self._onRelease)
        self.tree.tag_configure("inactive", foreground="#888")
        self._idToObj = {}   # tree iid → 物体映射
        self._dragSource = None
        self._pressPos = None
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

    # ---- 拖拽设父子 ----
    def _onPress(self, event):
        self._pressPos = (event.x, event.y)
        item = self.tree.identify_row(event.y)
        self._dragSource = item if item else None

    def _onRelease(self, event):
        source = self._dragSource
        self._dragSource = None
        if source is None:
            return
        if self._pressPos and (abs(event.x - self._pressPos[0]) +
                               abs(event.y - self._pressPos[1])) < 5:
            return   # 视为点击
        src = self._idToObj.get(source)
        if src is None:
            return
        target = self.tree.identify_row(event.y)
        if target == source:
            return
        if target == "root":
            self.scene.setParent(src, None)   # 拖回场景 = 设为根
        else:
            dst = self._idToObj.get(target)
            if dst is None or dst is src:
                return
            # 不能把源设为源自身或源的后代
            cur = dst
            while cur is not None:
                if cur is src:
                    return
                cur = cur.parent
            self.scene.setParent(src, dst)
        self.refresh()
        if self.onStructure:
            self.onStructure()

    # ---- 选中 ----
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
