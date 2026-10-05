# -*- coding: utf-8 -*-
"""V5.3 脚本运行时：加载项目 .vpy 脚本并驱动播放模式。

脚本协议（新式，推荐）：
    def start():            # 进入播放时调用一次
        obj = getSelf()     # 获取当前物体
    def update():           # 播放期间每帧调用
        dt = getDuration()  # 帧间隔（秒）
旧式（兼容）：def start(obj) / def update(obj, dt) 仍可用。

脚本可用的全部 API 见 API_DOCS（引擎「帮助 → 脚本 API 参考」也展示同一份）。
所有 API 以模块级名字注入脚本（无需 import 即可使用）。
"""

import importlib.util
import inspect
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

import numpy as np
import tkinter as tk

from .scene import (GameObject, MeshRenderer, Script, Camera, Light,
                    Transform, worldMatrix)

# 模块缓存：绝对路径 → 模块（False 表示加载失败），避免播放期间反复读盘
_MOD_CACHE = {}
_SIG_CACHE = {}          # (模块, 函数名) → inspect.Signature（避免每帧重复解析）
_WINDOWS = {}            # 脚本创建的窗口：id → Toplevel
_WINDOW_CTR = [0]        # 窗口 id 计数器

# 运行时上下文（每次调用前由 runtime 填充，脚本 API 从这里取状态）
_CTX = {
    "obj": None,          # 当前脚本的挂载物体
    "dt": 0.0,            # 当前帧间隔（秒）
    "scene": None,        # 播放中的场景
    "projectRoot": None,  # 项目根（解析 Resources 用）
    "gameWindow": None,   # 游戏视图窗口（Toplevel，setResolution 用）
    "master": None,       # 主窗口（openWindow 的父窗口）
    "playStart": 0.0,     # 进入播放的 monotonic 时间
    "windows": _WINDOWS,
}

# 当前实际渲染相机信息（V5.4.3：主视口=轨道相机，游戏视图=场景相机；每帧由视口发布）
_CAMERA = {
    "valid": False,
    "fwd": [0.0, 0.0, -1.0],    # 相机前向（屏幕深处方向，单位向量）
    "right": [1.0, 0.0, 0.0],   # 相机右向（单位向量）
    "eye": [0.0, 3.0, 8.0],     # 相机位置
}


def setCameraInfo(fwd, right, eye):
    """视口每帧调用：发布当前相机朝向/位置（脚本 getCamera* 读取）。"""
    _CAMERA["valid"] = True
    _CAMERA["fwd"] = [float(fwd[0]), float(fwd[1]), float(fwd[2])]
    _CAMERA["right"] = [float(right[0]), float(right[1]), float(right[2])]
    _CAMERA["eye"] = [float(eye[0]), float(eye[1]), float(eye[2])]

# 输入状态（V5.4：由编辑器/游戏视图事件回调写入，脚本每帧查询）
_INPUT = {
    "down": set(),         # 当前按住的键（keysym 小写）
    "pressed": set(),      # 本帧刚按下
    "released": set(),     # 本帧刚松开
    "mouse": [0, 0],       # 鼠标在视口内位置（像素）
    "mouseDelta": [0, 0],  # 本帧鼠标位移
    "mouseDown": set(),    # 当前按住的鼠标按钮 {1,2,3}
    "mousePressed": set(),
    "mouseReleased": set(),
    "wheel": 0,            # 本帧滚轮增量（正=上滚）
}


def _beginInputFrame():
    """每帧开始时重置一次性输入状态（刚按下/刚松开/滚轮/位移）。"""
    _INPUT["pressed"].clear()
    _INPUT["released"].clear()
    _INPUT["mousePressed"].clear()
    _INPUT["mouseReleased"].clear()
    _INPUT["wheel"] = 0
    _INPUT["mouseDelta"][0] = 0
    _INPUT["mouseDelta"][1] = 0


# ---- 输入采样（视口事件回调调用） ----

def recordKeyDown(keysym):
    k = str(keysym).lower()
    if k not in _INPUT["down"]:
        _INPUT["down"].add(k)
        _INPUT["pressed"].add(k)


def recordKeyUp(keysym):
    k = str(keysym).lower()
    if k in _INPUT["down"]:
        _INPUT["down"].discard(k)
        _INPUT["released"].add(k)


def recordMouseDown(button, x, y):
    _INPUT["mouse"] = [int(x), int(y)]
    if button not in _INPUT["mouseDown"]:
        _INPUT["mouseDown"].add(button)
        _INPUT["mousePressed"].add(button)


def recordMouseUp(button):
    if button in _INPUT["mouseDown"]:
        _INPUT["mouseDown"].discard(button)
        _INPUT["mouseReleased"].add(button)


def recordMouseMove(x, y):
    _INPUT["mouseDelta"][0] += int(x) - _INPUT["mouse"][0]
    _INPUT["mouseDelta"][1] += int(y) - _INPUT["mouse"][1]
    _INPUT["mouse"] = [int(x), int(y)]


def recordMouseWheel(delta):
    _INPUT["wheel"] += int(delta)


