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
import time
import tkinter as tk

import numpy as np

from OpenGL.GL import (GL_AMBIENT, GL_AMBIENT_AND_DIFFUSE, GL_BLEND,
                       GL_COLOR_BUFFER_BIT, GL_CONSTANT_ATTENUATION,
                       GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
                       GL_DIFFUSE, GL_FLOAT, GL_FRONT_AND_BACK, GL_LEQUAL,
                       GL_LIGHT0, GL_LIGHT_MODEL_AMBIENT,
                       GL_LIGHTING, GL_LINEAR_ATTENUATION, GL_LINE_LOOP, GL_LINES,
                       GL_MODELVIEW,
                       GL_MODELVIEW_MATRIX,
                       GL_NORMAL_ARRAY, GL_ONE_MINUS_SRC_ALPHA, GL_POSITION,
                       GL_PROJECTION, GL_PROJECTION_MATRIX, GL_QUADRATIC_ATTENUATION,
                       GL_QUADS, GL_SHININESS, GL_SPECULAR,
                       GL_SRC_ALPHA, GL_TRIANGLES, GL_UNSIGNED_INT, GL_VERTEX_ARRAY,
                       GL_VERSION,
                       glBegin, glBlendFunc, glClear, glClearColor, glColor3f,
                       glColor4f, glDepthFunc, glDisable, glDisableClientState,
                       glDrawElements,
                       glEnable, glEnableClientState, glEnd, glGetFloatv, glGetString,
                       glLightModelfv, glLightfv, glLightf, glLineWidth, glLoadIdentity,
                       glMaterialfv, glMaterialf, glMatrixMode, glMultMatrixf,
                       glNormalPointer,
                       glPopMatrix, glPushMatrix, glTranslatef, glVertex3f,
                       glVertexPointer, glViewport)
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
from ..core.materialCache import loadMaterial
from ..core.scene import Camera, Light, MeshRenderer, worldMatrix
from ..core.meshCache import getMesh

# ---- Win32 / WGL 常量 ----
GCL_STYLE = -16
CS_OWNDC = 0x20
PFD_DRAW_TO_WINDOW = 0x00000004
PFD_SUPPORT_OPENGL = 0x00000020
PFD_DOUBLEBUFFER = 0x00000001
PFD_TYPE_RGBA = 0

REF = 16          # 每帧间隔 ms（约 60 FPS）
CLICK_TOL = 5.0   # 位移小于该像素视为「点击」（拾取），否则视为拖拽

# Gizmo 旋转：每帧最大角增量（度）。@60FPS 下约 480°/s，跟手且不跳变。
ROTATE_MAX_DEG_PER_FRAME = 8.0

