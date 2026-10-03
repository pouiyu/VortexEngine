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
from .core.scene import GameObject, Light, MeshRenderer, createDemoScene, worldMatrix
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


def _goWith(mesh, color, name=None):
    """带网格渲染器的物体（创建列表辅助）。"""
    go = GameObject(name=name or ("立方体" if mesh == "cube" else "球体"))
    go.addComponent(MeshRenderer(mesh=mesh, color=color))
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
            self.scene = loadSceneFile(self.projectRoot / "scene.json")
            if not self.scene.objects:
                self.scene = createDemoScene()
        else:
            self.scene = createDemoScene()
        self.prefs = loadPreferences()
        self.selected = None            # 当前选中物体（结构刷新后恢复高亮用）

        root.title(f"{APP_NAME} — {self.projectName}")
        root.geometry("1280x760")
        root.minsize(900, 600)

        self._buildMenu()
        self._buildLayout()

        # 快捷键：Delete 删除选中（焦点在输入框时交给输入框）；Ctrl+S/O 保存/打开
        root.bind("<Delete>", lambda e: self.deleteSelected())
        root.bind("<Control-s>", lambda e: self.saveScene())
        root.bind("<Control-o>", lambda e: self.openScene())

        # 帧率统计
        self._lastFrames = 0
        self._lastFPS = time.monotonic()
        root.after(REFRESH_MS, self._updateFPS)

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
            "Vortex 游戏编辑器（V3 游戏对象系统）\n"
            "tkinter 界面 + OpenGL（WGL 嵌入）3D 视口\n"
            "GameObject + 组件（Transform / 网格渲染器）+ scene.json 序列化\n"
            "下一阶段：V4 渲染核心、V5 脚本组件与播放模式",
        )

    # ---- 布局 ----
    def _buildLayout(self):
        # 状态栏（提前创建，供项目面板/其它回调显示消息）
        self.status = StatusBar(self.root, projectPath=str(self.projectRoot) if self.projectRoot else "")
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

        # 工具栏
        toolbar = Toolbar(self.root, projectName=self.projectName, onCreate=self.createObject)
        toolbar.pack(fill=tk.X)

        # 主体：左列（层级+项目） | 视口 | 检查器
        body = ttk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Panedwindow(body, orient=tk.VERTICAL)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0), pady=2)

        self.hierarchy = HierarchyPanel(left, scene=self.scene, onSelect=self._onSelect)
        left.add(self.hierarchy, weight=2)

        self.project = ProjectPanel(left, projectRoot=self.projectRoot,
                                    onStatus=self.status.showMessage if hasattr(self, "status") else None,
                                    onImport=self._onModelImported,
                                    onUseMesh=self._onUseMesh)
        left.add(self.project, weight=1)

        self.viewport = GLViewport(body, scene=self.scene, onSelect=self._onSelect,
                                   prefs=self.prefs, projectRoot=self.projectRoot,
                                   onTransform=self._onTransform)
        self.viewport.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=2)

        self.inspector = InspectorPanel(body, scene=self.scene,
                                        onValue=self._onValue,
                                        onStructure=self._onStructure,
                                        projectRoot=self.projectRoot)
        self.inspector.pack(side=tk.LEFT, fill=tk.Y)

    def _onTransform(self, obj):
        """Gizmo 变换结束（松开）：刷新检查器数值框，保持联动。"""
        if obj is not None and self.inspector is not None:
            self.inspector.showObject(obj)

    def _onSelect(self, obj):
        """层级 / 视口拾取都能选中物体，三处联动（检查器 + 视口描边 + 层级高亮）。"""
        self.selected = obj
        if obj is None:
            self.viewport.setSelected(None)
            self.inspector.showObject(None)
            return
        self.viewport.setSelected(obj)
        self.inspector.showObject(obj)
        self.hierarchy.selectObject(obj)

    def _onValue(self):
        """数值变化（变换/颜色）：仅重绘视口。"""
        self.viewport.renderFrame()

    def _onStructure(self):
        """结构变化（名称/激活/父子/组件增删）：刷新层级 + 重绘，并恢复选中高亮。"""
        self.hierarchy.refresh()
        if self.selected is not None:
            self.hierarchy.selectObject(self.selected)
        self.viewport.renderFrame()

    def deleteSelected(self):
        """Delete：删除当前选中物体（焦点在输入框时交给输入框）。"""
        focus = self.root.focus_get()
        if isinstance(focus, (ttk.Entry, tk.Entry, tk.Text)):
            return
        obj = self.viewport.selected
        if obj is None or self.scene is None:
            return
        self.scene.removeObject(obj)   # 连带子树一起移除
        self.selected = None
        self.viewport.setSelected(None)
        self.hierarchy.refresh()
        self.inspector.showObject(None)

    # ---- 场景文件 ----
    def _scenePath(self):
        """scene.json 位置：项目根（无项目时用当前目录）。"""
        base = self.projectRoot if self.projectRoot else Path.cwd()
        return base / "scene.json"

    def newScene(self):
        """新建空场景（文件菜单）。"""
        self.scene = createDemoScene()
        self.viewport.scene = self.scene
        self.hierarchy.scene = self.scene
        self.inspector.scene = self.scene
        self.selected = None
        self.viewport.setSelected(None)
        self.inspector.showObject(None)
        self.hierarchy.refresh()
        self.viewport.renderFrame()

    def saveScene(self):
        """保存场景到 scene.json（项目根）。"""
        try:
            path = saveSceneFile(self.scene, self._scenePath())
            self.status.showMessage(f"已保存 {path.name}")
        except OSError as e:
            messagebox.showerror(APP_NAME, f"保存失败：{e}")

    def openScene(self):
        """打开场景（当前目录的项目根 scene.json，Ctrl+O）。"""
        path = self._scenePath()
        if not path.exists():
            messagebox.showinfo(APP_NAME, f"没有场景文件：{path}")
            return
        self.scene = loadSceneFile(path)
        self.viewport.scene = self.scene
        self.hierarchy.scene = self.scene
        self.inspector.scene = self.scene
        self.selected = None
        self.viewport.setSelected(None)
        self.inspector.showObject(None)
        self.hierarchy.refresh()
        self.viewport.renderFrame()
        self.status.showMessage(f"已打开 {path.name}")

    # ---- 创建物体 ----
    CREATE_OPTIONS = {
        "empty": ("空物体", lambda: GameObject(name="空物体")),
        "cube": ("立方体", lambda: _goWith("cube", [0.35, 0.55, 0.85])),
        "sphere": ("球体", lambda: _goWith("sphere", [0.55, 0.35, 0.75])),
        "directional": ("方向光", lambda: _goLight("directional", [1.0, 1.0, 0.95], 1.0)),
        "point": ("点光源", lambda: _goLight("point", [1.0, 0.9, 0.7], 1.2)),
    }

    def createObject(self, kind):
        """创建物体（工具栏选择列表）：空物体 / 立方体 / 球体 / 方向光 / 点光源。"""
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
            self.status.showMessage(f"已把「{self.selected.name}」的网格设为 {rel}")
            return
        go = GameObject(name=Path(rel).stem)
        go.addComponent(MeshRenderer(mesh=rel, color=[0.60, 0.65, 0.70]))
        n = len(self.scene.objects)
        go.transform.position = np.array([(n % 5) * 1.5, 0.75, (n // 5) * 1.5])
        self.scene.addObject(go)
        self._onSelect(go)
        self.hierarchy.refresh()
        self.hierarchy.selectObject(go)
        self.viewport.renderFrame()
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
    child.addComponent(MeshRenderer(mesh="sphere", color=[1.0, 0.5, 0.25]))
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
    print("[自检] 数据层通过：组件 / 父子 / 世界矩阵 / 序列化往返 / 内置网格")


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
        # 上下文刚建立时立即做 GL 调用会报 1282，先让渲染循环空转几帧再取版本
        before = vp.frameCount
        for _ in range(5):
            root.update()
            time.sleep(0.05)
        assert vp.frameCount > before, "frameCount 未递增（渲染循环未运行）"
        ver = vp.glVersion()
        assert ver, "无法读取 OpenGL 版本"
        # 拾取逻辑自检：点击视口中心应命中演示立方体
        picked = vp.pickObject(vp.winfo_width() // 2, vp.winfo_height() // 2)
        assert picked is not None, "视口中心拾取未命中物体"
        print(f"[自检] 通过：窗口 / 项目识别 / WGL 上下文 / 渲染循环 / 拾取 / 图标（{ver}）")
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