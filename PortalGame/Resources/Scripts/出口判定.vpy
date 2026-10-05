# -*- coding: utf-8 -*-
# Vortex 出口判定：玩家踩上出口平台 → 通关提示
# 挂载物体：出口（绿色平台，Rigidbody mass=0 + BoxCollider + MeshRenderer）

_started = False


def start():
    global _started
    _started = False


def update():
    global _started
    obj = getSelf()
    for c in getCollidingObjects(obj):
        if c.name == "玩家":
            if not _started:
                _started = True
                logMessage("🎉 通关！你完成了 Vortex 传送门！")
            return