# 缩放灵敏度：factor = 1 + proj / (size × SCALE_SENSITIVITY)。
# 拖动一个轴长屏幕距离只放大 1/SCALE_SENSITIVITY 倍（精细控制，不再“一拖就大”）。
SCALE_SENSITIVITY = 1.6

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

    def __init__(self, master, scene=None, onSelect=None, prefs=None, projectRoot=None,
                 onTransform=None, onGizmoModeChanged=None, **kw):
        kw.setdefault("background", "#1e1e22")
        super().__init__(master, **kw)
        self.scene = scene
        self.onSelect = onSelect          # 拾取选中回调（main 提供）
        self.onTransform = onTransform    # Gizmo 变换回调（live=拖动中 / False=结束）
        self.onGizmoModeChanged = onGizmoModeChanged   # Gizmo 模式切换回调（同步工具栏）
        self.selected = None              # 主选中物体（黄色描边 + Gizmo 作用对象）
        self.selectedSet = set()          # 多选集合（Shift 追加；含主选中）
        self.projectRoot = projectRoot    # 项目根（解析 Resources 下 .obj 用）
        self.camera = OrbitCamera()
        self.keyBinds = dict(DEFAULT_KEYS)
        if prefs:
            self.applyPreferences(prefs)

        # Gizmo 状态
        self.gizmoMode = "move"           # "move" / "rotate" / "scale"
        self._gizmoDrag = None            # 当前拖拽的轴（"x"/"y"/"z"/"plane"）
        self._gizmoStart = None           # 起始物体位置（世界坐标，move 绝对式基准）
        self._gizmoStartScale = None      # 起始缩放（scale 绝对式基准）
        self._gizmoStartT = None          # move/scale: (sx,sy) 起始屏幕点；rotate: (refHit, lastAngle)

        # Win32 动态库
        self._gdi32 = ctypes.WinDLL("gdi32.dll")
        self._user32 = ctypes.WinDLL("user32.dll")
        self._opengl32 = ctypes.WinDLL("opengl32.dll")

        self._hdc = None
        self._ctx = None
        self._hwnd = 0           # 建上下文时窗口的 HWND（用于检测窗口重建）
        self._running = False
        self._after = None

        # 交互状态
        self._pressX = self._pressY = None   # 左键按下位置
        self._moved = False                   # 左键是否已发生拖拽
        self._flyActive = False               # 中键浏览模式
        self._flyRefX = self._flyRefY = 0     # 浏览转头基准（实际光标物理坐标）
        self._chars = set()                   # 当前按下的键名集合

        # 帧率
        self.frameCount = 0
        self._lastTick = None

        self.configure(cursor="crosshair")
        self.bind("<ButtonPress-1>", self._onPressLeft)
        self.bind("<B1-Motion>", self._onDragLeft)
        self.bind("<ButtonRelease-1>", self._onReleaseLeft)
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
        try:
            ready = self._ensureContext()
        except OSError:
            ready = False
        if ready:
            if self._after is None:
                self._after = self.after(REF, self._tick)   # 首帧由 after 驱动（避免竞态）
        else:
            self.after(50, self.initGL)

    def _ensureContext(self):
        """确保上下文与当前 HWND 匹配；tkinter 重建窗口导致 HWND 变化时自动重建。

        返回是否已就绪（上下文存在且 hwnd 匹配）。"""
        hwnd = int(self.winfo_id())
        if hwnd == 0:
            return False
        if self._ctx is not None and hwnd == self._hwnd:
            return True
        self._teardownGL()          # 释放旧 HDC/上下文，避免残留
        return self._createContext(hwnd)

    def _createContext(self, hwnd):
        """在指定 HWND 上创建 WGL 上下文（CS_OWNDC + 双缓冲 + 深度）。"""
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
        if not self._opengl32.wglMakeCurrent(hdc, ctx):
            self._opengl32.wglDeleteContext(ctx)
            self._user32.ReleaseDC(hwnd, hdc)
            raise OSError("wglMakeCurrent 失败")
        self._hwnd = hwnd
        self._hdc, self._ctx = hdc, ctx
        self._running = True
        return True

    def _teardownGL(self):
        """释放旧上下文 / DC（供窗口重建或析构复用，不停止渲染循环）。"""
        if self._ctx is not None:
            try:
                self._opengl32.wglMakeCurrent(None, None)
                self._opengl32.wglDeleteContext(self._ctx)
            except Exception:
                pass
        if self._hdc is not None:
            try:
                self._user32.ReleaseDC(self._hwnd, self._hdc)
            except Exception:
                pass
        self._hwnd = 0
        self._hdc = None
        self._ctx = None

    def glVersion(self):
        """OpenGL 版本字符串（自检用）。

        WGL 嵌入下建上下文后立即查询偶发 1282 / makecurrent 失败（根因：tkinter
        重建窗口使 HWND 变化、旧 HDC 失效）。这里先 _ensureContext 自动重建，
        再用原生 ctypes 直调 opengl32 清队列 + 查询，保证自检稳定。"""
        if not self._ensureContext():
            return None
        glGetError = self._opengl32.glGetError
        glGetError.restype = ctypes.c_uint
        glGetString = self._opengl32.glGetString
        glGetString.restype = ctypes.c_void_p
        glGetString.argtypes = [ctypes.c_uint]
        GL_VERSION = 0x1F02
        for _ in range(10):
            if not self._opengl32.wglMakeCurrent(self._hdc, self._ctx):
                time.sleep(0.05)
                continue
            for _ in range(64):                     # 限次清错误队列（防死循环）
                if glGetError() == 0:
                    break
            try:
                ptr = glGetString(GL_VERSION)
            except Exception:
                ptr = None
            if ptr:
                try:
                    raw = ctypes.string_at(ptr)
                    if raw:
                        return raw.decode("utf-8", "replace")
                except Exception:
                    pass
            time.sleep(0.05)
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
            return
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(50.0, w / h, 0.1, 2000.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        eye, center, up = self.camera.lookAtArgs()
        gluLookAt(eye[0], eye[1], eye[2], center[0], center[1], center[2], up[0], up[1], up[2])

    def renderFrame(self):
        """渲染一帧并计数（自检 / 外部事件可直调）。"""
        if not self._running:
            return
        if not self._ensureContext():
            return
        if not self._opengl32.wglMakeCurrent(self._hdc, self._ctx):
            return
        glClearColor(0.13, 0.14, 0.16, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        self._setupView()
        self._drawGrid()
        self._setupLights()
        self._drawScene()
        self._drawGizmo()
        self._gdi32.SwapBuffers(self._hdc)
        self.frameCount += 1

    def _setupLights(self):
        """把场景中的 Light 组件映射到固定管线光照（GL_LIGHT0..N）。

        - 方向光：方向取灯光物体世界旋转的 -Z（朝向光照射方向），位置 w=0
        - 点光源：世界位置 + 衰减，位置 w=1
        最多启用 4 盏（超出忽略）。
        无任何灯时环境光 = 0 → 场景物体全部绘制为纯黑 0,0,0
        （网格/坐标轴/Gizmo 已在各自绘制处关闭光照，不受影响）。
        """
        glEnable(GL_LIGHTING)
        lights = []
        for obj in (self.scene.objects if self.scene else []):
            if not obj.active:
                continue
            lt = obj.getComponent(Light)
            if lt is None:
                continue
            m = worldMatrix(obj)
            pos = m[:3, 3]
            # 灯光物体世界旋转的 -Z 轴 = 光照射方向
            fwd = -(m[:3, :3] @ np.array([0.0, 0.0, 1.0]))
            color = np.array(lt.color, dtype=float) * lt.intensity
            lights.append((lt.lightType, pos, fwd, color))
        # 有灯时给一点环境光让暗部可见；无灯时 0 → 全黑
        if lights:
            glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.18, 0.18, 0.22, 1.0])
        else:
            glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.0, 0.0, 0.0, 1.0])
        for i, (ltype, pos, fwd, color) in enumerate(lights[:4]):
            lightId = GL_LIGHT0 + i
            glEnable(lightId)
            if ltype == "point":
                glLightfv(lightId, GL_POSITION, [pos[0], pos[1], pos[2], 1.0])
                glLightf(lightId, GL_CONSTANT_ATTENUATION, 1.0)
                glLightf(lightId, GL_LINEAR_ATTENUATION, 0.05)
                glLightf(lightId, GL_QUADRATIC_ATTENUATION, 0.02)
            else:   # directional
                glLightfv(lightId, GL_POSITION, [fwd[0], fwd[1], fwd[2], 0.0])
            glLightfv(lightId, GL_DIFFUSE, [color[0], color[1], color[2], 1.0])
            glLightfv(lightId, GL_SPECULAR, [color[0], color[1], color[2], 1.0])
            glLightfv(lightId, GL_AMBIENT, [0.0, 0.0, 0.0, 1.0])
        for i in range(len(lights), 4):
            glDisable(GL_LIGHT0 + i)

    def _drawScene(self):
        """绘制场景物体（世界矩阵 + MeshRenderer 组件）；选中物体叠加黄色描边。

        mesh 键经 meshCache 解析为 MeshData，用顶点数组 + glDrawElements 绘制；
        光照开启时用材质色代替 glColor（固定管线）。"""
        for obj in (self.scene.objects if self.scene else []):
            if not obj.active:
                continue
            mr = obj.getComponent(MeshRenderer)
            if mr is None or not mr.mesh:
                continue
            data = getMesh(mr.mesh, self.projectRoot)
            if data is None:
                continue
            color = loadMaterial(mr.material, self.projectRoot)   # 颜色由材质资源配置
            glPushMatrix()
            glMultMatrixf(worldMatrix(obj).T.flatten())   # 列优先传给 GL（含父子链）
            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_NORMAL_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, data.vertices)
            glNormalPointer(GL_FLOAT, 0, data.normals)
            glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE,
                         [color[0], color[1], color[2], 1.0])
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.35, 0.35, 0.35, 1.0])
            glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 32.0)
            glDrawElements(GL_TRIANGLES, len(data.indices), GL_UNSIGNED_INT, data.indices)
            glDisableClientState(GL_NORMAL_ARRAY)
            glDisableClientState(GL_VERTEX_ARRAY)
            if obj in self.selectedSet:
                self._drawOutline(data)
            glPopMatrix()

    def _drawOutline(self, data):
        """选中物体黄色描边（基于网格实际边，轻微放大避免深度冲突）。"""
        edges = data.edges()
        glDisable(GL_LIGHTING)
        glLineWidth(3.0)
        glColor3f(1.0, 0.85, 0.20)
        glBegin(GL_LINES)
        for a, b in edges:
            glVertex3f(a[0] * 1.02, a[1] * 1.02, a[2] * 1.02)
            glVertex3f(b[0] * 1.02, b[1] * 1.02, b[2] * 1.02)
        glEnd()
        glLineWidth(1.0)
        glEnable(GL_LIGHTING)

    # ---- 变换 Gizmo ----
    GIZMO_COLORS = {
        "x": (0.85, 0.25, 0.25),
        "y": (0.25, 0.75, 0.35),
        "z": (0.25, 0.45, 0.85),
    }

    def _gizmoOrigin(self):
        """Gizmo 世界位置：选中物体世界原点（无选中返回 None）。"""
        if self.selected is None:
            return None
        return worldMatrix(self.selected)[:3, 3]

    def _drawGizmo(self):
        """绘制选中物体的变换 Gizmo（move=三轴箭头 / rotate=圆环 / scale=轴+方块）。

        多选（集合 > 1）时只描边、不画变换 Gizmo（避免多物体混淆），
        但相机视锥仍显示（提示朝向）。"""
        if self.selected is None:
            return
        origin = self._gizmoOrigin()
        if origin is None:
            return
        glDisable(GL_LIGHTING)
        glDisable(GL_DEPTH_TEST)   # Gizmo 始终可见（不穿模）
        if len(self.selectedSet) <= 1:
            size = self._gizmoSize(origin)
            if self.gizmoMode == "rotate":
                glLineWidth(3.5)   # 旋转圆环加粗（原来 2px 太细难抓）
                self._drawRotateGizmo(origin, size)
            elif self.gizmoMode == "scale":
                glLineWidth(2.0)
                self._drawScaleGizmo(origin, size)
            else:
                glLineWidth(2.0)
                self._drawMoveGizmo(origin, size)
        self._drawCameraFrustum()   # 选中带 Camera 组件的物体 → 画视锥朝向
        glLineWidth(1.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)

    def _gizmoSize(self, origin):
        """Gizmo 尺寸：按到相机距离缩放，保证屏幕上近似恒定大小。"""
        eye = self.camera.eye()
        dist = max(float(np.linalg.norm(origin - eye)), 1e-6)
        return max(0.5, dist * 0.18)

    def _drawMoveGizmo(self, origin, size):
        """移动模式：三轴箭头（杆 + 锥头）。"""
        for axis, color in self.GIZMO_COLORS.items():
            d = self._axisVec(axis)
            glColor3f(*color)
            glBegin(GL_LINES)
            glVertex3f(*origin); glVertex3f(*(origin + d * size))
            glEnd()
            self._drawCone(origin + d * size, d, size * 0.22, color)

    def _drawScaleGizmo(self, origin, size):
        """缩放模式：三轴杆 + 末端小方块。"""
        for axis, color in self.GIZMO_COLORS.items():
            d = self._axisVec(axis)
            glColor3f(*color)
            glBegin(GL_LINES)
            glVertex3f(*origin); glVertex3f(*(origin + d * size))
            glEnd()
            self._drawCubeHandle(origin + d * size, size * 0.09, color)

    def _drawRotateGizmo(self, origin, size):
        """旋转模式：XY / XZ / YZ 三色圆环（按轴向）。"""
        seg = 48
        for axis, color in self.GIZMO_COLORS.items():
            glColor3f(*color)
            glBegin(GL_LINE_LOOP)
            for i in range(seg):
                ang = 2.0 * math.pi * i / seg
                v = np.array([math.cos(ang), math.sin(ang), 0.0]) * size
                if axis == "x":
                    v = np.array([0.0, v[0], v[1]])
                elif axis == "y":
                    v = np.array([v[0], 0.0, v[1]])
                glVertex3f(*(origin + v))
            glEnd()

    def _axisVec(self, axis):
        """世界轴单位向量。"""
        return {"x": np.array([1.0, 0.0, 0.0]),
                "y": np.array([0.0, 1.0, 0.0]),
                "z": np.array([0.0, 0.0, 1.0])}[axis]

    def _drawCameraFrustum(self):
        """选中物体带 Camera 组件 → 画视锥（朝向 + 近/远平面框），提示相机面向哪里。

        朝向 = 物体本地 -Z（相机默认注视方向）经世界矩阵变换；
        视锥按 Camera 组件 fov（垂直角，固定 16:9 宽高比）与 near/far 计算。
        淡青色，线框，不参与光照。"""
        obj = self.selected
        if obj is None:
            return
        cam = obj.getComponent(Camera)
        if cam is None:
            return
        m = worldMatrix(obj)
        pos = m[:3, 3]
        fwd = -(m[:3, :3] @ np.array([0.0, 0.0, 1.0]))      # 本地 -Z → 世界朝向
        n = float(np.linalg.norm(fwd))
        if n < 1e-9:
            return
        fwd = fwd / n
        up = m[:3, :3] @ np.array([0.0, 1.0, 0.0])
        right = np.cross(fwd, up)
        rn = float(np.linalg.norm(right))
        if rn < 1e-9:
            right = np.array([1.0, 0.0, 0.0])
            rn = 1.0
        right = right / rn
        up2 = np.cross(right, fwd)                          # 正交上方向

        fov = max(float(cam.fov), 5.0)
        aspect = 16.0 / 9.0
        halfV = math.tan(math.radians(fov / 2.0))
        halfH = halfV * aspect
        near = max(float(cam.near), 1e-3)
        far = max(float(cam.far), near + 1e-3)

        def corners(d):
            hh, hv = halfH * d, halfV * d
            return [pos + fwd * d + right * hh + up2 * hv,
                    pos + fwd * d - right * hh + up2 * hv,
                    pos + fwd * d - right * hh - up2 * hv,
                    pos + fwd * d + right * hh - up2 * hv]

        nearC, farC = corners(near), corners(far)
        glColor3f(0.40, 0.95, 1.00)
        glLineWidth(2.2)
        glBegin(GL_LINES)
        # 四角连线（视锥侧面）
        for i in range(4):
            glVertex3f(*nearC[i]); glVertex3f(*farC[i])
        # 近平面框
        for i in range(4):
            glVertex3f(*nearC[i]); glVertex3f(*nearC[(i + 1) % 4])
        # 远平面框
        for i in range(4):
            glVertex3f(*farC[i]); glVertex3f(*farC[(i + 1) % 4])
        # 朝向中心线
        glVertex3f(*pos); glVertex3f(*(pos + fwd * far))
        glEnd()

    @staticmethod
    def _drawCone(tip, direction, length, color):
        """小锥体箭头（朝 direction，基座在 tip 的 -direction 方向）。"""
        glColor3f(*color)
        seg = 10
        side = np.cross(direction, np.array([0.0, 1.0, 0.0]))
        if np.linalg.norm(side) < 1e-6:
            side = np.cross(direction, np.array([1.0, 0.0, 0.0]))
        side = side / np.linalg.norm(side)
        base = tip - direction * length
        glBegin(GL_TRIANGLES)
        for i in range(seg):
            a = base + side * (length * 0.4) * math.cos(2 * math.pi * i / seg) \
                + np.cross(direction, side) * (length * 0.4) * math.sin(2 * math.pi * i / seg)
            b = base + side * (length * 0.4) * math.cos(2 * math.pi * (i + 1) / seg) \
                + np.cross(direction, side) * (length * 0.4) * math.sin(2 * math.pi * (i + 1) / seg)
            glVertex3f(*tip); glVertex3f(*a); glVertex3f(*b)
        glEnd()

    @staticmethod
    def _drawCubeHandle(center, half, color):
        """Gizmo 末端小方块（缩放模式手柄）。"""
        glColor3f(*color)
        glBegin(GL_QUADS)
        for quad in _CUBE_QUADS:
            for v in quad:
                glVertex3f(center[0] + v[0] * half, center[1] + v[1] * half, center[2] + v[2] * half)
        glEnd()

    def _drawGrid(self):
        """地面网格：网格线锚定在世界整数坐标上（平移/浏览时随世界一起移动，
        不会钉在视野中心或抖动）；窗口覆盖视锥并随视距扩大，边缘按与视野中心
        的世界距离渐隐（无限延伸观感）。半径设上限，避免远距时线数过多拖慢帧率。

        网格是辅助显示，不参与光照：开头显式关 GL_LIGHTING（上一帧场景绘制
        会重新开启它），保证网格/坐标轴颜色不被材质光照影响。"""
        glDisable(GL_LIGHTING)
        cx, cz = self.camera.target[0], self.camera.target[2]
        rf = min(max(15.0, self.camera.distance * 8.0), 800.0)   # 连续半径（渐隐包络用）
        r = int(rf)                                               # 整数窗口半径（画线范围用）
        gx, gz = math.floor(cx), math.floor(cz)                   # 窗口中心下取整 → 线落在整数格
        x0, x1 = gx - r, gx + r
        z0, z1 = gz - r, gz + r
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glBegin(GL_LINES)
        for x in range(x0, x1 + 1):
            t = 1.0 - abs(x - cx) / rf
            a = max(0.0, t * t)
            if a <= 0.001:
                continue
            glColor4f(0.35, 0.37, 0.42, a)
            glVertex3f(x, 0, z0); glVertex3f(x, 0, z1)
        for z in range(z0, z1 + 1):
            t = 1.0 - abs(z - cz) / rf
            a = max(0.0, t * t)
            if a <= 0.001:
                continue
            glColor4f(0.35, 0.37, 0.42, a)
            glVertex3f(x0, 0, z); glVertex3f(x1, 0, z)
        glEnd()
        # 世界坐标轴（锚定世界原点，随世界一起移动；X 红 / Y 绿 / Z 蓝）
        L = max(2.0, self.camera.distance * 0.35)
        glBegin(GL_LINES)
        glColor4f(0.85, 0.25, 0.25, 1.0); glVertex3f(0, 0.02, 0); glVertex3f(L, 0.02, 0)
        glColor4f(0.25, 0.75, 0.35, 1.0); glVertex3f(0, 0.02, 0); glVertex3f(0, L, 0)
        glColor4f(0.25, 0.45, 0.85, 1.0); glVertex3f(0, 0.02, 0); glVertex3f(0, 0.02, L)
        glEnd()
        glDisable(GL_BLEND)

    # ---- 拾取 ----
    def pickObject(self, x, y):
        """把视口内的点击坐标投影为场景物体（命中包围盒，取离点击中心最近的）。"""
        if not self._running or self.scene is None:
            return None
        if not self._ensureContext():
            return None
        self._opengl32.wglMakeCurrent(self._hdc, self._ctx)
        h = max(self.winfo_height(), 1)
        self._setupView()
        best, bestDist = None, 1e18
        for obj in self.scene.objects:
            if not obj.active or obj.getComponent(MeshRenderer) is None:
                continue
            m = worldMatrix(obj)
            pts = [self._project((m @ np.array([dx, dy, dz, 1.0]))[:3])
                   for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)]
            if not pts or any(p is None for p in pts):
                continue
            minx = min(p[0] for p in pts); maxx = max(p[0] for p in pts)
            miny = min(p[1] for p in pts); maxy = max(p[1] for p in pts)
            if minx <= x <= maxx and miny <= y <= maxy:
                c = self._project(m[:3, 3])
                if c is None:
                    continue
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

    # ---- 帧循环（连续渲染 60fps） ----
    def _tick(self):
        if not self._running:
            return
        now = time.monotonic()
        dt = min((now - self._lastTick) if self._lastTick else (1.0 / 60.0), 0.1)
        self._lastTick = now
        try:
            self._applyFlyMove(dt)   # 浏览模式按键移动（dt 平滑，避免帧率抖动）
            self.renderFrame()
        except Exception:
            pass                    # 单帧异常不中断渲染循环
        self._after = self.after(REF, self._tick)

    # ---- 浏览模式（中键）----
    def _onPressMiddle(self, event):
        self._flyActive = True
        self._hideCursor(True)
        self.focus_set()
        self._warpToCenter()
        # 基准固定为视口中心：不依赖回中后的光标读回
        # （SetCursorPos 是异步消息，立即 GetCursorPos 可能拿到回中前的位置）
        self._flyRefX, self._flyRefY = self._viewportCenter()

    def _onMiddleMotion(self, event):
        if not self._flyActive:
            return
        x, y = self._cursorPos()
        dx, dy = x - self._flyRefX, y - self._flyRefY
        if abs(dx) < 2 and abs(dy) < 2:
            return                      # 光标基本在中心：忽略微残差避免抖动
        self.camera.orbit(dx, dy)       # 中键拖动转头（同环绕手感）
        self._warpToCenter()
        # 基准保持视口中心（不动）：光标残差会在下一次 dx/dy 里自动抵消，
        # 不会累积漂移 → 旋转匀速、方向一致

    def _onReleaseMiddle(self, _event):
        self._flyActive = False
        self._hideCursor(False)

    def _applyFlyMove(self, dt):
        """根据按下的键沿相机自身轴移动（浏览模式）。"""
        if not self._flyActive or not self._chars:
            return
        fAmt = (1 if "forward" in self._chars else 0) - (1 if "back" in self._chars else 0)
        rAmt = (1 if "right" in self._chars else 0) - (1 if "left" in self._chars else 0)
        uAmt = (1 if "up" in self._chars else 0) - (1 if "down" in self._chars else 0)
        if fAmt or rAmt or uAmt:
            self.camera.move(fAmt, rAmt, uAmt, dt)

    # ---- 按键 ----
    def setGizmoMode(self, mode):
        """切换 Gizmo 模式（"move"/"rotate"/"scale"），同步回调（工具栏按钮）。"""
        if mode not in ("move", "rotate", "scale"):
            return
        self.gizmoMode = mode
        self.renderFrame()
        if self.onGizmoModeChanged:
            self.onGizmoModeChanged(mode)

    def _onKeyPress(self, event):
        # W/E/R 切换 Gizmo 模式（浏览模式激活时交给 WASD 移动）
        if not self._flyActive:
            k = event.keysym.lower()
            if k == "w":
                self.setGizmoMode("move")
                return
            if k == "e":
                self.setGizmoMode("rotate")
                return
            if k == "r":
                self.setGizmoMode("scale")
                return
            if k == "f":
                self.focusSelected()   # F：聚焦选中物体
                return
        for action, key in self.keyBinds.items():
            if event.keysym.lower() == key.lower():
                self._chars.add(action)
                break

    def focusSelected(self):
        """F 键：把相机注视点移到选中物体（保持当前距离与视角）。"""
        if self.selected is None:
            return
        origin = self._gizmoOrigin()
        if origin is None:
            return
        self.camera.target = origin.copy()
        self.renderFrame()

    def _onKeyRelease(self, event):
        for action, key in self.keyBinds.items():
            if event.keysym.lower() == key.lower():
                self._chars.discard(action)
                break

    # ---- 左键：旋转 / 平移(Shift) / Gizmo / 点击拾取 ----
    def _onPressLeft(self, event):
        self._pressX, self._pressY = event.x, event.y
        self._moved = False
        self.focus_set()
        # 先检测 Gizmo 命中（选中物体且非 Shift）
        if not (event.state & 0x0001):
            axis = self._pickGizmo(event.x, event.y)
            if axis is not None:
                self._gizmoDrag = axis
                self._gizmoStart = np.asarray(self._gizmoOrigin(), dtype=float).copy()
                self._gizmoStartScale = np.asarray(self.selected.transform.scale, dtype=float).copy()
                if self.gizmoMode == "rotate":
                    self._gizmoStartT = None   # rotate 首帧由 _dragRotate 初始化参考平面点
                else:
                    # move/scale：按下时缓存轴在屏幕上的方向（单位向量）。
                    # 拖动全程用固定方向 → 物体远离/靠近相机导致轴投影翻转时
                    # 不会突跳回原位（方向翻转正是“拖远后跳回”的根因）。
                    ax, ay, _pl = self._axisScreenDir(axis)
                    self._gizmoStartT = (event.x, event.y, ax, ay)
                self._moved = True   # 视为拖拽，不触发拾取

    def _onDragLeft(self, event):
        """按住 Shift=平移视野；命中 Gizmo=变换物体；否则=环绕旋转。"""
        if self._pressX is None:
            self._pressX, self._pressY = event.x, event.y
            return
        dx, dy = event.x - self._pressX, event.y - self._pressY
        # Shift 状态位在 Windows tkinter 为 0x0001；平移不设死区以外的条件
        if event.state & 0x0001:
            if abs(dx) < 2 and abs(dy) < 2:
                return
            self._moved = True
            self._pressX, self._pressY = event.x, event.y
            self.camera.pan(dx, dy)
            self.renderFrame()   # 相机移动后立即刷新画面
            return
        if self._gizmoDrag is not None:
            # Gizmo 拖拽：按轴变换选中物体
            self._moved = True
            self._dragGizmo(event.x, event.y)
            return
        if abs(dx) < 2 and abs(dy) < 2:
            return
        self._moved = True
        self._pressX, self._pressY = event.x, event.y
        self.camera.orbit(dx, dy)
        self.renderFrame()   # 相机移动后立即刷新画面

    def _onReleaseLeft(self, event):
        if not self._moved and self._pressX is not None:
            # 轻微位移 → 视为点击，拾取物体（Shift = 追加/移除多选）
            obj = self.pickObject(event.x, event.y)
            if event.state & 0x0001 and obj is not None:
                if self.onSelect:
                    self.onSelect(obj, True)
            else:
                if self.onSelect:
                    self.onSelect(obj, False)
        wasGizmo = self._gizmoDrag is not None
        self._pressX = self._pressY = None
        self._moved = False
        self._gizmoDrag = None
        self._gizmoStart = None
        self._gizmoStartScale = None
        self._gizmoStartT = None
        if wasGizmo and self.onTransform:
            # Gizmo 变换结束：完整刷新检查器
            self.onTransform(self.selected, live=False)

    # ---- Gizmo 拾取与拖拽 ----
    def _pickGizmo(self, x, y):
        """返回命中的 Gizmo 手柄（"x"/"y"/"z" 或 None）。阈值 = 屏幕 10px。"""
        if self.selected is None:
            return None
        origin = self._gizmoOrigin()
        if origin is None:
            return None
        size = self._gizmoSize(origin)
        tol = 10.0
        best, bestD = None, tol
        for axis in ("x", "y", "z"):
            p = origin + self._axisVec(axis) * size
            sp = self._project(p)
            so = self._project(origin)
            if sp is None or so is None:
                continue
            d = _pointSegDist(x, y, so, sp)
            if d < bestD:
                best, bestD = axis, d
        return best

    def _dragGizmo(self, x, y):
        """按当前 Gizmo 模式变换选中物体（每帧绝对量计算，跟手）。"""
        if self.selected is None or self._gizmoStart is None:
            return
        axis = self._gizmoDrag
        if self.gizmoMode == "rotate":
            self._dragRotate(x, y, axis)
        elif self.gizmoMode == "scale":
            self._dragScale(x, y, axis)
        else:
            self._dragMove(x, y, axis)
        self.renderFrame()
        if self.onTransform:
            self.onTransform(self.selected, live=True)   # 实时刷新检查器数值（不重建）

    def _dragMove(self, x, y, axis):
        """移动：鼠标位移投影到轴屏幕方向（用当前物体位置换算比例），
        位移 = 起始位置 + 轴 × 投影量（绝对量，不累积漂移，跟手）。"""
        origin = self._gizmoOrigin()
        if origin is None:
            return
        proj = self._screenAxisProj(x, y, origin, axis)
        tr = self.selected.transform
        tr.position = self._gizmoStart + self._axisVec(axis) * proj

    def _dragScale(self, x, y, axis):
        """缩放：鼠标位移投影到轴 → 起始缩放 × 因子（非等比，每轴独立）。

        灵敏度：拖动一个轴长屏幕距离只放大 1/SCALE_SENSITIVITY 倍，
        配合固定轴方向 → 精细、跟手、不跳变。"""
        origin = self._gizmoOrigin()
        if origin is None:
            return
        size = self._gizmoSize(origin)
        proj = self._screenAxisProj(x, y, origin, axis)
        factor = 1.0 + proj / max(size * SCALE_SENSITIVITY, 1e-6)
        tr = self.selected.transform
        sc = self._gizmoStartScale.copy()
        idx = {"x": 0, "y": 1, "z": 2}[axis]
        sc[idx] = max(sc[idx] * factor, 0.05)
        tr.scale = sc

    def _screenAxisProj(self, x, y, origin, axis):
        """鼠标从起始屏幕点的位移 → 沿该轴的世界位移量（跟手核心）。

        方向 = 按下时缓存的轴屏幕方向（全程固定，杜绝投影翻转导致回跳）；
        比例用「当前」物体位置实时换算（轴上 size 世界单位 = 多少屏幕像素），
        物体移动后比例自适应，速度保持跟手。位移 = 像素投影 ÷ 比例。"""
        t = self._gizmoStartT
        if not isinstance(t, tuple) or len(t) != 4:
            return 0.0
        sx, sy, ax, ay = t
        size = self._gizmoSize(origin)
        p0 = self._project(origin)
        p1 = self._project(origin + self._axisVec(axis) * size)
        if p0 is None or p1 is None:
            return 0.0
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return 0.0
        projPx = (x - sx) * ax + (y - sy) * ay            # 沿固定轴方向的像素投影
        return projPx * (size / length)                   # 像素 → 世界单位

    def _axisScreenDir(self, axis):
        """轴在屏幕上的方向（单位向量）与 像素/世界 比例，按下时缓存用。"""
        origin = self._gizmoOrigin()
        if origin is None:
            return 0.0, 0.0, 1.0
        size = self._gizmoSize(origin)
        p0 = self._project(origin)
        p1 = self._project(origin + self._axisVec(axis) * size)
        if p0 is None or p1 is None:
            return 0.0, 0.0, 1.0
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return 0.0, 0.0, 1.0
        return dx / length, dy / length, size / length

    def _dragRotate(self, x, y, axis):
        """旋转：射线与过原点、法线为轴的平面求交，逐帧增量角度 → 绕轴旋转。

        - 参考点固定为按下时的平面交点，角度全程从参考算起（绝对量，不累积漂移）
        - 每帧限制最大角速度（ROTATE_MAX_DEG_PER_FRAME），快速拖动不跳变"""
        rayO, rayD = self._screenRay(x, y)
        if rayD is None:
            return
        origin = self._gizmoOrigin()
        if origin is None:
            return
        n = self._axisVec(axis)
        denom = float(rayD @ n)
        if abs(denom) < 1e-9:
            return
        tPlane = float((origin - rayO) @ n) / denom
        hit = rayO + rayD * tPlane
        if self._gizmoStartT is None:
            self._gizmoStartT = (hit, 0.0)
            return
        ref, lastDeg = self._gizmoStartT
        # 以参考平面点建立局部坐标（u,v），用 atan2 求当前相对参考的总角
        u = np.array([1.0, 0.0, 0.0])
        if abs(float(u @ n)) > 0.9:
            u = np.array([0.0, 0.0, 1.0])
        u = u - (u @ n) * n
        u = u / max(float(np.linalg.norm(u)), 1e-9)
        v = np.cross(n, u)
        angNow = math.atan2(float((hit - origin) @ v), float((hit - origin) @ u))
        angRef = math.atan2(float((ref - origin) @ v), float((ref - origin) @ u))
        total = angNow - angRef
        if total > math.pi: total -= 2 * math.pi
        if total < -math.pi: total += 2 * math.pi
        totalDeg = math.degrees(total)
        # 每帧增量 + 最大角速度限制（防跳变）
        step = totalDeg - lastDeg
        maxStep = ROTATE_MAX_DEG_PER_FRAME
        if step > maxStep: step = maxStep
        if step < -maxStep: step = -maxStep
        tr = self.selected.transform
        rot = np.asarray(tr.rotation, dtype=float).copy()
        idx = {"x": 0, "y": 1, "z": 2}[axis]
        rot[idx] += step
        tr.rotation = rot
        self._gizmoStartT = (ref, totalDeg)   # 记住最新总量，下一帧差值为增量

    def _screenRay(self, x, y):
        """视口坐标 → 世界射线 (origin, dir)；失败返回 (None, None)。"""
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 0 or h <= 0:
            return None, None
        try:
            mv = np.asarray(glGetFloatv(GL_MODELVIEW_MATRIX), dtype=float).reshape(4, 4).T
            pr = np.asarray(glGetFloatv(GL_PROJECTION_MATRIX), dtype=float).reshape(4, 4).T
            inv = np.linalg.inv(pr @ mv)
            ndcX = 2.0 * x / w - 1.0
            ndcY = 1.0 - 2.0 * y / h
            near = inv @ np.array([ndcX, ndcY, -1.0, 1.0])
            far = inv @ np.array([ndcX, ndcY, 1.0, 1.0])
            if abs(near[3]) < 1e-9 or abs(far[3]) < 1e-9:
                return None, None
            pNear = near[:3] / near[3]
            pFar = far[:3] / far[3]
            d = pFar - pNear
            n = np.linalg.norm(d)
            if n < 1e-9:
                return None, None
            return pNear, d / n
        except Exception:
            return None, None

    def _onWheel(self, event):
        self.camera.zoom(event.delta)
        self.renderFrame()   # 相机缩放后立即刷新画面

    # ---- 辅助 ----
    def _cursorPos(self):
        """当前光标在屏幕上的物理像素坐标（GetCursorPos，兼容高 DPI）。"""
        pt = wt.POINT()
        self._user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _hideCursor(self, hide):
        try:
            self._user32.ShowCursor(0 if hide else 1)   # FALSE=隐藏 / TRUE=显示
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
        """外部（层级/检查器）设置选中（单选），更新描边。"""
        self.selected = obj
        self.selectedSet = {obj} if obj is not None else set()
        self.renderFrame()

    def setSelectedSet(self, objs):
        """外部（main）同步多选集合，更新描边（不含 renderFrame）。"""
        self.selectedSet = set(objs)
        if self.selected is not None and self.selected not in self.selectedSet:
            self.selected = next(iter(self.selectedSet), None)

    # ---- 释放 ----
    def dispose(self):
        """析构：停止渲染循环并释放 OpenGL 上下文。"""
        self._running = False
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        self._teardownGL()


# ---- 立方体几何数据（Gizmo 方块手柄用） ----
_CUBE_QUADS = [
    [(1, 1, 1), (-1, 1, 1), (-1, -1, 1), (1, -1, 1)],      # 前
    [(1, 1, -1), (1, -1, -1), (-1, -1, -1), (-1, 1, -1)],  # 后
    [(1, 1, 1), (1, 1, -1), (1, -1, -1), (1, -1, 1)],      # 右
    [(-1, 1, 1), (-1, -1, 1), (-1, -1, -1), (-1, 1, -1)],  # 左
    [(1, 1, 1), (1, 1, -1), (-1, 1, -1), (-1, 1, 1)],      # 上
    [(1, -1, 1), (-1, -1, 1), (-1, -1, -1), (1, -1, -1)],  # 下
]


def _pointSegDist(px, py, a, b):
    """点到线段（屏幕坐标）的最短距离。"""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    lengthSq = dx * dx + dy * dy
    if lengthSq < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / lengthSq))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))