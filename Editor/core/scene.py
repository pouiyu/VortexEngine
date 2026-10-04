# -*- coding: utf-8 -*-
"""场景数据层（V5：Unity 式 GameObject + 组件体系）。

- Component：组件基类（挂到物体上，默认每个物体挂一个 Transform）
- Transform：位置 / 旋转（度，绕 X/Y/Z）/ 缩放（物体的第一个组件，不可移除）
- MeshRenderer：网格渲染组件（mesh 键 + 材质键，颜色由材质决定）
- Material：颜色等外观由材质资源（.vmat）配置，MeshRenderer 只引用
- Light：光照组件（方向光 / 点光源，类型在检查器里切换）
- Camera：摄像机组件（fov / near / far，视口内以视锥 Gizmo 显示朝向）
- Script：脚本组件（引用项目 .vpy 脚本，播放模式时 start/update 每帧执行）
- GameObject：名称 + uuid + 激活 + 组件列表 + 父子层级
- Scene：全部物体（扁平列表，父子靠 parent 引用）+ 增删/设父/取世界变换

世界变换约定：本地矩阵 = T·R·S（先缩放→绕自身旋转→平移，旧版已确认），
旋转欧拉顺序 ZYX（R = Rz·Ry·Rx）；世界矩阵 = 根到自身的本地矩阵连乘。
"""

import math
import uuid

import numpy as np


# ---- 组件 ----
class Component:
    """组件基类：挂到 GameObject 上，携带一块数据/行为。"""

    TYPE = "Component"

    def __init__(self):
        self.gameObject = None   # 所属物体（挂载时设置）


class Transform(Component):
    """位置 / 旋转（度，欧拉 ZYX）/ 缩放。每个物体默认持有。"""

    TYPE = "Transform"

    def __init__(self, position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1)):
        super().__init__()
        self.position = np.asarray(position, dtype=float)
        self.rotation = np.asarray(rotation, dtype=float)
        self.scale = np.asarray(scale, dtype=float)


class MeshRenderer(Component):
    """网格渲染组件：决定物体画什么几何，颜色来自材质资源。

    mesh 取值：
    - "cube" / "sphere"：引擎内置 .obj 模型
    - 资源路径（相对项目 Resources，如 "Models/rock.obj"）：导入的自定义模型
    - None：空物体
    material 取值：
    - "default"：引擎内置默认材质（Editor/assets/materials/default.vmat）
    - 资源路径（相对项目 Resources，如 "Materials/red.vmat"）
    - None：无材质（渲染中性灰）
    """

    TYPE = "MeshRenderer"

    def __init__(self, mesh=None, material="default"):
        super().__init__()
        self.mesh = mesh            # "cube" / "sphere" / 资源路径 / None
        self.material = material    # 材质资源键（"default" / 相对路径 / None）


class Light(Component):
    """光照组件：方向光 / 点光源（颜色 + 强度）。"""

    TYPE = "Light"

    def __init__(self, lightType="directional", color=(1.0, 1.0, 1.0), intensity=1.0):
        super().__init__()
        self.lightType = lightType          # "directional" / "point"
        self.color = list(color)            # RGB 0~1
        self.intensity = float(intensity)   # 倍率


class Camera(Component):
    """摄像机组件：视锥参数（编辑器视口仍用轨道相机，组件供运行时/导出用）。"""

    TYPE = "Camera"

    def __init__(self, fov=60.0, near=0.1, far=1000.0):
        super().__init__()
        self.fov = float(fov)       # 垂直视场角（度）
        self.near = float(near)     # 近裁剪面
        self.far = float(far)       # 远裁剪面


class Script(Component):
    """脚本组件：播放模式时执行项目里的 .vpy 脚本。

    script 取值：
    - 相对项目 Resources 的 .vpy 路径（如 "Scripts/rotate.vpy"）
    - None：未选择脚本（播放时不执行）
    脚本协议见 Editor/core/runtime.py。
    """

    TYPE = "Script"

    def __init__(self, script=None):
        super().__init__()
        self.script = script