def _clearCache():
    _MOD_CACHE.clear()
    _SIG_CACHE.clear()


def _loadModule(rel, projectRoot):
    """加载 .vpy 脚本模块（带缓存），并把 API 注入模块全局；失败返回 None。"""
    if not rel:
        return None
    root = Path(projectRoot) if projectRoot else None
    if root is None:
        return None
    path = root / "Resources" / rel
    if not path.is_file():
        return None
    key = str(path.resolve())
    if key in _MOD_CACHE:
        return _MOD_CACHE[key] or None
    try:
        name = f"vortex_script_{abs(hash(key))}"
        loader = SourceFileLoader(name, str(path))
        spec = importlib.util.spec_from_loader(name, loader)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        loader.exec_module(mod)
        mod.__dict__.update(_API)      # 注入脚本 API（模块级名字）
    except Exception as e:
        print(f"[脚本] 加载失败 {rel}: {e}", file=sys.stderr)
        _MOD_CACHE[key] = False
        return None
    _MOD_CACHE[key] = mod
    return mod


# 脚本错误回调（V5.4.3：编辑器可把错误显示到游戏视图底部，避免"静默不动"）
_SCRIPT_ERROR_HANDLER = None


def setScriptErrorHandler(fn):
    """注册脚本错误处理器：脚本 start/update 抛异常时回调 fn(message)。"""
    global _SCRIPT_ERROR_HANDLER
    _SCRIPT_ERROR_HANDLER = fn


def _call(go, mod, fnName, dt=None):
    """调用脚本的 start/update，兼容新式（无参）与旧式（obj[, dt]）签名。"""
    fn = getattr(mod, fnName, None)
    if fn is None:
        return
    _CTX["obj"] = go
    _CTX["dt"] = dt if dt is not None else 0.0
    try:
        sig = _SIG_CACHE.get((mod, fnName))
        if sig is None:
            sig = inspect.signature(fn)
            _SIG_CACHE[(mod, fnName)] = sig
        n = len(sig.parameters)
        if n == 0:
            fn()                       # 新式：def start() / def update()
        elif fnName == "start":
            fn(go)                     # 旧式：def start(obj)
        else:
            fn(go, dt)                 # 旧式：def update(obj, dt)
    except Exception as e:
        src = getattr(mod, "__file__", "") or "?"
        msg = f"[脚本] {fnName} 错误 {src}: {e}"
        print(msg, file=sys.stderr)
        if _SCRIPT_ERROR_HANDLER is not None:
            try:
                _SCRIPT_ERROR_HANDLER(msg)
            except Exception:
                pass
    finally:
        _CTX["obj"] = None
        _CTX["dt"] = 0.0


def _setContext(scene, projectRoot, gameWindow=None, master=None, fresh=False):
    """设置运行时上下文；fresh=True 时重置播放基准时间与脚本窗口。"""
    _CTX["scene"] = scene
    _CTX["projectRoot"] = projectRoot
    _CTX["gameWindow"] = gameWindow
    _CTX["master"] = master
    if fresh:
        _CTX["playStart"] = time.monotonic()
        _WINDOWS.clear()
        _WINDOW_CTR[0] = 0


def startScripts(scene, projectRoot, gameWindow=None, master=None):
    """播放进入：设置上下文 → 清空延迟调用 → 对所有带脚本组件的物体调用一次 start()。"""
    _setContext(scene, projectRoot, gameWindow=gameWindow, master=master, fresh=True)
    _SCHEDULES.clear()   # 每次播放重新开始，旧的延迟调用作废
    if scene is None:
        return
    for go in scene.objects:
        if not go.active:
            continue
        for comp in go.components:
            if isinstance(comp, Script) and comp.script:
                mod = _loadModule(comp.script, projectRoot)
                if mod is not None and hasattr(mod, "start"):
                    _call(go, mod, "start")


_SCHEDULES = []          # V5.5 延迟调用：[deadline, func, args]


def invoke(seconds, func, *args):
    """延迟 seconds 秒后调用 func(*args)（脚本模块里的函数，每播放帧检查一次）。"""
    _SCHEDULES.append([time.monotonic() + max(0.0, float(seconds)), func, args])


def _runSchedules():
    """执行到期的延迟调用；每帧末调用一次。"""
    if not _SCHEDULES:
        return
    now = time.monotonic()
    due = [s for s in _SCHEDULES if s[0] <= now]
    _SCHEDULES[:] = [s for s in _SCHEDULES if s[0] > now]
    for _, func, args in due:
        try:
            func(*args)
        except Exception as e:
            msg = f"[脚本] 延迟调用错误 {getattr(func, '__module__', '?')}: {e}"
            print(msg, file=sys.stderr)
            if _SCRIPT_ERROR_HANDLER is not None:
                try:
                    _SCRIPT_ERROR_HANDLER(msg)
                except Exception:
                    pass


