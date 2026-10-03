# -*- coding: utf-8 -*-
"""OpenGL 视口（WGL 嵌入 tkinter HWND）。

功能（2026-10-03 用户需求全量落地）：
- 左键拖拽环绕、点击拾取选中（<5px 视为点击）、选中物体黄色描边
- Shift+左键拖拽平移视野；滚轮缩放
- 中键按住进入浏览模式（隐藏光标，WASD/QE 移动、拖动转头）
- 地面网格无限延伸并随视距淡出（辅助显示，不属场景）
- 帧率统计（frameCount，供状态栏显示）

技术要点（项目记忆已归档）：
- 上下文 = ctypes 直调 opengl32/gdi32/user32；CS_OWNDC 用 user32 API
- 首帧由 after 驱动，不在建上下文回调里同步渲染；单帧异常不中断循环
"""

import ctypes
import ctypes.wintypes as wt
import math
import tkinter as tk

import numpy as np

from OpenGL.GL import (GL_BLEND, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
                       GL_DEPTH_TEST, GL_LEQUAL, GL_LINES, GL_MODELVIEW,
                       GL_ONE_MINUS_SRC_ALPHA, GL_PROJECTION, GL_QUADS,
                       GL_SRC_ALPHA, GL_VERSION,
                       glBegin, glBlendFunc, glClear, glClearColor, glColor3f,
                       glColor4f, glDepthFunc, glDisable, glEnable, glEnd,
                       glGetString, glLineWidth, glLoadIdentity, glMatrixMode,
                       glPopMatrix, glPushMatrix, glTranslatef, glVertex3f,
                       glViewport)
from OpenGL.GLU import gluLookAt, gluPerspective

# WGL 嵌入 tkinter 时，窗口重绘/交换缓冲与异步查询交错的时机，
# GL 错误队列会偶发残留 GL_INVALID_OPERATION(1282)。
# PyOpenGL 默认的 errorchecker 会把这些历史错误抛成异常，打断渲染循环。
# 这里全局禁用自动抛错（错误码仍可通过 glGetError 主动查询），保证渲染稳定。
try:
    from OpenGL import error

    def _noErrorCheck(*_args, **_kw):
        return None

    error.ErrorChecker.glCheckError = _noErrorCheck
except Exception:
    pass

from .orbitCamera import OrbitCamera

# ---- Win32 / WGL 常量 ----
GCL_STYLE = -16
CS_OWNDC = 0x20
PFD_DRAW_TO_WINDOW = 0x00000004
PFD_SUPPORT_OPENGL = 0x00000020
PFD_DOUBLEBUFFER = 0x00000001
PFD_TYPE_RGBA = 0

REF = 16          # 每帧间隔 ms（约 60 FPS）
CLICK_TOL = 5.0   # 位移小于该像素视为「点击」（拾取），否则视为拖拽

