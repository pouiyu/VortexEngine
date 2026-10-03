# -*- coding: utf-8 -*-
"""Wavefront .obj 加载器：解析顶点 / 法线 / 三角面。

支持格式：
- v x y z（顶点）
- vn x y z（法线）
- f v/vt/vn、f v//vn、f v/vt、f v（自动三角化扇形，忽略纹理坐标）

输出：MeshData(vertices: (N,3), normals: (N,3), indices: (M,))。
OBJ 的面直接引用顶点索引，加载时按面展开成 GL_TRIANGLES 可直接使用的
共享索引数组；顶点/法线按需重复，保证每个三角面顶点都有法线。
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class MeshData:
    """已三角化的网格数据（供 glDrawElements 使用）。"""

    vertices: np.ndarray          # (N,3) float32
    normals: np.ndarray           # (N,3) float32
    indices: np.ndarray           # (M,) uint32，M 为 3 的倍数
    name: str = ""

    def edges(self):
        """去重后的边列表（供选中描边复用）。"""
        edgeSet = set()
        idx = self.indices
        for i in range(0, len(idx), 3):
            for a, b in ((idx[i], idx[i + 1]), (idx[i + 1], idx[i + 2]), (idx[i + 2], idx[i])):
                edgeSet.add((min(a, b), max(a, b)))
        return [(self.vertices[a], self.vertices[b]) for a, b in edgeSet]


def _faceNormal(pts):
    """三个世界顶点 → 单位面法线（退化时回退 +Y）。"""
    u = pts[1] - pts[0]
    v = pts[2] - pts[0]
    n = np.cross(u, v)
    length = np.linalg.norm(n)
    if length < 1e-9:
        return np.array([0.0, 1.0, 0.0])
    return n / length


def loadObjFile(path):
    """从 .obj 文件加载网格；文件缺失/格式损坏抛异常（由调用方处理）。"""
    positions, normals = [], []
    faces = []          # 每面 (顶点索引列表(1基), 法线索引列表(1基)或None)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            tag = parts[0]
            if tag == "v":
                positions.append([float(x) for x in parts[1:4]])
            elif tag == "vn":
                normals.append([float(x) for x in parts[1:4]])
            elif tag == "f":
                vIdx, nIdx = [], None
                for tok in parts[1:]:
                    seg = tok.split("/")
                    vIdx.append(int(seg[0]))
                    if len(seg) > 2 and seg[2]:
                        nIdx = nIdx if nIdx is not None else []
                        nIdx.append(int(seg[2]))
                faces.append((vIdx, nIdx))

    if not positions:
        raise ValueError(f"{path}: 无顶点数据")
    pos = np.asarray(positions, dtype=float)
    nrm = np.asarray(normals, dtype=float) if normals else None

    verts, norms, indices = [], [], []
    for (vIdx, nIdx) in faces:
        triCount = len(vIdx) - 2
        if triCount < 1:
            continue
        for t in range(triCount):
            tri = [vIdx[0], vIdx[t + 1], vIdx[t + 2]]
            triN = [nIdx[0], nIdx[t + 1], nIdx[t + 2]] if (nIdx is not None and len(nIdx) >= len(vIdx)) else None
            pts = []
            for vi in tri:
                oi = vi - 1 if vi > 0 else vi            # OBJ 索引从 1 开始
                if not (0 <= oi < len(pos)):
                    raise ValueError(f"{path}: 顶点索引越界 {vi}")
                pts.append(pos[oi])
            # 面法线（顶点法线缺失/越界时兜底；整面三个顶点收集完再算）
            faceN = _faceNormal(pts)
            for k, vi in enumerate(tri):
                oi = vi - 1 if vi > 0 else vi
                verts.append(pos[oi])
                if triN is not None and 0 <= triN[k] - 1 < len(nrm):
                    norms.append(nrm[triN[k] - 1])
                else:
                    norms.append(faceN)
                indices.append(len(verts) - 1)
    if not verts:
        raise ValueError(f"{path}: 无三角面")

    return MeshData(
        vertices=np.asarray(verts, dtype=np.float32),
        normals=np.asarray(norms, dtype=np.float32),
        indices=np.asarray(indices, dtype=np.uint32),
        name=Path(path).stem,
    )
