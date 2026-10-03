# -*- coding: utf-8 -*-
"""场景序列化（V3）：scene.json 保存 / 加载。

格式：扁平 objects 数组 + parent 用 uuid 引用（旧版约定），
每个物体带 components 数组（含默认 Transform）。损坏或缺字段时安全回退。
"""

import json
import uuid

import numpy as np

from .scene import Camera, GameObject, Light, MeshRenderer, Scene, Transform

SCHEMA = 4


def _listOrNone(v):
    """把 JSON 值转成 float 三元组；无效返回 None。"""
    try:
        return [float(x) for x in v]
    except (TypeError, ValueError):
        return None


def _numList(v):
    """把 numpy 数组/列表转成纯 Python float 列表（JSON 可序列化）。"""
    return [float(x) for x in v]


def serializeComponent(comp):
    """组件 → 可 JSON 化的字典。"""
    if isinstance(comp, Transform):
        return {
            "type": "Transform",
            "position": _numList(comp.position),
            "rotation": _numList(comp.rotation),
            "scale": _numList(comp.scale),
        }
    if isinstance(comp, MeshRenderer):
        return {"type": "MeshRenderer", "mesh": comp.mesh, "material": comp.material}
    if isinstance(comp, Light):
        return {
            "type": "Light",
            "lightType": comp.lightType,
            "color": _numList(comp.color),
            "intensity": float(comp.intensity),
        }
    if isinstance(comp, Camera):
        return {
            "type": "Camera",
            "fov": float(comp.fov),
            "near": float(comp.near),
            "far": float(comp.far),
        }
    return {"type": "Unknown"}


def deserializeComponent(data):
    """字典 → 组件实例；未知类型返回 None。"""
    ctype = data.get("type")
    if ctype == "Transform":
        t = Transform()
        if v := _listOrNone(data.get("position")):
            t.position = np.asarray(v, dtype=float)
        if v := _listOrNone(data.get("rotation")):
            t.rotation = np.asarray(v, dtype=float)
        if v := _listOrNone(data.get("scale")):
            t.scale = np.asarray(v, dtype=float)
        return t
    if ctype == "MeshRenderer":
        # V3.5：颜色已从组件移除，改由材质资源配置；旧数据 color 忽略
        return MeshRenderer(mesh=data.get("mesh"), material=data.get("material"))
    if ctype == "Light":
        color = _listOrNone(data.get("color"))
        return Light(lightType=data.get("lightType") or "directional",
                     color=color or [1.0, 1.0, 1.0],
                     intensity=data.get("intensity", 1.0))
    if ctype == "Camera":
        return Camera(fov=data.get("fov", 60.0),
                      near=data.get("near", 0.1),
                      far=data.get("far", 1000.0))
    return None


def serializeScene(scene):
    """Scene → 可 JSON 化的 dict（扁平数组 + parent uuid 引用）。"""
    objects = []
    for go in scene.objects:
        objects.append({
            "uuid": go.uuid,
            "name": go.name,
            "active": bool(go.active),
            "parent": go.parent.uuid if go.parent is not None else None,
            "components": [serializeComponent(c) for c in go.components],
        })
    return {"schema": SCHEMA, "objects": objects}


def deserializeScene(data):
    """dict → Scene（未知组件跳过；缺 Transform 自动补）。"""
    scene = Scene()
    if not isinstance(data, dict):
        return scene
    byUuid = {}
    parentOf = {}
    for od in data.get("objects", []) or []:
        if not isinstance(od, dict):
            continue
        go = GameObject(name=str(od.get("name") or "物体"),
                        active=bool(od.get("active", True)))
        uid = od.get("uuid")
        go.uuid = str(uid) if uid else uuid.uuid4().hex
        go.components = []
        for cd in od.get("components", []) or []:
            comp = deserializeComponent(cd)
            if comp is not None:
                go.components.append(comp)
                comp.gameObject = go
        if not any(isinstance(c, Transform) for c in go.components):
            go.components.insert(0, Transform())
            go.components[0].gameObject = go
        byUuid[go.uuid] = go
        parentOf[go.uuid] = od.get("parent")
        scene.objects.append(go)
    # 二次遍历补父子关系（父可能排在子后面，统一用 uuid 引用）
    for go in scene.objects:
        pid = parentOf.get(go.uuid)
        parent = byUuid.get(str(pid)) if pid else None
        if parent is not None and parent is not go:
            scene.setParent(go, parent)
    return scene


def saveSceneFile(scene, path):
    """保存场景到 JSON 文件（.vscene 自定义场景格式，内容为 JSON）。"""
    p = path if str(path).endswith((".json", ".vscene")) else f"{path}.vscene"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(serializeScene(scene), f, ensure_ascii=False, indent=2)
    return p


def loadSceneFile(path):
    """从场景文件（.vscene/.json）加载场景；文件缺失或损坏返回空场景。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return deserializeScene(json.load(f))
    except (OSError, json.JSONDecodeError):
        return Scene()
