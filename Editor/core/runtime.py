# -*- coding: utf-8 -*-
"""V5 脚本运行时：加载项目 .vpy 脚本并驱动播放模式。

脚本约定（.vpy 为 Python 源文件，位于项目 Resources 下）：
- 定义 start(obj)：进入播放时调用一次（可初始化物体自定义属性）
- 定义 update(obj, dt)：播放期间每帧调用，dt 为秒（基于真实帧间隔）

脚本内可用：
- obj.transform（position / rotation / scale，numpy 数组，直接改）
- obj.name / obj.active / obj.parent / obj.children
- obj.getComponent(...) 读取其它组件

脚本异常不会中断编辑器：错误打印到终端（stderr）。
"""

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from .scene import Script

# 模块缓存：绝对路径 → 模块（False 表示加载失败），避免播放期间反复读盘
_MOD_CACHE = {}


def _clearCache():
    _MOD_CACHE.clear()


def _loadModule(rel, projectRoot):
    """加载 .vpy 脚本模块（带缓存）；失败返回 None。"""
    if not rel:
        return None
    root = Path(projectRoot) if projectRoot else None
    if root is None:
        return None
    path = root / "Resources" / rel
    if not path.is_file():
        return None
    key = str(path.resolve())
    if key in _MOD_CACHE:
        return _MOD_CACHE[key] or None
    try:
        name = f"vortex_script_{abs(hash(key))}"
        # .vpy 不是 Python 默认扩展名：用 SourceFileLoader 显式加载
        loader = SourceFileLoader(name, str(path))
        spec = importlib.util.spec_from_loader(name, loader)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        loader.exec_module(mod)
    except Exception as e:
        print(f"[脚本] 加载失败 {rel}: {e}", file=sys.stderr)
        _MOD_CACHE[key] = False
        return None
    _MOD_CACHE[key] = mod
    return mod


def startScripts(scene, projectRoot):
    """播放进入：对所有带脚本组件的物体调用一次 start(obj)。"""
    if scene is None:
        return
    for go in scene.objects:
        if not go.active:
            continue
        for comp in go.components:
            if isinstance(comp, Script) and comp.script:
                mod = _loadModule(comp.script, projectRoot)
                if mod is not None and hasattr(mod, "start"):
                    try:
                        mod.start(go)
                    except Exception as e:
                        print(f"[脚本] start 错误 {comp.script}: {e}", file=sys.stderr)


def updateScripts(scene, projectRoot, dt):
    """播放每帧：对所有带脚本组件的物体调用 update(obj, dt)。"""
    if scene is None:
        return
    for go in scene.objects:
        if not go.active:
            continue
        for comp in go.components:
            if isinstance(comp, Script) and comp.script:
                mod = _loadModule(comp.script, projectRoot)
                if mod is not None and hasattr(mod, "update"):
                    try:
                        mod.update(go, dt)
                    except Exception as e:
                        print(f"[脚本] update 错误 {comp.script}: {e}", file=sys.stderr)
