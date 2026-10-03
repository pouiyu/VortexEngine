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

# 包上下文自适应：既支持 python -m Editor.main（引擎根启动），
# 也支持 python Editor/main.py（脚本启动，项目偏好），两种方式都能正常相对导入。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "Editor"

from .core.preferences import loadPreferences, savePreferences
from .core.scene import createDemoScene
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
        self.scene = createDemoScene()
        self.prefs = loadPreferences()

        root.title(f"{APP_NAME} — {self.projectName}")
        root.geometry("1280x760")
        root.minsize(900, 600)

        self._buildMenu()
        self._buildLayout()

        # 快捷键：Delete 删除选中（焦点在输入框时交给输入框）
        root.bind("<Delete>", lambda e: self.deleteSelected())

        # 帧率统计
        self._lastFrames = 0
        self._lastFPS = time.monotonic()
        root.after(REFRESH_MS, self._updateFPS)

    # ---- 菜单栏 ----
    def _buildMenu(self):
        menubar = tk.Menu(self.root)
        mFile = tk.Menu(menubar, tearoff=0)
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
            "Vortex 游戏编辑器（V2 骨架）\n"
            "tkinter 界面 + OpenGL（WGL 嵌入）3D 视口\n"
            "下一阶段：V3 游戏对象系统、V4 脚本组件与播放模式",
        )

    # ---- 布局 ----
    def _buildLayout(self):
        # 工具栏
        toolbar = Toolbar(self.root, projectName=self.projectName, padding=(0, 4))
        toolbar.pack(fill=tk.X)

        # 主体：左列（层级+项目） | 视口 | 检查器
        body = ttk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Panedwindow(body, orient=tk.VERTICAL)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0), pady=2)

        self.hierarchy = HierarchyPanel(left, scene=self.scene, onSelect=self._onSelect)
        left.add(self.hierarchy, weight=2)

        self.project = ProjectPanel(left, projectRoot=self.projectRoot)
        left.add(self.project, weight=1)

        self.viewport = GLViewport(body, scene=self.scene, onSelect=self._onSelect,
                                   prefs=self.prefs)
        self.viewport.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=2)

        self.inspector = InspectorPanel(body, padding=(4, 0))
        self.inspector.pack(side=tk.LEFT, fill=tk.Y)

        # 状态栏
        self.status = StatusBar(self.root, projectPath=str(self.projectRoot) if self.projectRoot else "")
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    def _onSelect(self, obj):
        """层级 / 视口拾取都能选中物体，三处联动（检查器 + 视口描边 + 层级高亮）。"""
        if obj is None:
            self.viewport.setSelected(None)
            self.inspector.showObject(None)
            return
        self.viewport.setSelected(obj)
        self.inspector.showObject(obj)
        self.hierarchy.selectObject(obj)

    def deleteSelected(self):
        """Delete：删除当前选中物体（焦点在输入框时交给输入框）。"""
        focus = self.root.focus_get()
        if isinstance(focus, (ttk.Entry, tk.Entry, tk.Text)):
            return
        obj = self.viewport.selected
        if obj is None or self.scene is None:
            return
        if obj in self.scene.objects:
            self.scene.objects.remove(obj)
        self.viewport.setSelected(None)
        self.hierarchy.refresh()
        self.inspector.showObject(None)

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


def selftest():
    """无交互自检：临时项目 + 构建窗口 + OpenGL 渲染 3 帧 + 清理。"""
    import shutil
    import tempfile

    print("[自检] 开始…")
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

        # 图标文件必须存在（工具栏 PNG 按钮依赖）
        iconsDir = Path(__file__).resolve().parent / "assets" / "icons"
        for icon in ("cube.png", "sphere.png", "play.png"):
            assert (iconsDir / icon).is_file(), f"缺少图标 {icon}"

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