def _applySimplePhysics(scene, dt):
    """V5.5 轻量物理：物体若设置了 obj.velocity / obj.useGravity / obj.angularVelocity，
    引擎每帧自动积分位移/旋转（无需脚本每帧手动加）。"""
    g = 9.8
    for go in scene.objects:
        if not go.active:
            continue
        t = go.transform
        v = getattr(go, "velocity", None)
        if getattr(go, "useGravity", False):
            if v is None:
                v = go.velocity = np.zeros(3)
            v[1] = v[1] - g * dt
        if v is not None:
            v = np.asarray(v, dtype=float)
            go.velocity = list(v)      # 写回（重力/外部改动持续生效）
            t.position = t.position + v * dt
        av = getattr(go, "angularVelocity", None)
        if av is not None:
            t.rotation = t.rotation + np.asarray(av, dtype=float) * dt


def updateScripts(scene, projectRoot, dt):
    """播放每帧：跑所有脚本 update()，帧末清理一次性输入状态。

    输入事件（键盘/鼠标/滚轮）发生在帧之间 → 本帧脚本能读到 pressed/delta；
    帧末清理，下一帧的事件重新累积。"""
    _setContext(scene, projectRoot,
                gameWindow=_CTX.get("gameWindow"), master=_CTX.get("master"))
    if scene is None:
        return
    _applySimplePhysics(scene, dt)     # 先应用物理（脚本 update 可覆盖 velocity）
    for go in scene.objects:
        if not go.active:
            continue
        for comp in go.components:
            if isinstance(comp, Script) and comp.script:
                mod = _loadModule(comp.script, projectRoot)
                if mod is not None and hasattr(mod, "update"):
                    _call(go, mod, "update", dt)
    _runSchedules()                    # 延迟调用
    _beginInputFrame()   # 帧末清理：一次性输入供下一帧重新累积


# =====================================================================
# 脚本 API（模块级注入）
# =====================================================================

def _requireScene():
    scene = _CTX.get("scene")
    if scene is None:
        raise RuntimeError("场景不可用（脚本只能在播放模式里调用场景 API）")
    return scene


# ---- 自身 / 时间 ----

def getSelf():
    """获取当前脚本所挂载的物体。"""
    return _CTX.get("obj")


def getDuration():
    """获取当前帧间隔（秒），如约 0.016。"""
    return _CTX.get("dt", 0.0)


def getTime():
    """获取播放已运行的秒数。"""
    return time.monotonic() - _CTX.get("playStart", time.monotonic())


def getRealTime():
    """获取系统真实时间戳（Unix 秒，可作随机种子等）。"""
    return time.time()


def getFPS():
    """获取当前帧率（由 dt 估算）。"""
    dt = _CTX.get("dt", 0.0)
    return round(1.0 / dt) if dt > 1e-6 else 60


def getRefreshRate():
    """获取显示器刷新率（Hz）。"""
    return _refreshRate()


def _refreshRate():
    try:
        import ctypes
        from ctypes import wintypes

        class DEVMODEW(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
                ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                ("dmOrientation", ctypes.c_short), ("dmPaperWidth", ctypes.c_short),
                ("dmPaperLength", ctypes.c_short), ("dmScale", ctypes.c_short),
                ("dmCopies", ctypes.c_short), ("dmDefaultSource", ctypes.c_short),
                ("dmPrintQuality", ctypes.c_short), ("dmColor", ctypes.c_short),
                ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
                ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
                ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD),
                ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD),
                ("dmPanningHeight", wintypes.DWORD),
            ]

        dev = DEVMODEW()
        dev.dmSize = ctypes.sizeof(DEVMODEW)
        if ctypes.windll.user32.EnumDisplaySettingsW(None, 0, ctypes.byref(dev)):
            return int(dev.dmDisplayFrequency)
    except Exception:
        pass
    return 60


def getRegion():
    """获取系统区域 / 时区（字符串）。"""
    try:
        import locale
        loc = locale.getdefaultlocale()
        tz = time.tzname
        return f"{tz[0]}（{loc[0]}）" if loc else f"{tz[0]}"
    except Exception:
        return "未知"


# ---- 场景物体 ----

def createObject(name="物体", mesh=None, material=None, position=(0, 0, 0), parent=None):
    """创建物体：mesh 可给内置名（cube/sphere）或模型资源路径，返回物体。"""
    scene = _requireScene()
    go = GameObject(name=str(name))
    if mesh:
        go.addComponent(MeshRenderer(mesh=str(mesh), material=material or "default"))
    go.transform.position = [float(v) for v in position[:3]]
    if parent is not None:
        scene.setParent(go, parent)
    scene.addObject(go)
    return go


def destroyObject(obj):
    """删除物体（连带其子树一起从场景移除）。"""
    scene = _requireScene()
    if obj is not None:
        scene.removeObject(obj)


def getSceneObjects():
    """获取场景全部物体列表。"""
    scene = _CTX.get("scene")
    return list(scene.objects) if scene is not None else []


def getObjectByName(name):
    """按名称在场景里查找物体（返回第一个同名，找不到返回 None）。"""
    for obj in getSceneObjects():
        if obj.name == name:
            return obj
    return None


# ---- V5.5 物体与变换（世界坐标 / 方向向量 / 父子） ----

