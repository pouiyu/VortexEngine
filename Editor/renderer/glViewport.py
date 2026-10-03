# -*- coding: utf-8 -*-
"""OpenGL 视口（WGL 嵌入 tkinter HWND）。

方案：取 tkinter Frame 的句柄（winfo_id），用 opengl32.dll 的
wglCreateContext / wglMakeCurrent 建立 OpenGL 上下文，直接在该
窗口上渲染；渲染循环由 tkinter after() 驱动（不抢占 Tk 主循环）。
渲染采用兼容模式固定管线（glBegin/glEnd 等），避免着色器编译排查。

注意：
- OpenGL.Tk（Togl）在本机不可用，勿再尝试；本方案不依赖它。
- SetPixelFormat 每窗口只能调用一次，采用 CS_OWNDC 保证 DC 稳定。
"""

import ctypes
import ctypes.wintypes as wt
import tkinter as tk

from OpenGL.GL import (GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
                       GL_LEQUAL, GL_LINES, GL_MODELVIEW, GL_PROJECTION,
                       GL_QUADS, GL_VERSION, glBegin, glClear, glClearColor,
                       glColor3f, glDepthFunc, glEnable, glEnd, glGetString,
                       glLineWidth, glLoadIdentity, glMatrixMode, glPopMatrix,
                       glPushMatrix, glTranslatef, glVertex3f, glViewport)
from OpenGL.GLU import gluLookAt, gluPerspective

from .orbitCamera import OrbitCamera

# ---- Win32 / WGL 常量 ----
GCL_STYLE = -16
CS_OWNDC = 0x20
PFD_DRAW_TO_WINDOW = 0x00000004
PFD_SUPPORT_OPENGL = 0x00000020
PFD_DOUBLEBUFFER = 0x00000001
PFD_TYPE_RGBA = 0

REF = 16  # 每帧渲染间隔 ms（约 60 FPS）


class _PIXELFORMATDESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("nSize", wt.WORD), ("nVersion", wt.WORD), ("dwFlags", wt.DWORD),
        ("iPixelType", wt.BYTE), ("cColorBits", wt.BYTE),
        ("cRedBits", wt.BYTE), ("cRedShift", wt.BYTE),
        ("cGreenBits", wt.BYTE), ("cGreenShift", wt.BYTE),
        ("cBlueBits", wt.BYTE), ("cBlueShift", wt.BYTE),
        ("cAlphaBits", wt.BYTE), ("cAlphaShift", wt.BYTE),
        ("cAccumBits", wt.BYTE), ("cAccumRedBits", wt.BYTE),
        ("cAccumGreenBits", wt.BYTE), ("cAccumBlueBits", wt.BYTE),
        ("cAccumAlphaBits", wt.BYTE),
        ("cDepthBits", wt.BYTE), ("cStencilBits", wt.BYTE),
        ("cAuxBuffers", wt.BYTE), ("iLayerType", wt.BYTE),
        ("bReserved", wt.BYTE),
        ("dwLayerMask", wt.DWORD), ("dwVisibleMask", wt.DWORD),
        ("dwDamageMask", wt.DWORD),
    ]


