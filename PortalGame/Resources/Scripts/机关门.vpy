# -*- coding: utf-8 -*-
# Vortex 机关门：按钮被玩家或方块接触 → 出口门板升起 / 降下
# 挂载物体：按钮（Rigidbody mass=0 + BoxCollider + MeshRenderer）

_DOOR_NAME = "出口门板"
_OPEN_Y = 5.4        # 门板升起隐藏到天花板内
_CLOSE_Y = 1.6       # 门板关闭位置（堵住门洞）
_SPEED = 4.0         # 门板升降速度（米/秒）


def start():
    obj = getSelf()
    obj._open = False


def update():
    obj = getSelf()
    dt = getDuration()
    pressed = False
    for c in getCollidingObjects(obj):
        if c.name in ("玩家", "方块"):
            pressed = True
            break
    if pressed and not obj._open:
        obj._open = True
        logMessage("按钮按下：出口门开启！")
    elif not pressed and obj._open:
        obj._open = False
        logMessage("按钮松开：出口门关闭")
    door = getObjectByName(_DOOR_NAME)
    if door is None:
        return
    targetY = _OPEN_Y if obj._open else _CLOSE_Y
    y = door.transform.position[1]
    if abs(y - targetY) > 0.001:
        step = _SPEED * dt
        y = y + max(-step, min(step, targetY - y))
        door.transform.position[1] = y