def _worldAxes(obj):
    """物体世界三轴（单位向量）：前向(-Z) / 右向(+X) / 上向(+Y)。"""
    m = worldMatrix(obj)
    R = m[:3, :3]
    fwd = -(R @ np.array([0.0, 0.0, 1.0]))
    right = R @ np.array([1.0, 0.0, 0.0])
    up = R @ np.array([0.0, 1.0, 0.0])
    out = []
    for v in (fwd, right, up):
        n = float(np.linalg.norm(v))
        out.append(v / n if n > 1e-9 else v)
    return out


def getWorldPosition(obj):
    """物体世界坐标 (x, y, z)（含父级变换）。"""
    if obj is None:
        return (0.0, 0.0, 0.0)
    return tuple(float(v) for v in worldMatrix(obj)[:3, 3])


def setWorldPosition(obj, xyz):
    """设置物体世界坐标（有父级时自动换算为局部坐标）。"""
    if obj is None:
        return
    target = np.asarray(xyz, dtype=float)[:3]
    parent = obj.parent
    if parent is None:
        obj.transform.position = target
        return
    inv = np.linalg.inv(worldMatrix(parent))
    obj.transform.position = (inv @ np.append(target, 1.0))[:3]


def getForward(obj):
    """物体自身的前向（本地 -Z 的世界方向，单位向量）。"""
    return tuple(float(v) for v in _worldAxes(obj)[0])


def getRight(obj):
    """物体自身的右向（本地 +X 的世界方向，单位向量）。"""
    return tuple(float(v) for v in _worldAxes(obj)[1])


def getUp(obj):
    """物体自身的上向（本地 +Y 的世界方向，单位向量）。"""
    return tuple(float(v) for v in _worldAxes(obj)[2])


def setParent(child, parent):
    """把 child 挂到 parent 下成为子物体（parent=None 解除父子）。"""
    scene = _requireScene()
    if child is None:
        return
    if parent is child or (parent is not None and child.isDescendantOf(parent)):
        raise ValueError("不能把物体设为自己的父级或形成环")
    scene.setParent(child, parent)


def getChildren(obj):
    """物体的直接子物体列表。"""
    return list(obj.children) if obj is not None else []


# ---- V5.5 组件（按名称字符串操作） ----

_COMPONENT_TYPES = {
    "Transform": Transform,
    "MeshRenderer": MeshRenderer,
    "Light": Light,
    "Camera": Camera,
    "Script": Script,
}


def getComponent(obj, name):
    """按类型名获取组件（"MeshRenderer" / "Camera" / "Light" / "Script" / "Transform"），
    没有返回 None。返回后可直接改属性，如 cam = getComponent(camObj, "Camera"); cam.fov = 90。"""
    if obj is None:
        return None
    cls = _COMPONENT_TYPES.get(str(name))
    for c in obj.components:
        if cls is not None and isinstance(c, cls):
            return c
        if cls is None and c.TYPE == str(name):
            return c
    return None


def addComponent(obj, name):
    """按类型名添加组件；已有同类型组件时不重复添加，返回该组件。"""
    if obj is None:
        return None
    cls = _COMPONENT_TYPES.get(str(name))
    if cls is None:
        raise ValueError(f"未知组件类型：{name}（可用 MeshRenderer/Light/Camera/Script）")
    existing = obj.getComponent(cls)
    if existing is not None:
        return existing
    if cls is Transform:
        return obj.transform
    return obj.addComponent(cls())


def removeComponent(obj, name):
    """按类型名移除组件（Transform 不可移除）。"""
    if obj is None:
        return False
    comp = getComponent(obj, name)
    if comp is None:
        return False
    return obj.removeComponent(comp)


# ---- V5.5 相机控制（作用于场景中第一个带 Camera 组件的物体） ----

def _findCamera():
    for go in getSceneObjects():
        if not go.active:
            continue
        c = go.getComponent(Camera)
        if c is not None:
            return go, c
    return None, None


def setCameraFov(fov):
    """设置场景相机视场角（度）。"""
    go, c = _findCamera()
    if c is not None:
        c.fov = float(fov)


def getCameraFov():
    """获取场景相机视场角（度），没有相机返回 50。"""
    _, c = _findCamera()
    return float(c.fov) if c is not None else 50.0


def setCameraPosition(x, y, z):
    """设置场景相机位置（世界坐标）。"""
    go, _ = _findCamera()
    if go is not None:
        go.transform.position = [float(x), float(y), float(z)]


def setCameraRotation(x, y, z):
    """设置场景相机旋转（度，欧拉）。"""
    go, _ = _findCamera()
    if go is not None:
        go.transform.rotation = [float(x), float(y), float(z)]


# ---- V5.5 渲染 ----

def setBackgroundColor(r, g, b):
    """设置视口背景色（0~1），主视口与游戏视图同时生效。"""
    from ..renderer.glViewport import GLViewport
    for vp in list(GLViewport._instances):
        try:
            vp.setBackground(float(r), float(g), float(b))
        except Exception:
            pass


