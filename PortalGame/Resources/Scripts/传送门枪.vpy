# -*- coding: utf-8 -*-
# Vortex 传送门枪（橙/蓝传送门放置）
# 挂载物体：玩家。左键放橙色门，右键放蓝色门；再点同色则移动旧门。
# 门环 + 门盘两个物体；传送逻辑脚本负责"穿过即传送"。

_RING = "Models/torus.obj"
_DISC = "Models/disc.obj"
_MAXDIST = 100.0


def start():
    obj = getSelf()
    obj._door = {"orange": None, "blue": None}   # 每色：(环物体, 盘物体)


def _rotFromZ(nx, ny, nz):
    """求欧拉角 [rx, ry, 0]（ZYX 顺序），使物体本地 +Z 轴指向 (nx,ny,nz)。"""
    l = (nx * nx + ny * ny + nz * nz) ** 0.5
    if l < 1e-9:
        return [0.0, 0.0, 0.0]
    nx, ny, nz = nx / l, ny / l, nz / l
    import math
    rx = math.degrees(math.asin(max(-1.0, min(1.0, -ny))))
    cx = math.cos(math.radians(rx))
    if abs(cx) < 1e-6:
        ry = 0.0
    else:
        ry = math.degrees(math.atan2(nx, nz))
    return [rx, ry, 0.0]


def _place(obj, colorKey, material):
    camPos = getCameraPosition()
    fwd = getCameraForward()
    hit = raycast(camPos[0], camPos[1], camPos[2],
                  fwd[0], fwd[1], fwd[2], _MAXDIST, ignore=obj)
    if hit is None:
        return False
    target = hit["obj"]
    if target is obj:
        return False
    p = hit["point"]
    n = hit["normal"]
    # 门中心稍微贴墙外 0.02，法线指向墙外（玩家从外侧进入）
    px, py, pz = p[0] + n[0] * 0.02, p[1] + n[1] * 0.02, p[2] + n[2] * 0.02
    rot = _rotFromZ(n[0], n[1], n[2])
    # 删旧门
    old = obj._door[colorKey]
    if old is not None:
        ring, disc = old
        destroyObject(ring)
        destroyObject(disc)
    # 建新门：环 + 盘
    ring = createObject(name=("传送门·" + ("橙" if colorKey == "orange" else "蓝")),
                        mesh=_RING, material=material, position=(px, py, pz))
    ring.transform.rotation = rot
    getComponent(ring, "MeshRenderer").doubleSided = True
    disc = createObject(name=("门盘·" + ("橙" if colorKey == "orange" else "蓝")),
                        mesh=_DISC, material=material, position=(px, py, pz))
    disc.transform.rotation = rot
    getComponent(disc, "MeshRenderer").doubleSided = True
    # 门盘稍微贴墙（环内侧）
    disc.transform.position = [px + n[0] * 0.015, py + n[1] * 0.015, pz + n[2] * 0.015]
    obj._door[colorKey] = (ring, disc)
    return True


def update():
    obj = getSelf()
    if isMousePressed(1):
        _place(obj, "orange", "Materials/橙色门.vmat")
    if isMousePressed(3):
        _place(obj, "blue", "Materials/蓝色门.vmat")
