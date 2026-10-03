# -*- coding: utf-8 -*-
"""最小场景数据层（V2 骨架版）。

V2 只做「编辑器骨架」，对象系统在 V3 完善。
这里提供最小可用的 GameObject / Transform / Scene：
- Transform：位置 / 旋转 / 缩放（numpy 向量）
- GameObject：名称 + Transform + 激活 + 子节点（为 V3 预留父子层级）
- Scene：物体列表 + 根节点

演示场景：地面网格 + 一个立方体，用于验证编辑器的层级面板与 OpenGL 视口。
"""

import math

import numpy as np


class Transform:
    """物体变换：位置 / 旋转（度，绕 X/Y/Z）/ 缩放。"""

    def __init__(self, position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1)):
        self.position = np.asarray(position, dtype=float)
        self.rotation = np.asarray(rotation, dtype=float)
        self.scale = np.asarray(scale, dtype=float)


class GameObject:
    """物体的最小形态（Unity 概念里的空物体 + Transform）。"""

    def __init__(self, name="物体", transform=None, active=True, mesh=None):
        self.name = name
        self.transform = transform or Transform()
        self.active = active
        self.mesh = mesh          # 演示用：None / "cube" / "grid"
        self.children = []        # 子节点列表（V3 启用父子层级）

    def addChild(self, child):
        self.children.append(child)
        return child


class Scene:
    """场景：根节点 + 全部物体（扁平列表，V3 起用 uuid 引用）。"""

    def __init__(self):
        self.objects = []         # 全部物体（含子树）

    def addObject(self, go):
        self.objects.append(go)
        return go


def createDemoScene():
    """生成演示场景：地面网格 + 立方体，用于验证视口与层级面板。"""
    scene = Scene()
    grid = GameObject(name="地面网格", mesh="grid")
    cube = GameObject(
        name="立方体",
        transform=Transform(position=(0, 1, 0)),
        mesh="cube",
    )
    scene.addObject(grid)
    scene.addObject(cube)
    return scene