def getBackgroundColor():
    """获取视口背景色 (r, g, b)。"""
    from ..renderer.glViewport import GLViewport
    vp = GLViewport.lastRendered or (GLViewport._instances[0] if GLViewport._instances else None)
    if vp is None:
        return (0.13, 0.14, 0.16)
    r, g, b, _ = vp._bgColor
    return (float(r), float(g), float(b))


def setObjectVisible(obj, visible):
    """设置物体可见性（obj.active，控制渲染与脚本更新）。"""
    if obj is not None:
        obj.active = bool(visible)


def isObjectVisible(obj):
    """物体是否可见（激活）。"""
    return bool(obj.active) if obj is not None else False


# ---- V5.5 数学辅助 ----

def lerp(a, b, t):
    """线性插值（标量或向量，t 取 0~1）。"""
    t = max(0.0, min(1.0, float(t)))
    return (np.asarray(a, dtype=float) + (np.asarray(b, dtype=float) - np.asarray(a, dtype=float)) * t).tolist() if \
        isinstance(a, (list, tuple, np.ndarray)) else float(np.asarray(a) + (np.asarray(b) - np.asarray(a)) * t)


def clamp(x, lo, hi):
    """限制 x 到 [lo, hi]。"""
    return float(min(max(float(x), float(lo)), float(hi)))


def clamp01(x):
    """限制 x 到 [0, 1]。"""
    return float(min(max(float(x), 0.0), 1.0))


def distance(a, b):
    """两点（向量）欧氏距离。"""
    return float(np.linalg.norm(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)))


def magnitude(v):
    """向量长度。"""
    return float(np.linalg.norm(np.asarray(v, dtype=float)))


def normalize(v):
    """向量归一化（零向量返回原向量）。"""
    a = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(a))
    return a.tolist() if n <= 1e-9 else (a / n).tolist()


def moveTowards(current, target, maxDelta):
    """从 current 朝 target 移动不超过 maxDelta（向量）。"""
    cur = np.asarray(current, dtype=float)
    tar = np.asarray(target, dtype=float)
    d = tar - cur
    n = float(np.linalg.norm(d))
    if n <= maxDelta or n <= 1e-9:
        return tar.tolist()
    return (cur + d / n * maxDelta).tolist()


def sign(x):
    """符号：负数 -1，正数 1，0 返回 0。"""
    x = float(x)
    return -1.0 if x < 0 else (1.0 if x > 0 else 0.0)


# ---- V5.5 世界 ↔ 屏幕坐标 ----

def _viewMatrices():
    from ..renderer.glViewport import GLViewport
    vp = GLViewport.lastRendered
    if vp is None or vp._mvM is None or vp._projM is None:
        return None
    w, h = vp.winfo_width(), vp.winfo_height()
    if w <= 0 or h <= 0:
        return None
    return vp._mvM, vp._projM, [0, 0, w, h]


def worldToScreen(x, y, z):
    """世界坐标 → 屏幕坐标 (sx, sy)（tk 坐标，y 向下，原点左上；视口外返回 None）。"""
    from OpenGL.GLU import gluProject
    m = _viewMatrices()
    if m is None:
        return None
    mv, proj, vp = m
    sx, sy, _ = gluProject(float(x), float(y), float(z), mv, proj, vp)
    return (float(sx), float(vp[3] - sy))


def screenToWorld(sx, sy, depth=0.0):
    """屏幕坐标 → 世界坐标 (x, y, z)。depth 0~1：0=近裁剪面、1=远裁剪面。"""
    from OpenGL.GLU import gluUnProject
    m = _viewMatrices()
    if m is None:
        return None
    mv, proj, vp = m
    wx, wy, wz = gluUnProject(float(sx), float(vp[3] - sy), float(depth), mv, proj, vp)
    return (float(wx), float(wy), float(wz))


# ---- V5.5 其他 ----

def isPlaying():
    """当前是否处于播放模式。"""
    return _CTX.get("scene") is not None


def getSceneName():
    """项目 / 场景名称。"""
    root = _CTX.get("projectRoot")
    if root:
        return Path(root).name
    return "未命名"


def getVersion():
    """引擎版本号。"""
    return "V5.5"


# ---- 日志（显示到游戏视图底部信息栏） ----

_LOG_HANDLER = None


def setLogHandler(fn):
    """注册日志处理器：logMessage(text) 时回调 fn(text)。"""
    global _LOG_HANDLER
    _LOG_HANDLER = fn


def logMessage(text):
    """向游戏视图底部信息栏输出一行文本（调试用）。"""
    if _LOG_HANDLER is not None:
        try:
            _LOG_HANDLER(str(text))
        except Exception:
            pass
    print(f"[脚本日志] {text}")


# ---- 材质 ----

def setMaterialColor(material, r, g, b):
    """修改材质颜色并写回材质文件（渲染立即生效）。r/g/b 取 0~1。"""
    from .materialCache import saveMaterial
    saveMaterial(str(material), _CTX["projectRoot"], (float(r), float(g), float(b)))


def getMaterialColor(material):
    """获取材质颜色 (r, g, b) 0~1。"""
    from .materialCache import loadMaterial
    return list(loadMaterial(str(material), _CTX["projectRoot"]))


