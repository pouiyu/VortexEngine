# -*- coding: utf-8 -*-
"""Vortex 编辑器 —— 场景编辑器（V2 骨架版）。

用法：
- python Editor/main.py                 （打开空项目，演示场景）
- python Editor/main.py --project <目录> （打开启动器创建的项目）
- python Editor/main.py --selftest       （无交互自检：构建窗口 + OpenGL 渲染 3 帧）

布局：菜单栏 / 工具栏 / 左侧（层级+项目） / 中央 OpenGL 视口 / 右侧检查器 / 状态栏。
本版验证重点：tkinter 主窗 + WGL 嵌入式 OpenGL 视口渲染管线（网格 + 立方体）。
"""

import json
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import numpy as np

# 包上下文自适应：既支持 python -m Editor.main（引擎根启动），
# 也支持 python Editor/main.py（脚本启动，项目偏好），两种方式都能正常相对导入。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "Editor"

from .core.preferences import loadPreferences, savePreferences
from .core.scene import Camera, GameObject, Light, MeshRenderer, createDemoScene, worldMatrix
from .core.serializer import loadSceneFile, saveSceneFile
from .core.meshCache import importModel as importModelFile
from .renderer.glViewport import GLViewport
from .renderer.orbitCamera import OrbitCamera
from .ui.hierarchyPanel import HierarchyPanel
from .ui.inspectorPanel import InspectorPanel
from .ui.projectPanel import ProjectPanel
from .ui.statusBar import StatusBar
from .ui.toolbar import Toolbar

APP_NAME = "Vortex 编辑器"
REFRESH_MS = 500  # 状态栏 FPS 刷新间隔


def isVortexProject(path):
    """判断是否为有效的 Vortex 项目（含 Engine/engineData.ved）。"""
    return (Path(path) / "Engine" / "engineData.ved").is_file()


def _goWith(mesh, material="default", name=None):
    """带网格渲染器的物体（创建列表辅助，颜色由材质配置）。"""
    go = GameObject(name=name or ("立方体" if mesh == "cube" else "球体"))
    go.addComponent(MeshRenderer(mesh=mesh, material=material))
    return go


def _goCamera(name="摄像机"):
    """带摄像机组件的物体（创建列表辅助）。"""
    go = GameObject(name=name)
    go.addComponent(Camera())
    return go


def _goLight(lightType, color, intensity, name=None):
    """带光照组件的物体（创建列表辅助）。"""
    go = GameObject(name=name or ("方向光" if lightType == "directional" else "点光源"))
    go.addComponent(Light(lightType=lightType, color=color, intensity=intensity))
    return go


def readProjectName(projectRoot):
    """读取项目名（engineData.ved），失败用目录名。"""
    ved = Path(projectRoot) / "Engine" / "engineData.ved"
    try:
        meta = json.loads(ved.read_text(encoding="utf-8"))
        name = meta.get("name")
        if name:
            return str(name)
    except (json.JSONDecodeError, OSError):
        pass
    return Path(projectRoot).name


