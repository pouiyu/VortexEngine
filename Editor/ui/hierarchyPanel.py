# -*- coding: utf-8 -*-
"""层级面板：以父子树显示场景中的物体，点击选中，拖拽设置父子。

拖拽约定：按住左键拖动到目标物体上释放 → 源物体成为目标物体的子物体。
- 位移 < 5px 视为点击（仅选中）
- 不能拖到自身、自身子孙、或「场景」根节点（允许拖回根）
- 拖到根节点「场景」= 设为根物体

选中：单击单选；按住 Ctrl/Shift 点击多选（Treeview extended 模式）。
Ctrl+C / Ctrl+V：复制选中物体（含整棵子树）→ 粘贴为新物体（多选一起复制）。
Ctrl+X / Ctrl+V：剪切选中物体 = 移动（粘贴到当前选中物体下，无选中则设根）。
"""

import tkinter as tk
from tkinter import ttk

from ..core.scene import Camera, Light, MeshRenderer, Transform


def cloneComponent(comp):
    """深拷贝一个组件（各组件类型字段独立复制）。"""
    if isinstance(comp, Transform):
        return Transform(position=comp.position.copy(),
                         rotation=comp.rotation.copy(),
                         scale=comp.scale.copy())
    if isinstance(comp, MeshRenderer):
        return MeshRenderer(mesh=comp.mesh, material=comp.material)
    if isinstance(comp, Light):
        return Light(lightType=comp.lightType,
                     color=list(comp.color), intensity=comp.intensity)
    if isinstance(comp, Camera):
        return Camera(fov=comp.fov, near=comp.near, far=comp.far)
    return None


def cloneObjectTree(obj, parent=None):
    """深拷贝物体及其整棵子树（新 uuid，保持内部父子结构）。

    GameObject 构造已带默认 Transform：直接覆盖其数值，其余组件逐个复制。"""
    from ..core.scene import GameObject
    newObj = GameObject(name=obj.name, active=obj.active)
    for comp in obj.components:
        if isinstance(comp, Transform):
            newObj.components[0].position = comp.position.copy()
            newObj.components[0].rotation = comp.rotation.copy()
            newObj.components[0].scale = comp.scale.copy()
            continue
        clone = cloneComponent(comp)
        if clone is not None:
            newObj.addComponent(clone)
    if parent is not None:
        parent.children.append(newObj)
        newObj.parent = parent
    for child in obj.children:
        cloneObjectTree(child, newObj)
    return newObj


class HierarchyPanel(tk.Frame):
    """层级树（V4：父子递归 + 拖拽设父子 + 复制粘贴）。"""

    def __init__(self, master, scene=None, onSelect=None, onStructure=None, **kw):
        super().__init__(master, **kw)
        self.scene = scene
        self.onSelect = onSelect
        self.onStructure = onStructure   # 结构变化回调（main 刷新其它面板/视图）
        self.selected = None
        self._clipboard = None           # Ctrl+C/X 剪切源（物体列表）
        self._cutMode = False            # True=剪切（粘贴=移动）

        header = ttk.Label(self, text="层级", padding=(6, 3))
        header.pack(fill=tk.X)
        self.tree = ttk.Treeview(self, show="tree", selectmode="extended")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._onSelect)
        self.tree.bind("<ButtonPress-1>", self._onPress)
        self.tree.bind("<ButtonRelease-1>", self._onRelease)
        self.tree.bind("<Control-c>", self._onCopy)
        self.tree.bind("<Control-v>", self._onPaste)
        self.tree.bind("<Control-x>", self._onCut)
        self.tree.tag_configure("inactive", foreground="#888")
        self._idToObj = {}   # tree iid → 物体映射
        self._dragSource = None
        self._pressPos = None
        self.refresh()

    # ---- 选中辅助 ----
    def _selectedObjects(self):
        """当前 Treeview 选中项对应的物体列表（保持 iid 顺序）。"""
        return [self._idToObj[i] for i in self.tree.selection() if i in self._idToObj]

    def _selectObjects(self, objs):
        """选中指定物体集合（无事件回调，只设高亮）。"""
        ids = [oid for oid, o in self._idToObj.items() if o in objs]
        if ids:
            self.tree.selection_set(ids)

    # ---- 复制 / 剪切 / 粘贴 ----
    def _onCopy(self, _event):
        objs = self._selectedObjects()
        if objs:
            self._clipboard = objs
            self._cutMode = False
        return "break"

    def _onCut(self, _event):
        """Ctrl+X：剪切选中物体（粘贴=移动到目标物体下/根）。"""
        objs = self._selectedObjects()
        if objs:
            self._clipboard = objs
            self._cutMode = True
        return "break"

    def _onPaste(self, _event):
        if not self._clipboard or self.scene is None:
            return "break"
        if self._cutMode:
            # 剪切粘贴 = 移动：粘贴到当前选中物体下（无选中 → 设根）
            targets = self._selectedObjects()
            dst = targets[-1] if targets else None
            for src in self._clipboard:
                if src not in self.scene.objects:
                    continue
                if dst is None:
                    self.scene.setParent(src, None)
                elif dst is not src and not src.isDescendantOf(dst):
                    self.scene.setParent(src, dst)
            self._cutMode = False
            self._clipboard = None
        else:
            clones = []
            for src in self._clipboard:
                clone = cloneObjectTree(src)
                self.scene.addObject(clone)
                # 粘贴到原物体父级下（根物体则放场景根），位置保持原位
                if src.parent is not None:
                    self.scene.setParent(clone, src.parent)
                clones.append(clone)
            self._selectObjects(clones)
        self.refresh()
        if self.onSelect:
            self.onSelect(self._selectedObjects())
        if self.onStructure:
            self.onStructure()
        return "break"

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
        objs = self._selectedObjects()
        if not objs:
            return
        self.selected = objs[-1]   # 树序最后一项作为主选中（Gizmo/检查器作用对象）
        if self.onSelect:
            self.onSelect(objs)

    def selectObjects(self, objs):
        """外部（视口拾取 / 结构刷新）设置选中集合，联动高亮层级项。
        与当前一致则跳过（防止再次触发 TreeviewSelect 事件风暴）。"""
        objs = list(objs)
        cur = self._selectedObjects()
        if len(cur) == len(objs) and all(a is b for a, b in zip(cur, objs)):
            return
        self._selectObjects(objs)

    def selectObject(self, obj):
        """外部（如视口拾取）设置单选选中（保持旧接口语义）。"""
        self.selectObjects([obj] if obj is not None else [])