def createMaterial(name, r=0.7, g=0.7, b=0.8):
    """创建材质资源（.vmat），返回相对 Resources 的路径。"""
    from .materialCache import createMaterialFile
    return createMaterialFile(_CTX["projectRoot"], name=str(name),
                              color=(float(r), float(g), float(b)))


# ---- 文件（限定项目 Resources 内） ----

def _resPath(rel):
    root = (Path(_CTX["projectRoot"]) / "Resources").resolve()
    p = (root / str(rel)).resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"路径越界：只允许访问项目 Resources 内（{rel}）")
    return p


def createFile(path, content=""):
    """在项目 Resources 下创建文件（自动建父目录），返回相对路径。"""
    p = _resPath(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(str(content), encoding="utf-8")
    return p.relative_to((Path(_CTX["projectRoot"]) / "Resources").resolve()).as_posix()


def writeFile(path, content):
    """写内容到项目 Resources 下的文件（不存在则创建）。"""
    p = _resPath(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(content), encoding="utf-8")
    return p.relative_to((Path(_CTX["projectRoot"]) / "Resources").resolve()).as_posix()


def readFile(path):
    """读取项目 Resources 下文件内容；文件不存在返回 None。"""
    p = _resPath(path)
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_bytes()


def deleteFile(path):
    """删除项目 Resources 下的文件（不存在则忽略）。"""
    p = _resPath(path)
    if p.is_file():
        p.unlink()


def listFiles(path=""):
    """列出项目 Resources 下（相对路径）的文件列表。"""
    root = (Path(_CTX["projectRoot"]) / "Resources").resolve()
    base = _resPath(path)
    if not base.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix()
                  for p in base.rglob("*") if p.is_file())


# ---- 窗口 ----

def openWindow(title="窗口", width=320, height=200):
    """创建脚本窗口，返回窗口 id（closeWindow/setWindowTitle 用）。"""
    master = _CTX.get("master") or _CTX.get("gameWindow")
    if master is None:
        raise RuntimeError("没有可用主窗口")
    win = tk.Toplevel(master)
    win.title(str(title))
    win.geometry(f"{int(width)}x{int(height)}")
    _WINDOW_CTR[0] += 1
    wid = _WINDOW_CTR[0]
    _WINDOWS[wid] = win
    win.protocol("WM_DELETE_WINDOW", lambda w=wid: closeWindow(w))
    return wid


def closeWindow(winId):
    """关闭脚本窗口。"""
    win = _WINDOWS.pop(int(winId), None)
    if win is not None:
        try:
            if win.winfo_exists():
                win.destroy()
        except Exception:
            pass


def closeAllWindows():
    """关闭全部脚本窗口。"""
    for wid in list(_WINDOWS.keys()):
        closeWindow(wid)


def setWindowTitle(winId, title):
    """设置脚本窗口标题。"""
    win = _WINDOWS.get(int(winId))
    if win is not None:
        try:
            win.title(str(title))
        except Exception:
            pass


# ---- 分辨率 ----

def setResolution(width, height):
    """设置游戏视图窗口分辨率。"""
    gw = _CTX.get("gameWindow")
    if gw is not None:
        try:
            if gw.winfo_exists():
                gw.geometry(f"{int(width)}x{int(height)}")
        except Exception:
            pass


def getResolution():
    """获取游戏视图窗口分辨率 (宽, 高)。"""
    gw = _CTX.get("gameWindow")
    if gw is not None:
        try:
            if gw.winfo_exists():
                return (gw.winfo_width(), gw.winfo_height())
        except Exception:
            pass
    return (0, 0)


# ---- 键盘输入 ----

def getCameraForward():
    """当前渲染相机的前向（屏幕深处方向）(x, y, z) 单位向量。

    主视口播放用轨道相机、游戏视图用场景相机，二者都反映你实际看到的画面方向。"""
    return tuple(_CAMERA["fwd"])


def getCameraRight():
    """当前渲染相机的右向 (x, y, z) 单位向量。"""
    return tuple(_CAMERA["right"])


def getCameraPosition():
    """当前渲染相机的位置 (x, y, z)。"""
    return tuple(_CAMERA["eye"])


def isKeyDown(key):
    """按键当前是否按住（如 "w"、"space"、"up"、"return"）。"""
    return str(key).lower() in _INPUT["down"]


def isKeyPressed(key):
    """按键是否本帧刚按下（边缘触发，适合单击/连点判断）。"""
    return str(key).lower() in _INPUT["pressed"]


def isKeyReleased(key):
    """按键是否本帧刚松开。"""
    return str(key).lower() in _INPUT["released"]


def getKeysDown():
    """当前按住的所有键（keysym 小写列表）。"""
    return sorted(_INPUT["down"])


# ---- 鼠标输入 ----

def getMousePosition():
    """鼠标在视口内的位置 (x, y)（像素，左上角原点）。"""
    return tuple(_INPUT["mouse"])


def getMouseDelta():
    """本帧鼠标位移 (dx, dy)（适合 FPS 视角控制）。"""
    return (_INPUT["mouseDelta"][0], _INPUT["mouseDelta"][1])


