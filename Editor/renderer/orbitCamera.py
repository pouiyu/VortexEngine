# -*- coding: utf-8 -*-
"""轨道相机：环绕 / 平移 / 浏览(fly) / 缩放。

交互约定（2026-10-03 用户确认）：
- 左键拖拽          ：环绕（拖右→内容右移；拖上→内容上移，上下方向与旧版相反）
- Shift+左键拖拽    ：平移视野
- 中键按住          ：浏览模式（隐藏光标，WASD/QE 移动，拖动转头）
- 滚轮              ：缩放
- orbitSpeed        ：用户自定义旋转速度倍率
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
        self.theta = theta          # 仰角（度），增大=相机抬高、内容下移
        self.target = np.asarray(target, dtype=float)
        self.orbitSpeed = 1.0       # 旋转速度倍率（用户可调）
        self.panSensitivity = 1.0   # 平移灵敏度（用户可调）
        self.moveSpeed = 1.0        # fly 移动速度倍率（用户可调）

    # ---- 交互 ----
    def orbit(self, dx, dy):
        """按屏幕像素位移环绕：水平内容跟随鼠标；上下与旧版相反（拖上→内容上移）。"""
        s = 0.005 * self.orbitSpeed
        self.phi -= dx * s
        self.theta += dy * s

    def pan(self, dx, dy):
        """平移视野：内容跟随鼠标（拖右→内容右移、拖上→内容上移，与环绕一致）。"""
        _, right, up = self.axes()
        k = 0.0012 * self.distance * self.panSensitivity
        self.target = self.target - right * dx * k + up * dy * k

    def zoom(self, step):
        """滚轮缩放，step 为滚轮增量（±120 的倍数）。"""
        self.distance *= 0.9 ** (step / 120.0)
        self.distance = max(0.8, min(self.distance, 200.0))

    # ---- 方向轴 ----
    def axes(self):
        """返回相机自身的 (forward, right, up) 单位向量。"""
        ph, th = _deg2rad(self.phi), _deg2rad(self.theta)
        eye = self.eye()
        fwd = self.target - eye
        length = max(np.linalg.norm(fwd), 1e-9)
        forward = fwd / length
        right = np.cross(forward, np.array([0.0, 1.0, 0.0]))
        if np.linalg.norm(right) < 1e-6:   # 极视角（正上/正下）退化
            right = np.array([1.0, 0.0, 0.0])
        right = right / np.linalg.norm(right)
        up = np.cross(right, forward)
        return forward, right, up

    def move(self, forwardAmt, rightAmt, upAmt, dt=1.0):
        """fly 模式平移 target（沿相机自身方向轴）；速度恒定 3 单位/秒×dt，避免帧率抖动。"""
        forward, right, up = self.axes()
        k = 3.0 * self.moveSpeed * dt
        self.target = self.target + forward * forwardAmt * k \
            + right * rightAmt * k + up * upAmt * k

    # ---- 视图数据 ----
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