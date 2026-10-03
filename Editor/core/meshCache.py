# -*- coding: utf-8 -*-
"""网格资源缓存：把 MeshRenderer.mesh 的键解析为 MeshData 并缓存。

键约定：
- "cube" / "sphere"：引擎内置模型（Editor/assets/models/*.obj）
- 其他字符串：相对项目 Resources 的资源路径（如 "Models/rock.obj"），
  或直接可用的绝对/相对路径
- None：空物体（返回 None）

解析规则（按优先级）：
1. 内置名 → Editor/assets/models/<name>.obj
2. 项目资源 → <projectRoot>/Resources/<key>（key 可能是 Models/xxx.obj 或 xxx.obj）
3. 原样路径 → Path(key)（绝对或相对当前工作目录）
加载结果按绝对路径缓存，避免每帧重新解析文件。
"""

from pathlib import Path

from .objLoader import MeshData, loadObjFile

_BUILTIN_DIR = Path(__file__).resolve().parent.parent / "assets" / "models"
BUILTIN_MESHES = ("cube", "sphere")

_cache = {}          # 绝对路径 → MeshData
_failed = set()      # 已确认缺失的路径（避免反复尝试读盘）


def resolveMeshPath(mesh, projectRoot=None):
    """把 mesh 键解析成候选文件路径（返回第一个存在的路径，找不到返回 None）。"""
    if not mesh:
        return None
    if mesh in BUILTIN_MESHES:
        p = _BUILTIN_DIR / f"{mesh}.obj"
        return p if p.is_file() else None
    candidates = []
    if projectRoot:
        candidates.append(Path(projectRoot) / "Resources" / mesh)
        candidates.append(Path(projectRoot) / mesh)
    candidates.append(Path(mesh))                      # 绝对路径或 cwd 相对路径
    for p in candidates:
        if p.is_file():
            return p
    return None


def getMesh(mesh, projectRoot=None):
    """按键取 MeshData；找不到返回 None（不抛异常，渲染端跳过）。"""
    if not mesh:
        return None
    path = resolveMeshPath(mesh, projectRoot)
    if path is None:
        return None
    key = str(path)
    if key in _cache:
        return _cache[key]
    if key in _failed:
        return None
    try:
        data = loadObjFile(path)
    except (OSError, ValueError):
        _failed.add(key)
        return None
    _cache[key] = data
    return data


def listProjectMeshes(projectRoot):
    """列出项目 Resources 下所有 .obj（相对路径，供创建列表/网格下拉复用）。"""
    if not projectRoot:
        return []
    res = Path(projectRoot) / "Resources"
    if not res.is_dir():
        return []
    return sorted(p.relative_to(res).as_posix()
                  for p in res.rglob("*.obj") if p.is_file())


def importModel(srcPath, projectRoot, subdir="Models"):
    """把 .obj 复制进项目 Resources/<subdir>/，返回相对资源路径；失败抛 OSError。"""
    src = Path(srcPath)
    if src.suffix.lower() != ".obj":
        raise ValueError("仅支持 .obj 模型文件")
    targetDir = Path(projectRoot) / "Resources" / subdir
    targetDir.mkdir(parents=True, exist_ok=True)
    target = targetDir / src.name
    if target.resolve() != src.resolve():
        import shutil
        shutil.copy2(src, target)
    return (Path(subdir) / src.name).as_posix()