def isMouseDown(button=1):
    """鼠标按钮当前是否按住（1=左，2=中，3=右）。"""
    return int(button) in _INPUT["mouseDown"]


def isMousePressed(button=1):
    """鼠标按钮是否本帧刚按下。"""
    return int(button) in _INPUT["mousePressed"]


def isMouseReleased(button=1):
    """鼠标按钮是否本帧刚松开。"""
    return int(button) in _INPUT["mouseReleased"]


def getMouseWheel():
    """本帧滚轮增量（正=向上滚，累计多个刻度）。"""
    return _INPUT["wheel"]


# ---- 设备控制（高危） ----

def shutdownComputer():
    """【高危】立即关机（3 秒后）。请先保存所有文件。"""
    import subprocess
    subprocess.Popen(["shutdown", "/s", "/t", "3"])


def rebootComputer():
    """【高危】立即重启电脑（3 秒后）。请先保存所有文件。"""
    import subprocess
    subprocess.Popen(["shutdown", "/r", "/t", "3"])


# 注入给脚本的 API 表
_API = {
    # 自身 / 时间
    "getSelf": getSelf,
    "getDuration": getDuration,
    "getTime": getTime,
    "getRealTime": getRealTime,
    "getFPS": getFPS,
    "getRefreshRate": getRefreshRate,
    "getRegion": getRegion,
    # 场景物体
    "createObject": createObject,
    "destroyObject": destroyObject,
    "getSceneObjects": getSceneObjects,
    "getObjectByName": getObjectByName,
    # V5.5 物体与变换（世界坐标 / 方向 / 父子）
    "getWorldPosition": getWorldPosition,
    "setWorldPosition": setWorldPosition,
    "getForward": getForward,
    "getRight": getRight,
    "getUp": getUp,
    "setParent": setParent,
    "getChildren": getChildren,
    # V5.5 组件（按名称）
    "getComponent": getComponent,
    "addComponent": addComponent,
    "removeComponent": removeComponent,
    # 材质
    "setMaterialColor": setMaterialColor,
    "getMaterialColor": getMaterialColor,
    "createMaterial": createMaterial,
    # 文件（项目 Resources 内）
    "createFile": createFile,
    "writeFile": writeFile,
    "readFile": readFile,
    "deleteFile": deleteFile,
    "listFiles": listFiles,
    # 窗口
    "openWindow": openWindow,
    "closeWindow": closeWindow,
    "closeAllWindows": closeAllWindows,
    "setWindowTitle": setWindowTitle,
    # 分辨率
    "setResolution": setResolution,
    "getResolution": getResolution,
    # 键盘输入
    "isKeyDown": isKeyDown,
    "isKeyPressed": isKeyPressed,
    "isKeyReleased": isKeyReleased,
    "getKeysDown": getKeysDown,
    # 相机（当前实际渲染视角，V5.4.3）
    "getCameraForward": getCameraForward,
    "getCameraRight": getCameraRight,
    "getCameraPosition": getCameraPosition,
    # V5.5 相机控制（场景相机物体）
    "setCameraFov": setCameraFov,
    "getCameraFov": getCameraFov,
    "setCameraPosition": setCameraPosition,
    "setCameraRotation": setCameraRotation,
    # V5.5 渲染
    "setBackgroundColor": setBackgroundColor,
    "getBackgroundColor": getBackgroundColor,
    "setObjectVisible": setObjectVisible,
    "isObjectVisible": isObjectVisible,
    # V5.5 数学辅助
    "lerp": lerp,
    "clamp": clamp,
    "clamp01": clamp01,
    "distance": distance,
    "magnitude": magnitude,
    "normalize": normalize,
    "moveTowards": moveTowards,
    "sign": sign,
    # V5.5 坐标转换
    "worldToScreen": worldToScreen,
    "screenToWorld": screenToWorld,
    # V5.5 调度 / 状态 / 日志
    "invoke": invoke,
    "isPlaying": isPlaying,
    "getSceneName": getSceneName,
    "getVersion": getVersion,
    "logMessage": logMessage,
    # 鼠标输入
    "getMousePosition": getMousePosition,
    "getMouseDelta": getMouseDelta,
    "isMouseDown": isMouseDown,
    "isMousePressed": isMousePressed,
    "isMouseReleased": isMouseReleased,
    "getMouseWheel": getMouseWheel,
    # 设备控制（高危）
    "shutdownComputer": shutdownComputer,
    "rebootComputer": rebootComputer,
}


# =====================================================================
# API 文档（帮助 → 脚本 API 参考）
# =====================================================================