# 默认按键绑定（动作 → 键名）
DEFAULT_KEYS = {
    "forward": "w", "back": "s", "left": "a", "right": "d",
    "up": "q", "down": "e",
}


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

    def __init__(self, master, scene=None, onSelect=None, prefs=None, **kw):
        kw.setdefault("background", "#1e1e22")
        super().__init__(master, **kw)
        self.scene = scene
        self.onSelect = onSelect          # 拾取选中回调（main 提供）
        self.selected = None              # 当前选中物体（黄色描边）
        self.camera = OrbitCamera()
        self.keyBinds = dict(DEFAULT_KEYS)
        if prefs:
            self.applyPreferences(prefs)

        # Win32 动态库
        self._gdi32 = ctypes.WinDLL("gdi32.dll")
        self._user32 = ctypes.WinDLL("user32.dll")
        self._opengl32 = ctypes.WinDLL("opengl32.dll")

        self._hdc = None
        self._ctx = None
        self._running = False
        self._after = None

        # 交互状态
        self._pressX = self._pressY = None   # 左键按下位置
        self._moved = False                   # 左键是否已发生拖拽
        self._flyActive = False               # 中键浏览模式
        self._chars = set()                   # 当前按下的键名集合

        # 帧率
        self.frameCount = 0

        self.configure(cursor="crosshair")
        self.bind("<ButtonPress-1>", self._onPressLeft)
        self.bind("<B1-Motion>", self._onDragLeft)
        self.bind("<ButtonRelease-1>", self._onReleaseLeft)
        self.bind("<Shift-B1-Motion>", self._onDragPan)
        self.bind("<ButtonPress-2>", self._onPressMiddle)
        self.bind("<B2-Motion>", self._onMiddleMotion)
        self.bind("<ButtonRelease-2>", self._onReleaseMiddle)
        self.bind("<MouseWheel>", self._onWheel)
        # 按键（浏览模式用）
        self.bind("<KeyPress>", self._onKeyPress)
        self.bind("<KeyRelease>", self._onKeyRelease)

        self.after(50, self.initGL)

    # ---- OpenGL 上下文 ----
    def initGL(self):
        """创建 WGL 上下文（窗口可见后调用，自动重试）。"""
        if self._ctx is not None:
            return
        hwnd = int(self.winfo_id())
        if hwnd == 0:
            self.after(50, self.initGL)
            return
        style = self._user32.GetClassLongW(hwnd, GCL_STYLE)
        self._user32.SetClassLongW(hwnd, GCL_STYLE, style | CS_OWNDC)
        hdc = self._user32.GetDC(hwnd)
        if not hdc:
            raise OSError("GetDC 失败，无法创建 OpenGL 上下文")
        pfd = _PIXELFORMATDESCRIPTOR(
            nSize=ctypes.sizeof(_PIXELFORMATDESCRIPTOR), nVersion=1,
            dwFlags=PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER,
            iPixelType=PFD_TYPE_RGBA, cColorBits=24, cDepthBits=24, iLayerType=0,
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
        self._after = self.after(REF, self._tick)   # 首帧由 after 驱动（避免竞态）

    def glVersion(self):
        """OpenGL 版本字符串（自检用）。

        坑：新建上下文后立即取版本可能报 GL_INVALID_OPERATION(1282)；
        先清空错误队列再查询，失败退化为 None。"""
        if self._ctx is None or not self._hdc:
            return None
        if not self._opengl32.wglMakeCurrent(self._hdc, self._ctx):
            return None
        try:
            from OpenGL.GL import glGetError
            while glGetError() != 0:      # 清掉建上下文阶段残留的错误标志
                pass
            raw = glGetString(GL_VERSION)
            return bytes(raw).decode("utf-8", "replace") if raw else None
        except Exception:
            return None

    # ---- 偏好 ----
    def applyPreferences(self, prefs):
        """应用用户偏好（旋转速度 / 平移灵敏度 / 移动速度 / 按键绑定）。"""
        self.camera.orbitSpeed = float(prefs.get("orbitSpeed", 1.0))
        self.camera.panSensitivity = float(prefs.get("panSensitivity", 1.0))
        self.camera.moveSpeed = float(prefs.get("moveSpeed", 1.0))
        keys = prefs.get("keys") or {}
        self.keyBinds = dict(DEFAULT_KEYS)
        self.keyBinds.update({k: str(v) for k, v in keys.items() if v})

    # ---- 渲染 ----
    def _setupView(self):
        """按当前窗口与相机设置投影/模型矩阵（渲染与拾取共用）。"""
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 0 or h <= 0:
            h = max(h, 1)
        glViewport(0, 0, w, max(h, 1))
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(50.0, w / max(h, 1), 0.1, 2000.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        eye, center, up = self.camera.lookAtArgs()
        gluLookAt(eye[0], eye[1], eye[2], center[0], center[1], center[2], up[0], up[1], up[2])

    def renderFrame(self):
        """渲染一帧（自检可直调）。"""
        if not self._running or self._ctx is None:
            return
        if not self._opengl32.wglMakeCurrent(self._hdc, self._ctx):
            return
        glClearColor(0.13, 0.14, 0.16, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        self._setupView()
        self._drawGrid()
        self._drawScene()
        self._gdi32.SwapBuffers(self._hdc)

    def _drawGrid(self):
        """地面网格：范围随视距扩大，边缘渐隐（无限延伸观感），中心跟随视野。"""
        cx, cz = self.camera.target[0], self.camera.target[2]
        r = max(15, int(self.camera.distance * 8))
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glBegin(GL_LINES)
        for i in range(-r, r + 1):
            t = 1.0 - abs(i) / r
            a = max(0.0, t * t)
            glColor4f(0.35, 0.37, 0.42, a)
            glVertex3f(cx + i, 0, cz - r); glVertex3f(cx + i, 0, cz + r)
            glVertex3f(cx - r, 0, cz + i); glVertex3f(cx + r, 0, cz + i)
        glEnd()
        glBegin(GL_LINES)   # 主轴醒目标识（X 红 / Z 蓝）
        glColor4f(0.85, 0.25, 0.25, 1.0); glVertex3f(cx, 0.01, cz); glVertex3f(cx + r * 0.8, 0.01, cz)
        glColor4f(0.25, 0.45, 0.85, 1.0); glVertex3f(cx, 0.01, cz); glVertex3f(cx, 0.01, cz + r * 0.8)
        glEnd()
        glDisable(GL_BLEND)

    def _drawScene(self):
        """绘制场景物体；选中物体叠加黄色描边。"""
        for obj in (self.scene.objects if self.scene else []):
            if not obj.active or not obj.mesh:
                continue
            t = obj.transform
            glPushMatrix()
            glTranslatef(t.position[0], t.position[1], t.position[2])
            if obj.mesh == "cube":
                self._drawCubeUnit()
                if obj is self.selected:
                    self._drawOutline()
            glPopMatrix()

    @staticmethod
    def _drawCubeUnit():
        """单位立方体（边长 2，中心在原点）。"""
        glColor3f(0.30, 0.55, 0.85)
        glBegin(GL_QUADS)
        for quad in _CUBE_QUADS:
            for v in quad:
                glVertex3f(*v)
        glEnd()
        glColor3f(0.10, 0.12, 0.15)
        glBegin(GL_LINES)
        for a, b in _CUBE_EDGES:
            glVertex3f(*a); glVertex3f(*b)
        glEnd()

    def _drawOutline(self):
        """选中物体黄色描边（加粗 + 偏移避免深度冲突）。"""
        glLineWidth(3.0)
        glColor3f(1.0, 0.85, 0.20)
        glBegin(GL_LINES)
        for a, b in _CUBE_EDGES:
            glVertex3f(a[0] * 1.02, a[1] * 1.02, a[2] * 1.02)
            glVertex3f(b[0] * 1.02, b[1] * 1.02, b[2] * 1.02)
        glEnd()
        glLineWidth(1.0)

    # ---- 拾取 ----
    def pickObject(self, x, y):
        """把视口内的点击坐标投影为场景物体（命中包围盒，取离点击中心最近的）。"""
        if not self._running or self.scene is None:
            return None
        self._opengl32.wglMakeCurrent(self._hdc, self._ctx)
        h = max(self.winfo_height(), 1)
        self._setupView()
        best, bestDist = None, 1e18
        for obj in self.scene.objects:
            if not obj.active or not obj.mesh:
                continue
            t = obj.transform
            sx, sy, sz = t.scale
            corner = []
            for dx in (-sx, sx):
                for dy in (-sy, sy):
                    for dz in (-sz, sz):
                        corner.append((t.position[0] + dx, t.position[1] + dy, t.position[2] + dz))
            pts = [self._project(p) for p in corner]
            if not pts:
                continue
            minx = min(p[0] for p in pts); maxx = max(p[0] for p in pts)
            miny = min(p[1] for p in pts); maxy = max(p[1] for p in pts)
            if minx <= x <= maxx and miny <= y <= maxy:
                c = self._project(t.position)
                d = math.hypot(x - c[0], y - c[1])
                if d < bestDist:
                    best, bestDist = obj, d
        return best

    def _project(self, worldPos):
        """世界坐标 → 视口内像素坐标（numpy 手写投影，等价 gluProject）。

        GL 矩阵 GetFloatv 出来是「列优先」展平；numpy 行优先数组相当于
        数学矩阵的转置，因此 clip = (矩阵^T) · pos。返回 tkinter 坐标（左上原点）。"""
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 0 or h <= 0:
            return None
        try:
            from OpenGL.GL import (glGetFloatv, GL_MODELVIEW_MATRIX, GL_PROJECTION_MATRIX)
            mv = np.asarray(glGetFloatv(GL_MODELVIEW_MATRIX), dtype=float).reshape(4, 4).T
            pr = np.asarray(glGetFloatv(GL_PROJECTION_MATRIX), dtype=float).reshape(4, 4).T
            clip = pr @ mv @ np.array([worldPos[0], worldPos[1], worldPos[2], 1.0])
            if abs(clip[3]) < 1e-9:
                return None
            ndc = clip / clip[3]
            winX = (ndc[0] + 1.0) * w / 2.0
            winY = (ndc[1] + 1.0) * h / 2.0
            return (winX, h - winY)
        except Exception:
            return None

    # ---- 帧循环 ----
    def _tick(self):
        if not self._running:
            return
        try:
            self._applyFlyMove()     # 浏览模式按键移动
            self.renderFrame()
            self.frameCount += 1
        except Exception:
            pass                    # 单帧异常不中断渲染循环
        self._after = self.after(REF, self._tick)

    # ---- 浏览模式（中键）----
    def _onPressMiddle(self, event):
        self._flyActive = True
        self._hideCursor(True)
        self.focus_set()
        self._warpToCenter()

    def _onMiddleMotion(self, event):
        if not self._flyActive:
            return
        cx, cy = self._viewportCenter()
        dx, dy = event.x_root - cx, event.y_root - cy
        self.camera.orbit(dx, dy)     # 中键拖动转头（同环绕手感）
        self._warpToCenter()

    def _onReleaseMiddle(self, _event):
        self._flyActive = False
        self._hideCursor(False)

    def _applyFlyMove(self):
        """根据按下的键沿相机自身轴移动（浏览模式）。"""
        if not self._flyActive or not self._chars:
            return
        fAmt = (1 if "forward" in self._chars else 0) - (1 if "back" in self._chars else 0)
        rAmt = (1 if "right" in self._chars else 0) - (1 if "left" in self._chars else 0)
        uAmt = (1 if "up" in self._chars else 0) - (1 if "down" in self._chars else 0)
        if fAmt or rAmt or uAmt:
            self.camera.move(fAmt, rAmt, uAmt)

    # ---- 按键 ----
    def _onKeyPress(self, event):
        for action, key in self.keyBinds.items():
            if event.keysym.lower() == key.lower():
                self._chars.add(action)
                break

    def _onKeyRelease(self, event):
        for action, key in self.keyBinds.items():
            if event.keysym.lower() == key.lower():
                self._chars.discard(action)
                break

    # ---- 左键：旋转 / 点击拾取；Shift+左键：平移 ----
    def _onPressLeft(self, event):
        self._pressX, self._pressY = event.x, event.y
        self._moved = False
        self.focus_set()

    def _onDragLeft(self, event):
        if self._pressX is None:
            self._pressX, self._pressY = event.x, event.y
            return
        dx, dy = event.x - self._pressX, event.y - self._pressY
        if abs(dx) < 2 and abs(dy) < 2:
            return
        self._moved = True
        self._pressX, self._pressY = event.x, event.y
        self.camera.orbit(dx, dy)
        self.renderFrame()

    def _onReleaseLeft(self, event):
        if not self._moved and self._pressX is not None:
            # 轻微位移 → 视为点击，拾取物体
            obj = self.pickObject(event.x, event.y)
            self.selected = obj
            if self.onSelect:
                self.onSelect(obj)
        self._pressX = self._pressY = None
        self._moved = False

    def _onDragPan(self, event):
        """Shift+左键拖动：平移视野。"""
        if self._pressX is None:
            self._pressX, self._pressY = event.x, event.y
            self._moved = True
            return
        dx, dy = event.x - self._pressX, event.y - self._pressY
        self._moved = True
        self._pressX, self._pressY = event.x, event.y
        self.camera.pan(dx, dy)
        self.renderFrame()

    def _onWheel(self, event):
        self.camera.zoom(event.delta)
        self.renderFrame()

    # ---- 辅助 ----
    def _hideCursor(self, hide):
        try:
            self._user32.ShowCursor(int(hide))   # <0 隐藏 / >=0 显示
        except Exception:
            pass
        self.configure(cursor="none" if hide else "crosshair")

    def _viewportCenter(self):
        return (self.winfo_rootx() + max(self.winfo_width(), 1) // 2,
                self.winfo_rooty() + max(self.winfo_height(), 1) // 2)

    def _warpToCenter(self):
        cx, cy = self._viewportCenter()
        self._user32.SetCursorPos(cx, cy)

    def setSelected(self, obj):
        """外部（层级/检查器）设置选中，更新描边。"""
        self.selected = obj
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


# ---- 立方体几何数据 ----
_CUBE_QUADS = [
    [(1, 1, 1), (-1, 1, 1), (-1, -1, 1), (1, -1, 1)],      # 前
    [(1, 1, -1), (1, -1, -1), (-1, -1, -1), (-1, 1, -1)],  # 后
    [(1, 1, 1), (1, 1, -1), (1, -1, -1), (1, -1, 1)],      # 右
    [(-1, 1, 1), (-1, -1, 1), (-1, -1, -1), (-1, 1, -1)],  # 左
    [(1, 1, 1), (1, 1, -1), (-1, 1, -1), (-1, 1, 1)],      # 上
    [(1, -1, 1), (-1, -1, 1), (-1, -1, -1), (1, -1, -1)],  # 下
]
_CUBE_EDGES = []
for quad in _CUBE_QUADS:
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        if (b, a) not in _CUBE_EDGES:
            _CUBE_EDGES.append((a, b))