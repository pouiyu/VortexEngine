# -*- coding: utf-8 -*-
# Vortex 玩家控制器（第一人称：WASD 移动 + 鼠标视角 + 跳跃）
# 挂载物体：玩家（Rigidbody + SphereCollider + Camera）
# 操作：WASD 移动 / 鼠标 视角 / Space 跳跃

_sens = 0.12          # 鼠标灵敏度（度/像素）
_speed = 6.5          # 移动速度（米/秒）
_jumpSpeed = 6.0      # 跳跃初速度（配合坑墙 3.5 米，玩家跳不进去）
_eyeHeight = 1.75     # 视角高度（物体位置即相机位置，直接设物体高度）


def start():
    obj = getSelf()
    setMouseCapture(True)          # 锁定鼠标到视口中心（FPS 视角）
    setPlayerColliderSize(0.9, 1.8)  # 胶囊近似碰撞体
    obj.transform.position[1] = _eyeHeight
    obj._grounded = False


def update():
    obj = getSelf()
    dt = getDuration()

    # ---- 视角：鼠标位移 → 偏航(绕Y) / 俯仰(绕X) ----
    if isMouseCaptured():
        dx, dy = getMouseDelta()
        r = list(obj.transform.rotation)
        r[1] -= dx * _sens          # 偏航
        r[0] = clamp(r[0] - dy * _sens, -85.0, 85.0)   # 俯仰（限制不翻跟头）
        obj.transform.rotation = r

    # ---- 地面检测（与地板/平台接触） ----
    grounded = False
    for c in getCollidingObjects(obj):
        if c.name in ("地板", "坑底"):
            grounded = True
    obj._grounded = grounded

    # ---- 移动：相对相机前/右方向（水平分量） ----
    fx, fy, fz = getCameraForward()
    rx, ry, rz = getCameraRight()
    mx = 0.0
    mz = 0.0
    if isKeyDown("w"):
        mx += fx; mz += fz
    if isKeyDown("s"):
        mx -= fx; mz -= fz
    if isKeyDown("a"):
        mx -= rx; mz -= rz
    if isKeyDown("d"):
        mx += rx; mz += rz
    ln = (mx * mx + mz * mz) ** 0.5
    if ln > 1e-6:
        mx /= ln; mz /= ln
    _v = getVelocity(obj)
    vy = _v[1]                       # 保留竖直速度（重力下落）
    if isKeyPressed("space") and grounded:
        vy = _jumpSpeed
    setVelocity(obj, mx * _speed, vy, mz * _speed)

    # ---- 掉出世界：重置回起点 ----
    if obj.transform.position[1] < -10.0:
        teleport(obj, 0.0, _eyeHeight, -3.0)
        logMessage("已重置位置")