# ---- 物体 ----
class GameObject:
    """Unity 概念里的 GameObject：Transform + 组件 + 父子层级。"""

    def __init__(self, name="物体", active=True):
        self.uuid = uuid.uuid4().hex
        self.name = name
        self.active = active
        self.components = [Transform()]   # 默认挂 Transform 组件
        self.components[0].gameObject = self
        self.parent = None
        self.children = []

    # ---- 组件 ----
    @property
    def transform(self):
        """便捷属性：返回 Transform 组件（每个物体必有）。"""
        for c in self.components:
            if isinstance(c, Transform):
                return c
        return None

    def getComponent(self, cls):
        """按类型取第一个组件，没有返回 None。"""
        for c in self.components:
            if isinstance(c, cls):
                return c
        return None

    def addComponent(self, comp):
        """挂载组件（自动设置所属物体）。"""
        comp.gameObject = self
        self.components.append(comp)
        return comp

    def removeComponent(self, comp):
        """卸载组件；Transform 为默认组件不可移除。"""
        if isinstance(comp, Transform) or comp not in self.components:
            return False
        comp.gameObject = None
        self.components.remove(comp)
        return True

    # ---- 层级 ----
    def addChild(self, child):
        """把 child 设为自己的子物体（child 从旧父脱离）。"""
        if child.parent is not None and child in child.parent.children:
            child.parent.children.remove(child)
        child.parent = self
        if child not in self.children:
            self.children.append(child)
        return child

    def removeChild(self, child):
        """解除子物体关系（child 变回根物体）。"""
        if child in self.children:
            self.children.remove(child)
            child.parent = None

    def isDescendantOf(self, other):
        """是否位于 other 的子树中。"""
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False


# ---- 场景 ----
class Scene:
    """场景：全部物体（扁平列表，父子靠 parent 引用，V3 起用 uuid 引用）。"""

    def __init__(self):
        self.objects = []

    def addObject(self, go):
        """登记物体（不改变父子关系）。"""
        if go not in self.objects:
            self.objects.append(go)
        return go

    def removeObject(self, go):
        """删除物体（连带其子树一起从场景移除）。"""
        if go in self.objects:
            self.objects.remove(go)
        if go.parent is not None and go in go.parent.children:
            go.parent.children.remove(go)
        for child in list(go.children):
            self.removeObject(child)

    def setParent(self, child, parent):
        """把 child 设为 parent 的子物体；parent 传 None 表示脱离父级。

        拒绝两种情况：parent 就是 child 自己；parent 位于 child 的子树中
        （把祖先拖进自己的后代会造成父子环）。"""
        if parent is not None and (parent is child or parent.isDescendantOf(child)):
            return child      # 拒绝成环：parent 是 child 的后代/自身
        if child.parent is not None and child in child.parent.children:
            child.parent.children.remove(child)
        child.parent = parent
        if parent is not None and child not in parent.children:
            parent.children.append(child)
        return child

    def rootObjects(self):
        """所有根物体（无父级，用于层级树与保存）。"""
        return [o for o in self.objects if o.parent is None]

    def findByUuid(self, uid):
        """按 uuid 查找物体。"""
        for o in self.objects:
            if o.uuid == uid:
                return o
        return None


# ---- 变换矩阵 ----
def _rotationMatrix(rotDeg):
    """欧拉角（度，ZYX 顺序）→ 3x3 旋转矩阵（R = Rz·Ry·Rx）。"""
    rx, ry, rz = np.radians(rotDeg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rxM = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ryM = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rzM = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rzM @ ryM @ rxM


def localMatrix(t):
    """Transform → 4x4 本地矩阵（T·R·S）。"""
    s4 = np.diag([*t.scale, 1.0])
    r4 = np.eye(4)
    r4[:3, :3] = _rotationMatrix(t.rotation)
    t4 = np.eye(4)
    t4[:3, 3] = t.position
    return t4 @ r4 @ s4


def worldMatrix(go):
    """物体 → 4x4 世界矩阵（根到自身的本地矩阵连乘）。"""
    chain = []
    node = go
    while node is not None:
        chain.append(node.transform)
        node = node.parent
    m = np.eye(4)
    for t in reversed(chain):   # 从根到自身
        m = m @ localMatrix(t)
    return m


# ---- 演示场景 ----
def createDemoScene():
    """生成演示场景：一个立方体（默认材质）+ 一个方向光。"""
    scene = Scene()
    cube = GameObject(name="立方体")
    cube.addComponent(MeshRenderer(mesh="cube", material="default"))
    cube.transform.position = np.array([0.0, 1.0, 0.0])
    scene.addObject(cube)
    sun = GameObject(name="方向光")
    sun.addComponent(Light(lightType="directional", color=(1.0, 1.0, 0.95), intensity=1.0))
    sun.transform.rotation = np.array([45.0, -30.0, 0.0])
    scene.addObject(sun)
    return scene