class GLViewport(tk.Frame):
    """嵌入 tkinter 的 OpenGL 3D 视口。"""

    def __init__(self, master, scene=None, **kw):
        kw.setdefault("background", "#1e1e22")
        super().__init__(master, **kw)
        self.scene = scene
        self.camera = OrbitCamera()

        # Win32 动态库
        self._gdi32 = ctypes.WinDLL("gdi32.dll")
        self._user32 = ctypes.WinDLL("user32.dll")
        self._opengl32 = ctypes.WinDLL("opengl32.dll")

        self._hdc = None
        self._ctx = None
        self._running = False
        self._after = None
        self._lastX = None
        self._lastY = None

        # 光标与鼠标交互：左键拖拽环绕、滚轮缩放
        self.configure(cursor="crosshair")
        self.bind("<ButtonPress-1>", self._onPressLeft)
        self.bind("<B1-Motion>", self._onDragLeft)
        self.bind("<ButtonRelease-1>", self._onReleaseLeft)
        self.bind("<MouseWheel>", self._onWheel)

        # 等窗口映射后初始化 OpenGL
        self.after(50, self.initGL)

    # ---- OpenGL 上下文 ----
    def initGL(self):
        """创建 WGL 上下文（需窗口可见后调用，自动重试直到成功）。"""
        if self._ctx is not None:
            return
        hwnd = int(self.winfo_id())
        if hwnd == 0:
            self.after(50, self.initGL)
            return

        # 加 CS_OWNDC，保证 DC 稳定（SetPixelFormat 每窗口仅一次）
        style = self._user32.GetClassLongW(hwnd, GCL_STYLE)
        self._user32.SetClassLongW(hwnd, GCL_STYLE, style | CS_OWNDC)

        hdc = self._user32.GetDC(hwnd)
        if not hdc:
            raise OSError("GetDC 失败，无法创建 OpenGL 上下文")

        pfd = _PIXELFORMATDESCRIPTOR(
            nSize=ctypes.sizeof(_PIXELFORMATDESCRIPTOR), nVersion=1,
            dwFlags=PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER,
            iPixelType=PFD_TYPE_RGBA, cColorBits=24,
            cDepthBits=24, cStencilBits=0, iLayerType=0,
        )
        fmt = self._gdi32.ChoosePixelFormat(hdc, ctypes.byref(pfd))
        if not fmt:
            self._user32.ReleaseDC(hwnd, hdc)
            raise OSError("ChoosePixelFormat 失败")
        if not self._gdi32.SetPixelFormat(hdc, fmt, ctypes.byref(pfd)):
            self._user32.ReleaseDC(hwnd, hdc)
            raise OSError("SetPixelFormat 失败")

        ctx = self._opengl32.wglCreateContext(hdc)
        if not ctx:
            self._user32.ReleaseDC(hwnd, hdc)
            raise OSError("wglCreateContext 失败")
        self._opengl32.wglMakeCurrent(hdc, ctx)

        self._hdc, self._ctx = hdc, ctx
        self._running = True
        # 上下文就绪后由 after 驱动首帧（避免在建上下文同一回调里立刻渲染的竞态）
        self._after = self.after(REF, self._tick)

    def glVersion(self):
        """当前 OpenGL 版本字符串（用于自检）。"""
        if self._ctx is None or not self._hdc:
            return None
        self._opengl32.wglMakeCurrent(self._hdc, self._ctx)
        try:
            return bytes(glGetString(GL_VERSION) or b"").decode("utf-8", "replace")
        except Exception:
            return None

    def renderFrame(self):
        """渲染一帧（自检可直调）。"""
        if not self._running or self._ctx is None:
            return
        if not self._opengl32.wglMakeCurrent(self._hdc, self._ctx):
            return  # 上下文失效（如窗口已销毁），跳过本帧
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 0 or h <= 0:
            return
        glViewport(0, 0, w, h)
        glClearColor(0.13, 0.14, 0.16, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(50.0, w / max(h, 1), 0.1, 200.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        eye, center, up = self.camera.lookAtArgs()
        gluLookAt(eye[0], eye[1], eye[2], center[0], center[1], center[2], up[0], up[1], up[2])

        self._drawGrid()
        self._drawScene()
        self._gdi32.SwapBuffers(self._hdc)

    # ---- 渲染内容 ----
    def _drawGrid(self):
        """地面网格（XZ 平面，Y=0，20x20）。"""
        glBegin(GL_LINES)
        glColor3f(0.35, 0.37, 0.42)
        n = 10
        for i in range(-n, n + 1):
            glVertex3f(i, 0, -n); glVertex3f(i, 0, n)
            glVertex3f(-n, 0, i); glVertex3f(n, 0, i)
        # 主轴（X 红 / Z 蓝）
        glColor3f(0.85, 0.25, 0.25); glVertex3f(0, 0.01, 0); glVertex3f(n, 0.01, 0)
        glColor3f(0.25, 0.45, 0.85); glVertex3f(0, 0.01, 0); glVertex3f(0, 0.01, n)
        glEnd()

    def _drawScene(self):
        """绘制场景物体（V2 演示：带 mesh 标记的物体）。"""
        for obj in (self.scene.objects if self.scene else []):
            if not obj.active or not obj.mesh:
                continue
            t = obj.transform
            glPushMatrix()
            glTranslatef(t.position[0], t.position[1], t.position[2])
            if obj.mesh == "cube":
                self._drawCubeUnit()
            glPopMatrix()

    @staticmethod
    def _drawCubeUnit():
        """单位立方体（中心在原点，边长 2）。"""
        glColor3f(0.30, 0.55, 0.85)
        glBegin(GL_QUADS)
        for quad in _CUBE_QUADS:
            for v in quad:
                glVertex3f(*v)
        glEnd()
        # 线框轮廓
        glColor3f(0.10, 0.12, 0.15)
        glBegin(GL_LINES)
        for a, b in _CUBE_EDGES:
            glVertex3f(*a); glVertex3f(*b)
        glEnd()

    # ---- 帧循环 ----
    def _tick(self):
        if not self._running:
            return
        try:
            self.renderFrame()
        except Exception:
            pass  # 单帧异常不中断渲染循环
        self._after = self.after(REF, self._tick)

    # ---- 鼠标 ----
    def _onPressLeft(self, event):
        self._lastX, self._lastY = event.x, event.y

    def _onReleaseLeft(self, _event):
        self._lastX = None
        self._lastY = None

    def _onDragLeft(self, event):
        if self._lastX is None:
            self._lastX, self._lastY = event.x, event.y
            return
        dx, dy = event.x - self._lastX, event.y - self._lastY
        self._lastX, self._lastY = event.x, event.y
        self.camera.orbit(dx, dy)
        self.renderFrame()

    def _onWheel(self, event):
        self.camera.zoom(event.delta)
        self.renderFrame()

    # ---- 释放 ----
    def dispose(self):
        """析构：释放 OpenGL 上下文。"""
        self._running = False
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
        if self._ctx is not None:
            try:
                self._opengl32.wglMakeCurrent(None, None)
                self._opengl32.wglDeleteContext(self._ctx)
            except Exception:
                pass
            self._user32.ReleaseDC(int(self.winfo_id()), self._hdc)
            self._ctx = None


# 依赖引入（见上）


# ---- 立方体几何数据 ----
_CUBE_QUADS = [
    [(1, 1, 1), (-1, 1, 1), (-1, -1, 1), (1, -1, 1)],  # 前
    [(1, 1, -1), (1, -1, -1), (-1, -1, -1), (-1, 1, -1)],  # 后
    [(1, 1, 1), (1, 1, -1), (1, -1, -1), (1, -1, 1)],  # 右
    [(-1, 1, 1), (-1, -1, 1), (-1, -1, -1), (-1, 1, -1)],  # 左
    [(1, 1, 1), (1, 1, -1), (-1, 1, -1), (-1, 1, 1)],  # 上
    [(1, -1, 1), (-1, -1, 1), (-1, -1, -1), (1, -1, -1)],  # 下
]
_CUBE_EDGES = []
for quad in _CUBE_QUADS:
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        if (b, a) not in _CUBE_EDGES:
            _CUBE_EDGES.append((a, b))