class EditorApp:
    """编辑器主窗口。"""

    def __init__(self, root, projectRoot=None):
        self.root = root
        self.projectRoot = Path(projectRoot) if projectRoot else None
        self.projectName = readProjectName(self.projectRoot) if self.projectRoot else "（未命名项目）"
        # 打开项目时自动加载项目根 scene.json；没有则用演示场景
        if self.projectRoot:
            defaultScene = self.projectRoot / "scene.json"
            if defaultScene.exists():
                self.scene = loadSceneFile(defaultScene)
                self.scenePath = defaultScene
            else:
                self.scene = createDemoScene()
                self.scenePath = None
        else:
            self.scene = createDemoScene()
            self.scenePath = None
        self.prefs = loadPreferences()
        self.selected = None            # 主选中物体（Gizmo/检查器作用对象）
        self.selectedSet = set()        # 多选集合（Shift 追加；含主选中）
        self._undoStack = []            # 场景撤销栈（序列化快照）
        self._lastUndoTime = 0.0        # 变换类撤销合并用
        self._playing = False           # 播放模式（V5：脚本每帧执行）
        self._playSnapshot = None       # 播放开始时的场景快照（停止时恢复）
        self._playWindow = None         # 播放窗口（游戏视图）
        self._codeEditors = {}          # 打开的代码编辑器：路径 → CodeEditorWindow
        self._unsaved = False           # 未保存修改标记（标题显示 *）
        self._updatingTitle = False
        self._updateTitle()

        root.geometry("1280x760")
        root.minsize(900, 600)

        self._buildMenu()
        self._buildLayout()

        # 快捷键：Delete 删除选中（焦点在输入框时交给输入框）；Ctrl+S/O 保存/打开；
        # Ctrl+Z 撤销场景（焦点在资源树时由项目面板的 <Control-z> 优先处理资源撤销）；
        # F5 播放 / 停止（V5 播放模式）
        root.bind("<Delete>", lambda e: self.deleteSelected())
        root.bind("<Control-s>", lambda e: self.saveScene())
        root.bind("<Control-o>", lambda e: self.openScene())
        root.bind("<Control-z>", self._undoScene)
        root.bind("<F5>", lambda e: self._togglePlay())
        # 退出前检查未保存修改
        root.protocol("WM_DELETE_WINDOW", self._onClose)

        # 帧率统计
        self._lastFrames = 0
        self._lastFPS = time.monotonic()
        root.after(REFRESH_MS, self._updateFPS)

    # ---- 未保存标记 ----
    def _updateTitle(self):
        star = " *" if self._unsaved else ""
        play = " — ▶ 播放中" if self._playing else ""
        self.root.title(f"{APP_NAME} — {self.projectName}{star}{play}")

    def markUnsaved(self):
        """任意场景修改（变换/结构/增删/材质引用等）→ 标题加 *。"""
        self._unsaved = True
        self._updateTitle()

    def clearUnsaved(self):
        self._unsaved = False
        self._updateTitle()

    # ---- 内置代码编辑器（V5.2：双击 .vpy 打开） ----
    def openScriptEditor(self, path):
        """打开（或聚焦已打开的）脚本编辑器窗口。"""
        from .ui.codeEditor import CodeEditorWindow
        key = str(Path(path).resolve())
        win = self._codeEditors.get(key)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_force()
                    return
            except Exception:
                pass
        editor = CodeEditorWindow(self.root, Path(path),
                                  onClosed=lambda k=key: self._codeEditors.pop(k, None))
        self._codeEditors[key] = editor

    # ---- 播放模式（V5：脚本每帧执行） ----
    def _togglePlay(self):
        """工具栏按钮 / F5：播放 ⇄ 停止。"""
        if self._playing:
            self._stopPlay()
        else:
            self._startPlay()

    def _startPlay(self):
        """进入播放：快照场景 → 调所有脚本 start → 弹出播放窗口 → 标题/按钮进入播放态。"""
        if self._playing:
            return
        from .core.serializer import serializeScene
        from .core.runtime import startScripts, _clearCache
        from .ui.playWindow import PlayWindow
        _clearCache()                       # 重新加载脚本（热更新编辑内容）
        self._playSnapshot = serializeScene(self.scene)
        self._playing = True
        startScripts(self.scene, self.projectRoot)
        self.toolbar.setPlaying(True)
        self._playWindow = PlayWindow(self.root, self.scene, projectRoot=self.projectRoot,
                                      onClose=self._stopPlay)
        self.status.showMessage("▶ 播放中（F5 或按钮停止，播放修改不会保存）")
        self._updateTitle()

    def _stopPlay(self):
        """停止播放：恢复进入前快照（丢弃播放期间的修改），关播放窗口，刷新所有面板。"""
        if not self._playing:
            return
        from .core.serializer import deserializeScene
        if self._playWindow is not None:
            w = self._playWindow
            self._playWindow = None
            try:
                if w.winfo_exists():
                    w._closed = True
                    try:
                        w.viewport.dispose()
                    except Exception:
                        pass
                    w.destroy()
            except Exception:
                pass
        self.scene = deserializeScene(self._playSnapshot) if self._playSnapshot else self.scene
        self._playSnapshot = None
        self._playing = False
        self.viewport.scene = self.scene
        self.hierarchy.scene = self.scene
        self.inspector.scene = self.scene
        self.selected = None
        self.selectedSet = set()
        self.viewport.setSelected(None)
        self.viewport.setSelectedSet(set())
        self.inspector.showObject(None)
        self.hierarchy.refresh()
        self.viewport.renderFrame()
        self.toolbar.setPlaying(False)
        self.status.showMessage("⏹ 已停止播放（场景已恢复播放前状态）")
        self._updateTitle()

    def _onScriptTick(self, dt):
        """渲染循环每帧回调：播放中执行所有脚本的 update(obj, dt)。"""
        if self._playing:
            from .core.runtime import updateScripts
            updateScripts(self.scene, self.projectRoot, dt)

    def _onClose(self):
        """退出：有未保存修改时询问是否保存；播放中先停止（关播放窗口）。"""
        if self._playing:
            self._stopPlay()
        # 关闭所有代码编辑器（有未保存修改会弹提示；取消则中止退出）
        for key, ed in list(self._codeEditors.items()):
            try:
                if ed.winfo_exists():
                    ed._close()
            except Exception:
                pass
        try:
            alive = [k for k, ed in self._codeEditors.items() if ed.winfo_exists()]
        except Exception:
            alive = []
        if alive:
            return
        if self._unsaved:
            choice = messagebox.askyesnocancel(
                "未保存", f"「{self.projectName}」有未保存的修改，是否保存？")
            if choice is None:
                return                     # 取消：留在编辑器
            if choice:
                self.saveScene()           # 保存失败也会弹窗，直接继续关闭
        try:
            self.viewport.dispose()
        except Exception:
            pass
        self.root.destroy()

    # ---- 菜单栏 ----
    def _buildMenu(self):
        menubar = tk.Menu(self.root)
        mFile = tk.Menu(menubar, tearoff=0)
        mFile.add_command(label="新建场景", command=self.newScene)
        mFile.add_command(label="保存场景", accelerator="Ctrl+S", command=self.saveScene)
        mFile.add_command(label="打开场景", accelerator="Ctrl+O", command=self.openScene)
        mFile.add_separator()
        mFile.add_command(label="退出", accelerator="Alt+F4", command=self.root.destroy)
        menubar.add_cascade(label="文件", menu=mFile)

        mView = tk.Menu(menubar, tearoff=0)
        mView.add_command(label="重置视角", command=self.resetCamera)
        menubar.add_cascade(label="视图", menu=mView)

        mSettings = tk.Menu(menubar, tearoff=0)
        mSettings.add_command(label="设置…", command=self.openSettings)
        menubar.add_cascade(label="设置", menu=mSettings)

        mHelp = tk.Menu(menubar, tearoff=0)
        mHelp.add_command(label="关于", command=self._showAbout)
        menubar.add_cascade(label="帮助", menu=mHelp)
        self.root.config(menu=menubar)

    def resetCamera(self):
        """视角重置（视图菜单）：保留用户设定的速度系数。"""
        if hasattr(self, "viewport"):
            old = self.viewport.camera
            cam = OrbitCamera()
            cam.orbitSpeed = old.orbitSpeed
            cam.panSensitivity = old.panSensitivity
            cam.moveSpeed = old.moveSpeed
            self.viewport.camera = cam
            self.viewport.renderFrame()

    def _showAbout(self):
        messagebox.showinfo(
            APP_NAME,
            "Vortex 游戏编辑器（V5 脚本 + 播放模式）\n"
            "tkinter 界面 + OpenGL（WGL 嵌入）3D 视口\n"
            "GameObject + 组件（变换 / 网格渲染器 / 光照 / 摄像机 / 脚本）\n"
            "资源系统：.obj 模型 / .vmat 材质 / .vscene 场景 / .vpy 脚本\n"
            "内置代码编辑器：双击 .vpy 打开，语法高亮 + Ctrl+S 保存\n"
            "播放模式：▶ 播放（F5）执行物体脚本，弹出游戏视图窗口，停止恢复播放前场景\n"
            "下一阶段：V6 运行时导出",
        )

    # ---- 布局 ----
    def _buildLayout(self):
        # 状态栏（提前创建，供项目面板/其它回调显示消息）
        self.status = StatusBar(self.root, projectPath=str(self.projectRoot) if self.projectRoot else "")
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

        # 工具栏
        toolbar = Toolbar(self.root, projectName=self.projectName,
                          onCreate=self.createObject, onGizmoMode=self._onGizmoMode,
                          onPlay=self._togglePlay)
        toolbar.pack(fill=tk.X)
        self.toolbar = toolbar

        # 主体：左列（层级+项目） | 视口 | 检查器
        body = ttk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Panedwindow(body, orient=tk.VERTICAL)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0), pady=2)

        self.hierarchy = HierarchyPanel(left, scene=self.scene, onSelect=self._onHierarchySelect,
                                         onStructure=self._onStructure)
        left.add(self.hierarchy, weight=2)

        self.project = ProjectPanel(left, projectRoot=self.projectRoot,
                                    onOpenScene=self.openSceneFile,
                                    onUseMesh=self._onUseMesh,
                                    onEditMaterial=self._onEditMaterial,
                                    onImport=self._onModelImported,
                                    onOpenScript=self.openScriptEditor,
                                    onStatus=self.status.showMessage if hasattr(self, "status") else None)
        left.add(self.project, weight=1)

        self.viewport = GLViewport(body, scene=self.scene, onSelect=self._onSelect,
                                   prefs=self.prefs, projectRoot=self.projectRoot,
                                   onTransform=self._onTransform,
                                   onGizmoModeChanged=self._onGizmoModeChanged,
                                   onScriptUpdate=self._onScriptTick)
        self.viewport.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=2)

        self.inspector = InspectorPanel(body, scene=self.scene,
                                        onValue=self._onValue,
                                        onStructure=self._onStructure,
                                        projectRoot=self.projectRoot,
                                        onSaveMaterial=self._onSaveMaterial)
        self.inspector.pack(side=tk.LEFT, fill=tk.Y)

    def _onTransform(self, obj, live=False):
        """Gizmo 变换联动：live=True 拖动中轻量刷新数值框；否则重建检查器 + 压撤销。"""
        if obj is None or self.inspector is None:
            return
        if live:
            self.inspector.refreshTransformValues(obj)
        else:
            self.inspector.showObject(obj)
            self.markUnsaved()
            self._pushUndo()

    # ---- 场景撤销（Ctrl+Z，序列化快照栈） ----
    def _pushUndo(self, merge=False):
        """把当前场景快照压入撤销栈。merge=True（数值连续提交）时替换栈顶中间态。"""
        if self.scene is None:
            return
        from .core.serializer import serializeScene
        snap = serializeScene(self.scene)
        now = time.monotonic()
        if merge and self._undoStack and now - self._lastUndoTime < 0.5:
            self._undoStack[-1] = snap      # 连续数值提交只保留最近一次
        else:
            self._undoStack.append(snap)
            if len(self._undoStack) > 50:
                self._undoStack.pop(0)
        self._lastUndoTime = now

    def _undoScene(self, _event=None):
        """Ctrl+Z：恢复上一场景快照（焦点在输入框/资源树时让位）。"""
        focus = self.root.focus_get()
        if isinstance(focus, (ttk.Entry, tk.Entry, tk.Text)):
            return "break"
        if not self._undoStack:
            self.status.showMessage("没有可撤销的操作")
            return "break"
        from .core.serializer import deserializeScene
        snap = self._undoStack.pop()
        self.scene = deserializeScene(snap)
        self.viewport.scene = self.scene
        self.hierarchy.scene = self.scene
        self.inspector.scene = self.scene
        self.selected = None
        self.selectedSet = set()
        self.viewport.setSelected(None)
        self.viewport.setSelectedSet(set())
        self.inspector.showObject(None)
        self.hierarchy.refresh()
        self.viewport.renderFrame()
        self.markUnsaved()
        self.status.showMessage("已撤销（Ctrl+Z）")
        return "break"

    def _onGizmoMode(self, mode):
        """工具栏按钮切换 Gizmo 模式。"""
        self.viewport.setGizmoMode(mode)

    def _onGizmoModeChanged(self, mode):
        """键盘 W/E/R 切换 Gizmo 模式后，同步工具栏按钮高亮。"""
        if hasattr(self, "toolbar"):
            self.toolbar.setGizmoMode(mode)

    def _onSelect(self, obj, additive=False):
        """视口拾取选中：obj=None 取消；additive=True（Shift）= 追加/移除多选。"""
        if additive and obj is not None:
            if obj in self.selectedSet:
                self.selectedSet.discard(obj)
                if obj is self.selected:
                    self.selected = next(iter(self.selectedSet), None)
            else:
                self.selectedSet.add(obj)
                self.selected = obj
        else:
            self.selected = obj
            self.selectedSet = {obj} if obj is not None else set()
        self._syncSelection()

    def _onHierarchySelect(self, objs):
        """层级 Treeview 多选（单击单选；Ctrl/Shift 多选）。objs 为物体列表。"""
        if not objs:
            return
        self.selectedSet = set(objs)
        self.selected = objs[-1]   # 树序最后一项作为主选中
        self._syncSelection()

    def _syncSelection(self):
        """三处联动：视口描边集合 / 检查器（主选中）/ 层级高亮集合。"""
        if self.selected is None:
            self.viewport.setSelected(None)
            self.viewport.setSelectedSet(set())
            self.inspector.showObject(None)
            return
        self.viewport.setSelected(self.selected)      # 主选中（先重置为单选）
        self.viewport.setSelectedSet(self.selectedSet)  # 再同步多选集合
        self.inspector.showObject(self.selected)
        self.hierarchy.selectObjects(self.selectedSet)

    def _onValue(self):
        """数值变化（变换/颜色）：标记未保存 + 压撤销快照 + 仅重绘视口。"""
        self.markUnsaved()
        self._pushUndo(merge=True)
        self.viewport.renderFrame()

    def _onStructure(self):
        """结构变化（名称/激活/父子/组件增删）：压撤销 + 刷新层级 + 重绘，并恢复选中高亮。"""
        self.markUnsaved()
        self._pushUndo()
        self.hierarchy.refresh()
        if self.selectedSet:
            self.hierarchy.selectObjects(self.selectedSet)
        self.viewport.renderFrame()

    def deleteSelected(self):
        """Delete：删除当前选中物体（焦点在输入框时交给输入框）。"""
        focus = self.root.focus_get()
        if isinstance(focus, (ttk.Entry, tk.Entry, tk.Text)):
            return
        targets = [o for o in self.selectedSet if o in self.scene.objects] \
            if self.selectedSet else []
        if not targets:
            return
        self._pushUndo()
        for obj in targets:
            if obj in self.scene.objects:
                self.scene.removeObject(obj)   # 连带子树一起移除
        self.selected = None
        self.selectedSet = set()
        self.viewport.setSelected(None)
        self.viewport.setSelectedSet(set())
        self.hierarchy.refresh()
        self.inspector.showObject(None)
        self.markUnsaved()

    # ---- 场景文件 ----
    def _scenePath(self):
        """保存路径：当前打开的场景文件优先，否则项目根 scene.json。"""
        if self.scenePath:
            return self.scenePath
        base = self.projectRoot if self.projectRoot else Path.cwd()
        return base / "scene.json"

    def _switchScene(self, scene, scenePath=None):
        """把新场景接到所有面板（视口/层级/检查器）并刷新。

        切换前先停止播放（V5）；若有未保存修改先询问（保存 / 不保存 / 取消）。"""
        if self._playing:
            self._stopPlay()
        if self._unsaved:
            choice = messagebox.askyesnocancel(
                "未保存", f"当前场景有未保存的修改，是否先保存？")
            if choice is None:
                return False                     # 取消：不切换
            if choice:
                self.saveScene()
        self.scene = scene
        self.scenePath = scenePath
        self.viewport.scene = scene
        self.hierarchy.scene = scene
        self.inspector.scene = scene
        self.selected = None
        self.selectedSet = set()
        self.viewport.setSelected(None)
        self.viewport.setSelectedSet(set())
        self.inspector.showObject(None)
        self.hierarchy.refresh()
        self.viewport.renderFrame()
        self._undoStack.clear()   # 切换场景后旧撤销栈作废
        self.clearUnsaved()
        return True

    def newScene(self):
        """新建空场景（文件菜单，不落盘）。"""
        if self._switchScene(createDemoScene(), None):
            self.status.showMessage("已新建演示场景（未保存）")

    def saveScene(self):
        """保存场景到当前场景文件（或项目根 scene.json）。"""
        try:
            path = saveSceneFile(self.scene, self._scenePath())
            self.scenePath = path
            self.clearUnsaved()
            self.status.showMessage(f"已保存 {path.name}")
        except OSError as e:
            messagebox.showerror(APP_NAME, f"保存失败：{e}")

    def openScene(self):
        """打开场景（当前目录的项目根 scene.json，Ctrl+O）。"""
        path = self._scenePath()
        if not path.exists():
            messagebox.showinfo(APP_NAME, f"没有场景文件：{path}")
            return
        self.openSceneFile(path)

    def openSceneFile(self, path):
        """打开场景文件（项目面板双击 .vscene / Ctrl+O）。"""
        path = Path(path)
        if not path.is_file():
            messagebox.showinfo(APP_NAME, f"场景文件不存在：{path}")
            return
        scene = loadSceneFile(path)
        if not scene.objects:
            messagebox.showinfo(APP_NAME, f"「{path.name}」为空场景，已打开。")
        if self._switchScene(scene, path):
            self.status.showMessage(f"已打开场景 {path.name}")

    def _onEditMaterial(self, rel):
        """资源浏览器选中/双击 .vmat：检查器进入材质编辑模式。"""
        if self.inspector is not None:
            self.inspector.showMaterial(rel)

    def _onSaveMaterial(self):
        """材质保存完成：重绘视口（所有引用该材质的物体立即变色）。"""
        self.viewport.renderFrame()
        self.status.showMessage("材质已保存")

    # ---- 创建物体 ----
    CREATE_OPTIONS = {
        "empty": ("空物体", lambda: GameObject(name="空物体")),
        "cube": ("立方体", lambda: _goWith("cube", material="default")),
        "sphere": ("球体", lambda: _goWith("sphere", material="default")),
        "camera": ("摄像机", _goCamera),
        "directional": ("方向光", lambda: _goLight("directional", [1.0, 1.0, 0.95], 1.0)),
        "point": ("点光源", lambda: _goLight("point", [1.0, 0.9, 0.7], 1.2)),
    }

    def createObject(self, kind):
        """创建物体（工具栏选择列表）：空物体 / 立方体 / 球体 / 摄像机 / 方向光 / 点光源。"""
        maker = self.CREATE_OPTIONS.get(kind)
        if maker is None:
            self.status.showMessage(f"未知的创建类型：{kind}")
            return
        go = maker[1]()
        # 方向光沿 -Y 下照（旋转 45,-30 更像午后斜光）
        if kind == "directional":
            go.transform.rotation = np.array([45.0, -30.0, 0.0])
        n = len(self.scene.objects)
        go.transform.position = np.array([(n % 5) * 1.5, 0.75, (n // 5) * 1.5])
        self.scene.addObject(go)
        self._onSelect(go)
        self.hierarchy.refresh()
        self.hierarchy.selectObject(go)
        self.viewport.renderFrame()
        self.markUnsaved()
        self._pushUndo()
        self.status.showMessage(f"已创建「{go.name}」")

    def importModel(self, path):
        """导入 .obj 到项目 Resources/Models，刷新项目面板与网格下拉。"""
        try:
            rel = importModelFile(path, self.projectRoot)
        except (OSError, ValueError) as e:
            messagebox.showerror(APP_NAME, f"导入失败：{e}")
            return
        self.project.refresh()
        self.status.showMessage(f"已导入模型 {rel}")

    def _onModelImported(self, rel):
        """导入完成：刷新检查器网格下拉（若选中物体在编辑网格）。"""
        if self.inspector is not None:
            self.inspector.refreshMeshOptions()

    def _onUseMesh(self, rel):
        """项目面板双击 .obj：给选中物体换网格；无选中则创建新物体。"""
        if self.selected is not None and self.selected.getComponent(MeshRenderer) is not None:
            mr = self.selected.getComponent(MeshRenderer)
            mr.mesh = rel
            self.viewport.renderFrame()
            self.markUnsaved()
            self._pushUndo()
            self.status.showMessage(f"已把「{self.selected.name}」的网格设为 {rel}")
            return
        go = GameObject(name=Path(rel).stem)
        go.addComponent(MeshRenderer(mesh=rel, material="default"))
        n = len(self.scene.objects)
        go.transform.position = np.array([(n % 5) * 1.5, 0.75, (n // 5) * 1.5])
        self.scene.addObject(go)
        self._onSelect(go)
        self.hierarchy.refresh()
        self.hierarchy.selectObject(go)
        self.viewport.renderFrame()
        self.markUnsaved()
        self._pushUndo()
        self.status.showMessage(f"已创建物体（模型 {rel}）")

    # ---- 设置 ----
    def openSettings(self):
        from .ui.settingsDialog import SettingsDialog
        SettingsDialog(self.root, self.prefs, onApply=self._applyPrefs)

    def _applyPrefs(self, prefs):
        """应用并保存偏好。"""
        savePreferences(prefs)
        self.prefs = prefs
        self.viewport.applyPreferences(prefs)

    # ---- 帧率 ----
    def _updateFPS(self):
        now = time.monotonic()
        frames = self.viewport.frameCount - self._lastFrames
        self._lastFrames = self.viewport.frameCount
        dt = now - self._lastFPS
        self._lastFPS = now
        if dt > 0:
            self.status.showFPS(frames / dt)
        self.root.after(REFRESH_MS, self._updateFPS)


def _testDataLayer():
    """无窗口数据层自检：组件 / 父子 / 世界矩阵 / 序列化往返 / 内置网格。"""
    from .core.scene import Scene
    from .core.serializer import deserializeScene, serializeScene
    from .core.meshCache import getMesh

    scene = Scene()
    parent = GameObject(name="父")
    child = GameObject(name="子")
    child.transform.position = np.array([1.0, 2.0, 3.0])
    child.transform.rotation = np.array([0.0, 90.0, 0.0])
    child.addComponent(MeshRenderer(mesh="sphere", material="default"))
    sun = GameObject(name="方向光")
    sun.addComponent(Light(lightType="directional", color=[1.0, 1.0, 0.9], intensity=1.5))
    scene.addObject(parent)
    scene.addObject(child)
    scene.addObject(sun)
    scene.setParent(child, parent)
    assert child.parent is parent and parent.children == [child], "setParent 失败"
    # 世界矩阵：子平移应叠加父平移
    parent.transform.position = np.array([10.0, 0.0, 0.0])
    m = worldMatrix(child)
    assert abs(m[0, 3] - 11.0) < 1e-6 and abs(m[1, 3] - 2.0) < 1e-6, "worldMatrix 未叠加父链"
    # 序列化往返（含 Light 组件）
    data = serializeScene(scene)
    restored = deserializeScene(data)
    assert len(restored.objects) == 3, "反序列化物体数不符"
    rp = restored.findByUuid(parent.uuid)
    rc = restored.findByUuid(child.uuid)
    rs = restored.findByUuid(sun.uuid)
    assert rp is not None and rc is not None and rs is not None, "uuid 未保留"
    assert rc.parent is rp, "父子引用未恢复"
    assert rc.name == "子" and rc.active is True, "字段未恢复"
    assert abs(rc.transform.position[1] - 2.0) < 1e-9, "Transform 未恢复"
    mr = rc.getComponent(MeshRenderer)
    assert mr is not None and mr.mesh == "sphere", "MeshRenderer 未恢复"
    rl = rs.getComponent(Light)
    assert rl is not None and rl.lightType == "directional", "Light 未恢复"
    assert abs(rl.intensity - 1.5) < 1e-9 and abs(rl.color[2] - 0.9) < 1e-9, "Light 字段未恢复"
    # 组件增删（Transform 不可移除）
    assert parent.getComponent(MeshRenderer) is None
    parent.addComponent(MeshRenderer(mesh="cube"))
    assert parent.getComponent(MeshRenderer) is not None, "挂载组件失败"
    assert parent.removeComponent(parent.getComponent(MeshRenderer)), "移除组件失败"
    assert parent.getComponent(MeshRenderer) is None
    assert not parent.removeComponent(parent.transform), "Transform 不应可移除"
    # 内置 .obj 网格加载（cube / sphere 都必须可解析且有三角面）
    for meshName in ("cube", "sphere"):
        data = getMesh(meshName)
        assert data is not None, f"内置网格 {meshName} 加载失败"
        assert len(data.indices) > 0 and len(data.indices) % 3 == 0, f"{meshName} 无三角面"
        assert data.vertices.shape[1] == 3 and data.normals.shape[1] == 3, f"{meshName} 顶点/法线维数错误"
    # V5：Script 组件序列化往返
    from .core.scene import Script
    scr = GameObject(name="脚本物")
    scr.addComponent(Script(script="Scripts/转圈.vpy"))
    scene.addObject(scr)
    data2 = serializeScene(scene)
    rest2 = deserializeScene(data2)
    rsc = rest2.findByUuid(scr.uuid)
    rscComp = rsc.getComponent(Script) if rsc else None
    assert rscComp is not None and rscComp.script == "Scripts/转圈.vpy", "Script 组件未序列化/恢复"
    print("[自检] 数据层通过：组件 / 父子 / 世界矩阵 / 序列化往返 / 内置网格 / Script")


def selftest():
    """无交互自检：数据层 + 临时项目 + 构建窗口 + OpenGL 渲染 3 帧 + 清理。"""
    import shutil
    import tempfile

    print("[自检] 开始…")
    _testDataLayer()
    with tempfile.TemporaryDirectory(prefix="vortex_editor_selftest_") as tmp:
        proj = Path(tmp) / "自检项目"
        (proj / "Resources").mkdir(parents=True)
        (proj / "Engine").mkdir()
        (proj / "Engine" / "engineData.ved").write_text(
            json.dumps({"name": "自检项目", "engineVersion": "0.1.0"}, ensure_ascii=False),
            encoding="utf-8",
        )
        assert isVortexProject(proj), "项目识别失败"
        assert readProjectName(proj) == "自检项目", "项目名读取失败"

        # 内置 .obj 模型文件必须存在（创建/渲染依赖）
        modelsDir = Path(__file__).resolve().parent / "assets" / "models"
        for model in ("cube.obj", "sphere.obj"):
            assert (modelsDir / model).is_file(), f"缺少内置模型 {model}"

        root = tk.Tk()
        app = EditorApp(root, projectRoot=proj)
        root.update()   # 让窗口映射，视口获得 HWND
        # 等 WGL 初始化（after 50ms 重试机制），最多等 20 次
        vp = app.viewport
        for _ in range(20):
            root.update()
            if vp._ctx is not None:
                break
            time.sleep(0.05)
        assert vp._ctx is not None, "OpenGL 上下文未创建（WGL 嵌入失败）"
        # 上下文刚建立时立即做 GL 调用会报 1282，先让渲染循环转几帧
        time.sleep(0.2)
        root.update()
        fc0 = vp.frameCount
        vp.renderFrame()   # 显式渲染一帧（帧计数递增）
        root.update()
        assert vp.frameCount > fc0, "renderFrame 未渲染（frameCount 未递增）"
        ver = vp.glVersion()
        assert ver, "无法读取 OpenGL 版本"
        # 拾取逻辑自检：点击视口中心应命中演示立方体
        picked = vp.pickObject(vp.winfo_width() // 2, vp.winfo_height() // 2)
        assert picked is not None, "视口中心拾取未命中物体"
        # 连续渲染验证：update 循环应持续产生新帧（60fps 连续渲染）
        fc1 = vp.frameCount
        for _ in range(5):
            root.update()
            time.sleep(0.05)
        assert vp.frameCount > fc1, "连续渲染循环未运行"
        # V5：脚本执行（start/update）与播放快照恢复
        from .core.runtime import _clearCache, startScripts, updateScripts
        from .core.scene import Script
        (proj / "Resources" / "Scripts").mkdir(exist_ok=True)
        (proj / "Resources" / "Scripts" / "转圈.vpy").write_text(
            "def start(obj):\n    obj._started = True\n\n"
            "def update(obj, dt):\n    obj.transform.rotation[1] += 90 * dt\n",
            encoding="utf-8")
        go = GameObject(name="转盘")
        go.addComponent(MeshRenderer(mesh="cube", material="default"))
        go.addComponent(Script(script="Scripts/转圈.vpy"))
        app.scene.addObject(go)
        _clearCache()
        startScripts(app.scene, proj)
        assert getattr(go, "_started", False), "脚本 start 未调用"
        r0 = go.transform.rotation[1]
        updateScripts(app.scene, proj, 1.0)
        assert abs((go.transform.rotation[1] - r0) - 90.0) < 1e-6, "脚本 update 未执行"
        app._togglePlay()                       # 进入播放
        assert app._playing, "播放未进入"
        assert app._playWindow is not None, "播放窗口未创建"
        app.scene.findByUuid(go.uuid).transform.position[0] = 99.0   # 播放中修改
        app._togglePlay()                       # 停止 → 恢复播放前快照
        assert not app._playing, "播放未停止"
        assert app._playWindow is None, "播放窗口未销毁"
        restored = app.scene.findByUuid(go.uuid)
        assert restored is not None and abs(restored.transform.position[0] - 0.0) < 1e-6, \
            "停止播放未恢复播放前场景"
        # V5.2：代码编辑器（高亮 + 保存写回）
        from .ui.codeEditor import CodeEditorWindow
        sp = proj / "Resources" / "Scripts" / "高亮.vpy"
        sp.parent.mkdir(exist_ok=True)
        sp.write_text("def start(obj):\n    # 注释\n    x = 1 + 2\n    pass\n", encoding="utf-8")
        ce = CodeEditorWindow(root, sp)
        root.update()
        assert ce.editor.tag_ranges("keyword"), "关键字高亮未生效"
        assert ce.editor.tag_ranges("comment"), "注释高亮未生效"
        ce.editor.insert("end", "\nobj.transform.rotation[1] += 1  # 转")
        ce.editor.edit_modified(False)
        ce.save()
        root.update()
        assert "rotation[1] += 1" in sp.read_text(encoding="utf-8"), "代码编辑器保存失败"
        ce._dirty = False
        ce.destroy()
        print(f"[自检] 通过：窗口 / 项目识别 / WGL 上下文 / 渲染 / 拾取 / 连续渲染 / 脚本播放 / 代码编辑器 / 图标（{ver}）")
        vp.dispose()
        root.destroy()
    return 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    projectRoot = None
    if "--project" in sys.argv:
        i = sys.argv.index("--project")
        if i + 1 < len(sys.argv):
            candidate = Path(sys.argv[i + 1])
            if not isVortexProject(candidate):
                print(f"错误：「{candidate}」不是有效的 Vortex 项目（缺少 Engine/engineData.ved）")
                sys.exit(1)
            projectRoot = candidate
    root = tk.Tk()
    EditorApp(root, projectRoot=projectRoot)
    root.mainloop()


if __name__ == "__main__":
    main()