API_DOCS = """Vortex 脚本 API（.vpy）

脚本协议：进入播放调用 start()，之后每帧调用 update()。
在脚本里用 getSelf() / getDuration() 获取当前物体与帧间隔。

【自身 / 时间】
getSelf()          当前脚本所挂载的物体
getDuration()      当前帧间隔（秒），如 0.016
getTime()          播放已运行的秒数
getRealTime()      系统时间戳（Unix 秒）
getFPS()           当前帧率
getRefreshRate()   显示器刷新率（Hz）
getRegion()        系统区域 / 时区

【场景物体】
createObject(name, mesh, material, position, parent)   创建物体（mesh: cube/sphere 或模型路径）
destroyObject(obj)                                     删除物体（含子树）
getSceneObjects()                                      场景全部物体
getObjectByName(name)                                  按名称查找物体
getWorldPosition(obj)        物体世界坐标 (x,y,z)（含父级）
setWorldPosition(obj, xyz)   设置世界坐标（有父级自动换算）
getForward(obj) / getRight(obj) / getUp(obj)   物体自身世界方向（单位向量）
setParent(child, parent)     设置父子（parent=None 解除）
getChildren(obj)             直接子物体列表

【组件】（按名称字符串）
getComponent(obj, "MeshRenderer"/"Camera"/"Light"/"Script"/"Transform")  取组件，返回后可直接改属性
addComponent(obj, "MeshRenderer"/"Light"/"Camera"/"Script")              添加组件（已有不重复）
removeComponent(obj, 名称)                                               移除组件（Transform 不可移除）

【材质】
setMaterialColor(material, r, g, b)   修改材质颜色并写回文件（渲染立即生效，0~1）
getMaterialColor(material)            读取材质颜色 (r, g, b)
createMaterial(name, r, g, b)         创建材质资源，返回相对路径

【文件】（仅限项目 Resources 内，防越界）
createFile(path, content="")   创建文件（自动建父目录）
writeFile(path, content)       写文件（不存在则创建）
readFile(path)                 读文件（不存在返回 None）
deleteFile(path)               删除文件
listFiles(path="")             列出 Resources 下文件（相对路径）

【窗口】
openWindow(title, width, height)   创建脚本窗口，返回窗口 id
closeWindow(winId)                 关闭窗口
closeAllWindows()                  关闭全部脚本窗口
setWindowTitle(winId, title)       设置窗口标题

【分辨率】
setResolution(width, height)   设置游戏视图窗口分辨率
getResolution()                获取游戏视图分辨率

【键盘输入】键名用 keysym 小写：字母 a-z、space、return、up/down/left/right、
shift、control、escape、tab、f1-f12、数字 0-9 等
isKeyDown(key)        按键当前是否按住（如 isKeyDown("w")）
isKeyPressed(key)     本帧刚按下（单击/连点）
isKeyReleased(key)    本帧刚松开
getKeysDown()         当前按住的所有键（列表）

【相机】（当前实际渲染视角：游戏视图=场景相机，主视口=轨道相机）
getCameraForward()    前向单位向量 (x,y,z)——屏幕深处方向
getCameraRight()      右向单位向量 (x,y,z)
getCameraPosition()   相机位置 (x,y,z)
setCameraFov(度) / getCameraFov()           设置场景相机视场角
setCameraPosition(x,y,z) / setCameraRotation(x,y,z)   移动/旋转场景相机

【渲染】
setBackgroundColor(r,g,b)   设置视口背景色（0~1，主视口+游戏视图同时生效）
getBackgroundColor()        获取背景色
setObjectVisible(obj, bool) / isObjectVisible(obj)   物体可见性

【数学辅助】
lerp(a, b, t)       线性插值（t 0~1，支持向量）
clamp(x, lo, hi)    限制范围
clamp01(x)          限制到 0~1
distance(a, b)      两点距离
magnitude(v)        向量长度
normalize(v)        向量归一化
moveTowards(cur, target, maxDelta)   以限速靠近目标
sign(x)             符号（-1/0/1）

【坐标转换】
worldToScreen(x,y,z)    世界→屏幕坐标 (sx,sy)（tk 像素，y 向下；视口外返回 None）
screenToWorld(sx,sy, depth=0)   屏幕→世界（depth 0~1：0=近裁剪面 1=远裁剪面）

【轻量物理】（给物体设置以下属性即自动生效）
obj.velocity = [vx,vy,vz]         每帧自动积分位移（单位/秒）
obj.useGravity = True             施加重力（9.8）
obj.angularVelocity = [x,y,z]     每帧自动积分旋转（度/秒）

【调度 / 状态 / 日志】
invoke(seconds, func, *args)   延迟 seconds 秒后调用 func(*args)
isPlaying()                    是否播放中
getSceneName()                 项目名
getVersion()                   引擎版本
logMessage(text)               向游戏视图底部输出调试信息

【鼠标输入】按钮：1=左，2=中，3=右
getMousePosition()    鼠标在视口内位置 (x, y)
getMouseDelta()       本帧鼠标位移 (dx, dy)
isMouseDown(button)   按钮当前是否按住（默认左键）
isMousePressed(button) 本帧刚按下
isMouseReleased(button) 本帧刚松开
getMouseWheel()       本帧滚轮增量（正=上滚）

【设备控制（高危）】
shutdownComputer()   关机（3 秒后）
rebootComputer()     重启（3 秒后）

物体属性：obj.name / obj.active / obj.parent / obj.children
          obj.transform.position / rotation / scale
          obj.getComponent(组件名)
          obj.velocity / obj.useGravity / obj.angularVelocity（轻量物理）
"""
