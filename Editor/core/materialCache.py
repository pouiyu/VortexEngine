# -*- coding: utf-8 -*-
"""材质资源系统：MeshRenderer.material 键 → 颜色（.vmat 资源）。

.vmat 是 Vortex 材质文件（JSON）：
    {"color": [r, g, b], "name": "可选"}
键约定：
- "default"：引擎内置默认材质（Editor/assets/materials/default.vmat）
- 其他字符串：相对项目 Resources 的路径（如 "Materials/red.vmat"），
  或直接可用的绝对/相对路径
- None：无材质 → 渲染中性灰（由调用方决定）

内置材质目录同时作为「项目里创建材质」的默认内容来源。
"""

import json
from pathlib import Path

_BUILTIN_DIR = Path(__file__).resolve().parent.parent / "assets" / "materials"
BUILTIN_MATERIALS = ("default",)

_cache = {}          # 绝对路径 → 颜色元组
_failed = set()      # 已确认缺失的路径

DEFAULT_COLOR = (0.60, 0.60, 0.60)   # 无材质时的中性灰


def resolveMaterialPath(material, projectRoot=None):
    """把材质键解析成候选文件路径（返回第一个存在的路径，找不到返回 None）。"""
    if not material:
        return None
    if material in BUILTIN_MATERIALS:
        p = _BUILTIN_DIR / f"{material}.vmat"
        return p if p.is_file() else None
    candidates = []
    if projectRoot:
        candidates.append(Path(projectRoot) / "Resources" / material)
        candidates.append(Path(projectRoot) / material)
    candidates.append(Path(material))
    for p in candidates:
        if p.is_file():
            return p
    return None


def loadMaterial(material, projectRoot=None):
    """按键取颜色 (r,g,b) 0~1；找不到返回 DEFAULT_COLOR（渲染端不抛异常）。"""
    if not material:
        return DEFAULT_COLOR
    path = resolveMaterialPath(material, projectRoot)
    if path is None:
        return DEFAULT_COLOR
    key = str(path)
    if key in _cache:
        return _cache[key]
    if key in _failed:
        return DEFAULT_COLOR
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        color = data.get("color")
        if not color or len(color) < 3:
            raise ValueError(f"{path.name}: color 字段缺失")
        color = tuple(float(c) for c in color[:3])
    except (OSError, ValueError, json.JSONDecodeError):
        _failed.add(key)
        return DEFAULT_COLOR
    _cache[key] = color
    return color


def createMaterialFile(projectRoot, name="新材质", color=(0.70, 0.70, 0.80),
                       subdir=""):
    """在项目 Resources 下创建 .vmat，返回相对资源路径；失败抛 OSError。

    subdir 为相对 Resources 的目录（如 "MyFolder"），为空则直接放 Resources 根。
    目录必须已存在（由资源浏览器负责创建/定位），不再自动建子文件夹。"""
    resDir = Path(projectRoot) / "Resources"
    targetDir = resDir / subdir if subdir else resDir
    path = targetDir / f"{name}.vmat"
    n = 1
    while path.exists():
        path = targetDir / f"{name}{n}.vmat"
        n += 1
    path.write_text(json.dumps({"name": path.stem, "color": list(color)},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path.relative_to(resDir).as_posix()


def listProjectMaterials(projectRoot):
    """列出项目 Resources 下所有 .vmat（相对路径，供资源选择器/网格下拉复用）。"""
    if not projectRoot:
        return []
    res = Path(projectRoot) / "Resources"
    if not res.is_dir():
        return []
    return sorted(p.relative_to(res).as_posix()
                  for p in res.rglob("*.vmat") if p.is_file())


def saveMaterial(material, projectRoot, color):
    """写回材质文件颜色（资源浏览器编辑后保存）；失败抛 OSError。"""
    path = resolveMaterialPath(material, projectRoot)
    if path is None:
        raise OSError(f"材质文件不存在：{material}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["color"] = [float(c) for c in color[:3]]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _cache[str(path)] = tuple(float(c) for c in color[:3])
    return path
