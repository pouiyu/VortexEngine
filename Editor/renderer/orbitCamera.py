# -*- coding: utf-8 -*-
"""轨道相机：围绕目标点旋转 / 缩放（Godot / Unreal「内容跟随鼠标」约定）。

约定（与项目历史一致）：拖右→内容右移（phi 减小）、拖下→内容下移（theta 减小）。
"""

import math

import numpy as np


def _deg2rad(d):
    return d * math.pi / 180.0


class OrbitCamera:
    """一切编辑器视角操作都由它驱动。"""

    def __init__(self, distance=7.0, phi=-45.0, theta=25.0, target=(0, 1, 0)):
        self.distance = distance    # 视点到目标距离
        self.phi = phi              # 水平角（度）
        self.theta = theta          # 仰角（度）
        self.target = np.asarray(target, dtype=float)

    def orbit(self, dx, dy):
        """按屏幕像素位移环绕：内容跟随鼠标。"""
        self.phi -= dx * 0.005
        self.theta -= dy * 0.005

    def zoom(self, step):
        """滚轮缩放，step 为滚轮增量（±120 的倍数）。"""
        self.distance *= 0.9 ** (step / 120.0)
        self.distance = max(0.8, min(self.distance, 200.0))

    def eye(self):
        """相机世界坐标。"""
        ph, th = _deg2rad(self.phi), _deg2rad(self.theta)
        offset = np.array([
            math.cos(th) * math.sin(ph),
            math.sin(th),
            math.cos(th) * math.cos(ph),
        ])
        return self.target + offset * self.distance

    def lookAtArgs(self):
        """gluLookAt 用的 (eye, center, up)。"""
        return tuple(self.eye()), tuple(self.target), (0, 1, 0)