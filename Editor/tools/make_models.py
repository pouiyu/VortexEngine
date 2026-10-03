# -*- coding: utf-8 -*-
"""生成引擎内置 .obj 模型（Editor/assets/models/）：cube.obj / sphere.obj。

运行：python Editor/tools/make_models.py
输出：带法线、三角化的 Wavefront OBJ（单位立方体 / 单位球体，中心在原点）。
"""

import math
import sys
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "assets" / "models"


def _writeObj(path, vertices, normals, triangles):
    """写 OBJ：顶点/法线/面（f 用 v//vn 索引，三角化）。

    注意：OBJ 索引从 1 开始，这里把 0 基的三角形索引 +1 转成 1 基，
    否则加载端会把所有面错位引用顶点（历史上已踩过这个坑）。
    """
    lines = ["# Vortex 引擎内置模型", f"# {path.name}"]
    for v in vertices:
        lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
    for n in normals:
        lines.append(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}")
    for (a, b, c) in triangles:
        lines.append(f"f {a + 1}//{a + 1} {b + 1}//{b + 1} {c + 1}//{c + 1}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"生成 {path}（{len(vertices)} 顶点 / {len(triangles)} 三角面）")


def buildCube():
    """单位立方体（边长 2，中心原点）：8 顶点、6 面、12 三角。"""
    verts = []
    normals = []
    tris = []
    # 每个面单独定义（4 顶点 + 面法线），保证法线平滑度=面
    faces = [
        # (中心偏移, 法线, 4 个角)
        ((1, 0, 0), (1, 0, 0), [(1, 1, 1), (1, 1, -1), (1, -1, -1), (1, -1, 1)]),
        ((-1, 0, 0), (-1, 0, 0), [(-1, 1, -1), (-1, 1, 1), (-1, -1, 1), (-1, -1, -1)]),
        ((0, 1, 0), (0, 1, 0), [(1, 1, 1), (-1, 1, 1), (-1, 1, -1), (1, 1, -1)]),
        ((0, -1, 0), (0, -1, 0), [(1, -1, -1), (-1, -1, -1), (-1, -1, 1), (1, -1, 1)]),
        ((0, 0, 1), (0, 0, 1), [(1, 1, 1), (1, -1, 1), (-1, -1, 1), (-1, 1, 1)]),
        ((0, 0, -1), (0, 0, -1), [(-1, 1, -1), (-1, -1, -1), (1, -1, -1), (1, 1, -1)]),
    ]
    base = 0
    for (_c, n, corners) in faces:
        n = tuple(float(x) for x in n)
        for corner in corners:
            verts.append(tuple(float(x) for x in corner))
            normals.append(n)
        a, b, c, d = (base + i for i in range(4))
        tris.append((a, b, c))
        tris.append((a, c, d))
        base += 4
    return verts, normals, tris


def buildSphere(stacks=12, slices=24):
    """单位球体（半径 1，中心原点）：经纬网格，法线=顶点位置。"""
    verts, normals, tris = [], [], []
    for i in range(stacks + 1):
        phi = math.pi * i / stacks                      # 0..π
        y = math.cos(phi)
        r = math.sin(phi)
        for j in range(slices + 1):
            th = 2 * math.pi * j / slices               # 0..2π
            x = r * math.cos(th)
            z = r * math.sin(th)
            verts.append((x, y, z))
            normals.append((x, y, z))
    for i in range(stacks):
        for j in range(slices):
            a = i * (slices + 1) + j
            b = a + slices + 1
            tris.append((a, b, a + 1))
            tris.append((b, b + 1, a + 1))
    return verts, normals, tris


def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name, builder in (("cube.obj", buildCube), ("sphere.obj", buildSphere)):
        verts, normals, tris = builder()
        _writeObj(MODELS_DIR / name, verts, normals, tris)
    return 0


if __name__ == "__main__":
    sys.exit(main())
