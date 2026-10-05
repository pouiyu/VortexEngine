# -*- coding: utf-8 -*-
# Vortex 传送逻辑：检测玩家 / 方块穿过传送门平面 → 传送到另一门出口
# 挂载物体：传送管理器（空物体）。
# 门环物体命名：传送门·橙 / 传送门·蓝；出口法线 = -(getForward(环))。

_TARGETS = ("玩家", "方块")   # 会被传送的物体名


def _doorNormal(go):
    """门出口方向（门面朝外法线）：本地+Z 指向墙面法线 → 法线 = -getForward。"""
    fx, fy, fz = getForward(go)
    return (-fx, -fy, -fz)


def _side(pos, doorPos, n):
    """点相对门平面的符号（正 = 门外侧，即玩家进入的那一侧）。"""
    return ((pos[0] - doorPos[0]) * n[0] +
            (pos[1] - doorPos[1]) * n[1] +
            (pos[2] - doorPos[2]) * n[2])


def _check(go, src, srcN, dst, dstN):
    pos = getWorldPosition(go)
    prev = getattr(go, "_prevPos", None)
    if prev is None:
        go._prevPos = pos
        return
    s0 = _side(prev, src.transform.position, srcN)
    s1 = _side(pos, src.transform.position, srcN)
    if s0 > 0.0 and s1 <= 0.0:   # 从门外侧穿入门内 → 传送
        dp = dst.transform.position
        out = [dp[0] + dstN[0] * 1.2,
               dp[1] + dstN[1] * 1.2,
               dp[2] + dstN[2] * 1.2]
        teleport(go, out[0], out[1], out[2])
        # 速度映射：沿目标门法线方向，保持原速率（Portal 式）
        v = getVelocity(go)
        vm = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5
        if vm > 0.05:
            setVelocity(go, dstN[0] * vm, dstN[1] * vm, dstN[2] * vm)
        else:
            setVelocity(go, 0.0, 0.0, 0.0)
        go._prevPos = out
        if go.name == "玩家":
            logMessage("传送！")
        return
    go._prevPos = pos


def update():
    o = getObjectByName("传送门·橙")
    b = getObjectByName("传送门·蓝")
    if o is None or b is None:
        return
    oN = _doorNormal(o)
    bN = _doorNormal(b)
    for name in _TARGETS:
        go = getObjectByName(name)
        if go is None:
            continue
        _check(go, o, oN, b, bN)     # 橙 → 蓝
        _check(go, b, bN, o, oN)     # 蓝 → 橙
