# -*- coding: utf-8 -*-
"""场景射线检测（V5.7）：CPU 射线-三角形求交。

传送门枪、拾取、机关都需要"朝某个方向打到什么"。
固定管线没有现成 raycast，这里直接对 MeshRenderer 的网格做
Möller–Trumbore 三角形求交（物体逆变换到本地空间，命中后把
点/法线变换回世界空间）。
"""

import numpy as np

from .scene import MeshRenderer, worldMatrix


def _rayTri(orig, dir_, v0, v1, v2):
    """Möller–Trumbore：射线(orig, dir_单位)与三角形 v0/v1/v2 求交。
    返回 t（>0）或 None。"""
    e1 = v1 - v0
    e2 = v2 - v0
    p = np.cross(dir_, e2)
    det = float(e1 @ p)
    if abs(det) < 1e-12:
        return None
    inv = 1.0 / det
    s = orig - v0
    u = float(s @ p) * inv
    if u < 0.0 or u > 1.0:
        return None
    q = np.cross(s, e1)
    v = float(dir_ @ q) * inv
    if v < 0.0 or u + v > 1.0:
        return None
    t = float(e2 @ q) * inv
    if t < 1e-7:
        return None
    return t


def raycastScene(scene, origin, direction, maxDist=1000.0, ignore=None,
                 projectRoot=None):
    """从 origin 沿 direction（任意长度，内部归一化）发射射线。

    遍历场景里所有带 MeshRenderer 的激活物体（ignore 可排除某个物体），
    返回最近命中：dict {obj, point(世界), normal(世界单位), distance}
    或 None（没命中）。"""
    origin = np.asarray(origin, dtype=float)
    d = np.asarray(direction, dtype=float)
    ln = float(np.linalg.norm(d))
    if ln < 1e-9:
        return None
    d = d / ln
    if scene is None:
        return None
    best = None
    for go in scene.objects:
        if not go.active or go is ignore:
            continue
        mr = go.getComponent(MeshRenderer)
        if mr is None:
            continue
        try:
            from . import meshCache
            data = meshCache.getMesh(mr.mesh, projectRoot)
        except Exception:
            data = None
        if data is None or data.vertices is None or data.indices is None:
            continue
        m = worldMatrix(go)
        try:
            mInv = np.linalg.inv(m)
        except Exception:
            continue
        # 射线变换到物体本地空间
        lo = mInv @ np.array([origin[0], origin[1], origin[2], 1.0])
        ld = mInv[:3, :3] @ d
        lln = float(np.linalg.norm(ld))
        if lln < 1e-9:
            continue
        ld = ld / lln
        verts = np.asarray(data.vertices, dtype=float)
        idx = data.indices
        tHit = None
        for i in range(0, len(idx) - 2, 3):
            a, b, c = int(idx[i]), int(idx[i + 1]), int(idx[i + 2])
            t = _rayTri(lo[:3], ld, verts[a], verts[b], verts[c])
            if t is not None and (tHit is None or t < tHit):
                tHit = t
        if tHit is None:
            continue
        # 变换回世界空间
        lp = lo[:3] + ld * tHit
        wp = m @ np.array([lp[0], lp[1], lp[2], 1.0])
        # 命中三角形法线（本地）→ 世界
        triNorm = np.cross(verts[b] - verts[a], verts[c] - verts[a])
        tn = float(np.linalg.norm(triNorm))
        if tn < 1e-12:
            triNorm = np.array([0.0, 1.0, 0.0])
        else:
            triNorm = triNorm / tn
        R = m[:3, :3]
        wNorm = R @ triNorm
        nn = float(np.linalg.norm(wNorm))
        if nn > 1e-9:
            wNorm = wNorm / nn
        dist = float(np.linalg.norm(wp[:3] - origin))
        if dist > maxDist:
            continue
        if best is None or dist < best["distance"]:
            best = {
                "obj": go,
                "point": wp[:3],
                "normal": wNorm,
                "distance": dist,
            }
    return best
