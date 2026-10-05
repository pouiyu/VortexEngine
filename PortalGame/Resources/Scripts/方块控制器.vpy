# -*- coding: utf-8 -*-
# Vortex 方块控制器：按 E 抓取 / 放下（抓取时变运动学跟随相机前方）
# 挂载物体：方块（Rigidbody + BoxCollider + MeshRenderer）

_HELD_DIST = 2.6   # 抓取后距离相机
_PICK_DIST = 4.5   # 抓取射线长度


def start():
    obj = getSelf()
    obj._held = False


def update():
    obj = getSelf()
    if isKeyPressed("e"):
        if not obj._held:
            camPos = getCameraPosition()
            fwd = getCameraForward()
            hit = raycast(camPos[0], camPos[1], camPos[2],
                          fwd[0], fwd[1], fwd[2], _PICK_DIST)
            if hit is not None and hit["obj"] is obj:
                obj._held = True
                getComponent(obj, "Rigidbody").isKinematic = True
                logMessage("抓取了方块")
        else:
            obj._held = False
            getComponent(obj, "Rigidbody").isKinematic = False
            logMessage("放下了方块")
    if obj._held:
        camPos = getCameraPosition()
        fwd = getCameraForward()
        t = [camPos[0] + fwd[0] * _HELD_DIST,
             camPos[1] + fwd[1] * _HELD_DIST,
             camPos[2] + fwd[2] * _HELD_DIST]
        teleport(obj, t[0], t[1], t[2])
