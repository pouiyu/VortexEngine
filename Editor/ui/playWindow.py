# -*- coding: utf-8 -*-
"""播放窗口（V5.1）：游戏视图。

进入播放模式时弹出独立窗口，用场景里的摄像机物体（Camera 组件）作为视角，
渲染同一场景（脚本每帧由主编辑器视口驱动，本窗口只负责显示运行画面）。
关闭窗口 = 停止播放（由 main 绑定 onClose 处理）。
"""

import tkinter as tk

from ..core.scene import Camera
from ..renderer.glViewport import GLViewport


class PlayWindow(tk.Toplevel):
    """独立播放视图窗口。"""

    def __init__(self, master, scene, projectRoot=None, onClose=None):
        super().__init__(master)
        self.title("▶ 播放 — Vortex")
        self.geometry("960x540")
        self.minsize(320, 180)
        self.onClose = onClose
        self._closed = False

        self.viewport = GLViewport(self, scene=scene, projectRoot=projectRoot)
        self.viewport.playMode = True
        self.viewport.sceneCameraObj = self._findSceneCamera(scene)
        self.viewport.pack(fill=tk.BOTH, expand=True)
        # 播放即聚焦游戏视图：按键/WASD 直接生效（否则焦点在其它窗口时输入不采集）
        self.after(150, lambda: self.viewport.focus_set())

        # 场景里没有摄像机物体时给提示（仍用轨道相机兜底视角）
        if self.viewport.sceneCameraObj is None:
            bar = tk.Label(self, text="场景中没有摄像机物体（添加 Camera 组件后播放）",
                           background="#444", foreground="#ffd", anchor=tk.W)
            bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.protocol("WM_DELETE_WINDOW", self._close)

    @staticmethod
    def _findSceneCamera(scene):
        """取场景中第一个带 Camera 组件的激活物体。"""
        for obj in (scene.objects if scene else []):
            if not obj.active:
                continue
            if obj.getComponent(Camera) is not None:
                return obj
        return None

    def _close(self):
        self._closed = True
        try:
            self.viewport.dispose()
        except Exception:
            pass
        self.destroy()
        if self.onClose:
            self.onClose()
