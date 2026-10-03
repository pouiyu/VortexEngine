# -*- coding: utf-8 -*-
"""检查器面板：编辑选中物体的名称 / 激活 / 变换 / 组件（V3）。

- 名称 / 激活 / 组件增删：结构变化 → 刷新层级与视口（onStructure）
- 变换三组数值框：KeyRelease 实时提交（onValue 仅重绘，不重建控件）
- 滚轮增减数值：步长 1，Ctrl=0.1，Shift=10（09-13 已确认的交互）
- 组件区：网格渲染器（网格下拉 + RGB 颜色 + 预览色块）；Transform 为默认组件不可删
"""

import tkinter as tk
from tkinter import ttk

from ..core.meshCache import listProjectMeshes
from ..core.scene import Light, MeshRenderer, Transform


class InspectorPanel(ttk.Frame):
    """显示并编辑选中物体的属性。"""

    def __init__(self, master, scene=None, onValue=None, onStructure=None,
                 projectRoot=None, **kw):
        super().__init__(master, **kw)
        self.scene = scene
        self.onValue = onValue          # 数值变化：仅重绘视口
        self.onStructure = onStructure  # 结构变化：刷新层级 + 重绘视口
        self.projectRoot = projectRoot  # 项目根（网格下拉列出 Resources 下 .obj）
        self.selected = None

        ttk.Label(self, text="检查器", padding=(6, 3)).pack(fill=tk.X)
        self.proxy = ttk.Frame(self)
        self.proxy.pack(fill=tk.BOTH, expand=True)
        self._tfEntries = {}          # ("position"|"rotation"|"scale", i) → Entry（Gizmo 实时刷新用）
        self._buildEmpty()

    # ---- 显示 ----
    def showObject(self, obj):
        """显示物体的可编辑属性；obj 为 None 时显示空提示。"""
        self.selected = obj
        for child in self.proxy.winfo_children():
            child.destroy()
        if obj is None:
            self._buildMessage("请选择物体")
            return
        self._buildHeader(obj)
        self._buildComponents(obj)

    def _buildHeader(self, obj):
        """名称（可编辑）+ 激活（复选框）+ 父级（下拉可选，禁止选自己/子孙）。"""
        row = ttk.Frame(self.proxy)
        row.pack(fill=tk.X, padx=8, pady=(8, 2))
        nameVar = tk.StringVar(value=obj.name)
        nameEntry = ttk.Entry(row, textvariable=nameVar)
        nameEntry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _commitName(_e=None):
            text = nameVar.get().strip()
            if text:
                obj.name = text
                if self.onStructure:
                    self.onStructure()

        nameEntry.bind("<KeyRelease>", _commitName)
        actVar = tk.BooleanVar(value=obj.active)
        ttk.Checkbutton(row, text="激活", variable=actVar,
                        command=lambda: self._commitActive(obj, actVar)).pack(side=tk.LEFT, padx=6)
        self._buildParentRow(obj)

    def _buildParentRow(self, obj):
        """父级下拉：在场景其它物体中选择（空 = 根物体）。"""
        parentRow = ttk.Frame(self.proxy)
        parentRow.pack(fill=tk.X, padx=8, pady=(2, 0))
        ttk.Label(parentRow, text="父级").pack(side=tk.LEFT)
        mapping = {}   # 显示文本 → 物体
        values = ["（无）"]
        for o in (self.scene.objects if self.scene else []):
            if o is obj or o.isDescendantOf(obj):
                continue
            label = f"{o.name} ({o.uuid[:4]})"
            mapping[label] = o
            values.append(label)
        combo = ttk.Combobox(parentRow, values=values, width=16, state="readonly")
        cur = obj.parent
        combo.set("（无）" if cur is None else f"{cur.name} ({cur.uuid[:4]})")
        combo.pack(side=tk.LEFT, padx=(4, 0))

        def _setParent(_e=None):
            label = combo.get()
            newParent = mapping.get(label)
            if self.scene is not None and newParent is not obj:
                self.scene.setParent(obj, newParent)
                self.showObject(obj)
                if self.onStructure:
                    self.onStructure()

        combo.bind("<<ComboboxSelected>>", _setParent)

    def _commitActive(self, obj, actVar):
        obj.active = bool(actVar.get())
        if self.onStructure:
            self.onStructure()

    # ---- 组件区：一个组件一个框 ----
    def _buildComponents(self, obj):
        """按组件逐个画独立 LabelFrame 框（Transform / 网格渲染器 / 光照），底部是添加按钮。"""
        for comp in obj.components:
            if isinstance(comp, Transform):
                self._buildTransformBox(obj)
            elif isinstance(comp, MeshRenderer):
                self._buildMeshBox(obj, comp)
            elif isinstance(comp, Light):
                self._buildLightBox(obj, comp)
        addRow = ttk.Frame(self.proxy)
        addRow.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(addRow, text="+ 添加组件",
                   command=lambda: self._menuAddComponent(addRow, obj)).pack(side=tk.LEFT)

    def _buildTransformBox(self, obj):
        """Transform 组件框：位置 / 旋转 / 缩放三组数值框（实时提交 + 滚轮步进）。"""
        t = obj.transform
        sec = ttk.LabelFrame(self.proxy, text="Transform", padding=6)
        sec.pack(fill=tk.X, padx=6, pady=4)
        self._tfEntries = {}
        for label, attr in (("位置", "position"), ("旋转", "rotation"), ("缩放", "scale")):
            row = ttk.Frame(sec)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=label, width=4).pack(side=tk.LEFT)
            vec = getattr(t, attr)
            for i in range(3):
                e = ttk.Entry(row, width=7)
                e.insert(0, f"{vec[i]:g}")
                e.pack(side=tk.LEFT, padx=2)
                e.bind("<KeyRelease>",
                       lambda _ev, ee=e, tr=t, a=attr, idx=i: self._commitVec(ee, tr, a, idx))
                e.bind("<MouseWheel>",
                       lambda ev, ee=e, tr=t, a=attr, idx=i: self._onWheel(ev, ee, tr, a, idx))
                self._tfEntries[(attr, i)] = e

    def refreshTransformValues(self, obj):
        """Gizmo 拖动中轻量刷新：只更新 Transform 数值框文本，不重建控件。"""
        t = obj.transform if obj is not None else None
        if t is None or not self._tfEntries:
            return
        for (attr, i), e in self._tfEntries.items():
            try:
                val = getattr(t, attr)[i]
            except Exception:
                continue
            if e.get() != f"{val:g}":
                e.delete(0, tk.END)
                e.insert(0, f"{val:g}")

    def _commitVec(self, entry, tr, attr, idx):
        """把数值框内容写回变换向量（实时提交，仅重绘不重建控件）。"""
        try:
            val = float(entry.get())
        except ValueError:
            return
        vec = getattr(tr, attr).copy()
        vec[idx] = val
        setattr(tr, attr, vec)
        if self.onValue:
            self.onValue()

    def _onWheel(self, event, entry, tr, attr, idx):
        """滚轮增减数值：步长 1，Ctrl=0.1，Shift=10。"""
        step = 0.1 if (event.state & 0x0004) else (10.0 if (event.state & 0x0001) else 1.0)
        try:
            cur = float(entry.get())
        except ValueError:
            return "break"
        cur += step if event.delta > 0 else -step
        entry.delete(0, tk.END)
        entry.insert(0, f"{cur:g}")
        self._commitVec(entry, tr, attr, idx)
        return "break"

    def _buildMeshBox(self, obj, mr):
        """网格渲染器组件框：右上角「移除」+ 网格下拉 + RGB 颜色（0~255，实时预览）。"""
        sec = ttk.LabelFrame(self.proxy, text="网格渲染器", padding=6)
        sec.pack(fill=tk.X, padx=6, pady=4)
        head = ttk.Frame(sec)
        head.pack(fill=tk.X)
        ttk.Button(head, text="移除", width=4,
                   command=lambda: self._removeComponent(obj, mr)).pack(side=tk.RIGHT)

        meshRow = ttk.Frame(sec)
        meshRow.pack(fill=tk.X, padx=(12, 0), pady=1)
        ttk.Label(meshRow, text="网格").pack(side=tk.LEFT)
        combo = ttk.Combobox(meshRow, values=self._meshOptions(), width=16, state="readonly")
        combo.set(mr.mesh or "")
        combo.pack(side=tk.LEFT, padx=(4, 0))

        def _setMesh(_e=None):
            mr.mesh = combo.get() or None
            if self.onValue:
                self.onValue()

        combo.bind("<<ComboboxSelected>>", _setMesh)

        colorRow = ttk.Frame(sec)
        colorRow.pack(fill=tk.X, padx=(12, 0), pady=1)
        ttk.Label(colorRow, text="颜色").pack(side=tk.LEFT)
        swatch = tk.Label(colorRow, width=3, relief=tk.SUNKEN, bg=self._hex(mr.color))
        swatch.pack(side=tk.LEFT, padx=(4, 2))
        for i, label in enumerate(("R", "G", "B")):
            e = ttk.Entry(colorRow, width=4)
            e.insert(0, str(int(round(mr.color[i] * 255))))
            e.pack(side=tk.LEFT, padx=1)
            e.bind("<KeyRelease>",
                   lambda _ev, ee=e, idx=i: self._commitColor(mr, ee, swatch, idx))
            e.bind("<MouseWheel>",
                   lambda ev, ee=e, idx=i: self._onColorWheel(ev, ee, mr, swatch, idx))

    def _meshOptions(self):
        """网格下拉候选：内置 cube/sphere + 项目 Resources 下所有 .obj。"""
        options = ["cube", "sphere"]
        if self.projectRoot:
            options += listProjectMeshes(self.projectRoot)
        return options

    def refreshMeshOptions(self):
        """外部（导入模型后）刷新网格下拉候选。"""
        if self.selected is not None:
            self.showObject(self.selected)

    def _buildLightBox(self, obj, lt):
        """光照组件框：类型下拉 + 颜色 RGB + 强度。"""
        sec = ttk.LabelFrame(self.proxy, text="光照", padding=6)
        sec.pack(fill=tk.X, padx=6, pady=4)
        head = ttk.Frame(sec)
        head.pack(fill=tk.X)
        ttk.Button(head, text="移除", width=4,
                   command=lambda: self._removeComponent(obj, lt)).pack(side=tk.RIGHT)

        typeRow = ttk.Frame(sec)
        typeRow.pack(fill=tk.X, padx=(12, 0), pady=1)
        ttk.Label(typeRow, text="类型").pack(side=tk.LEFT)
        combo = ttk.Combobox(typeRow, values=["directional", "point"], width=12,
                             state="readonly")
        combo.set(lt.lightType)
        combo.pack(side=tk.LEFT, padx=(4, 0))

        def _setType(_e=None):
            lt.lightType = combo.get() or "directional"
            if self.onValue:
                self.onValue()

        combo.bind("<<ComboboxSelected>>", _setType)

        colorRow = ttk.Frame(sec)
        colorRow.pack(fill=tk.X, padx=(12, 0), pady=1)
        ttk.Label(colorRow, text="颜色").pack(side=tk.LEFT)
        swatch = tk.Label(colorRow, width=3, relief=tk.SUNKEN, bg=self._hex(lt.color))
        swatch.pack(side=tk.LEFT, padx=(4, 2))
        for i, label in enumerate(("R", "G", "B")):
            e = ttk.Entry(colorRow, width=4)
            e.insert(0, str(int(round(lt.color[i] * 255))))
            e.pack(side=tk.LEFT, padx=1)
            e.bind("<KeyRelease>",
                   lambda _ev, ee=e, idx=i: self._commitColor(lt, ee, swatch, idx))
            e.bind("<MouseWheel>",
                   lambda ev, ee=e, idx=i: self._onColorWheel(ev, ee, lt, swatch, idx))

        intenRow = ttk.Frame(sec)
        intenRow.pack(fill=tk.X, padx=(12, 0), pady=1)
        ttk.Label(intenRow, text="强度").pack(side=tk.LEFT)
        eInt = ttk.Entry(intenRow, width=6)
        eInt.insert(0, f"{lt.intensity:g}")
        eInt.pack(side=tk.LEFT, padx=(4, 0))

        def _commitIntensity(_ev=None):
            try:
                lt.intensity = max(0.0, float(eInt.get()))
            except ValueError:
                return
            if self.onValue:
                self.onValue()

        eInt.bind("<KeyRelease>", _commitIntensity)

    @staticmethod
    def _hex(color):
        r = [max(0, min(255, int(round(c * 255)))) for c in color]
        return f"#{r[0]:02x}{r[1]:02x}{r[2]:02x}"

    def _commitColor(self, mr, entry, swatch, idx):
        """写回颜色分量并刷新预览（仅重绘）。"""
        try:
            v = max(0, min(255, int(float(entry.get()))))
        except ValueError:
            return
        mr.color[idx] = v / 255.0
        swatch.config(bg=self._hex(mr.color))
        if self.onValue:
            self.onValue()

    def _onColorWheel(self, event, entry, mr, swatch, idx):
        step = 10 if (event.state & 0x0001) else 1
        try:
            cur = int(float(entry.get()))
        except ValueError:
            return "break"
        cur += step if event.delta > 0 else -step
        entry.delete(0, tk.END)
        entry.insert(0, str(max(0, min(255, cur))))
        self._commitColor(mr, entry, swatch, idx)
        return "break"

    def _menuAddComponent(self, anchor, obj):
        """「+ 添加组件」下拉：网格渲染器 / 光照（已有则禁用）。"""
        menu = tk.Menu(self, tearoff=0)
        if obj.getComponent(MeshRenderer) is None:
            menu.add_command(
                label="网格渲染器",
                command=lambda: self._addComponent(
                    obj, MeshRenderer(mesh="cube", color=[0.30, 0.55, 0.85])))
        else:
            menu.add_command(label="网格渲染器（已有）", state=tk.DISABLED)
        if obj.getComponent(Light) is None:
            menu.add_command(
                label="光照（方向光）",
                command=lambda: self._addComponent(
                    obj, Light(lightType="directional", color=[1.0, 1.0, 0.95], intensity=1.0)))
            menu.add_command(
                label="光照（点光源）",
                command=lambda: self._addComponent(
                    obj, Light(lightType="point", color=[1.0, 0.9, 0.7], intensity=1.2)))
        else:
            menu.add_command(label="光照（已有）", state=tk.DISABLED)
        menu.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())

    def _addComponent(self, obj, comp):
        """挂载组件后重建检查器 + 通知结构变化。"""
        obj.addComponent(comp)
        self.showObject(obj)
        if self.onStructure:
            self.onStructure()

    def _removeComponent(self, obj, comp):
        """卸载组件（Transform 不可卸）后重建检查器 + 通知结构变化。"""
        if obj.removeComponent(comp):
            self.showObject(obj)
            if self.onStructure:
                self.onStructure()

    # ---- 空态 ----
    def _buildEmpty(self):
        self._buildMessage("请选择物体")

    def _buildMessage(self, text):
        ttk.Label(self.proxy, text=text, foreground="#666").pack(padx=8, pady=12, anchor=tk.NW)
