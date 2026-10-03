# -*- coding: utf-8 -*-
"""编辑器偏好：加载 / 保存 Editor/preferences.json（用户可自定义）。

默认偏好：旋转速度、平移灵敏度、移动速度、按键绑定。
"""

import json
from pathlib import Path

PREFS_FILE = Path(__file__).resolve().parent.parent / "preferences.json"

DEFAULT_PREFS = {
    "orbitSpeed": 1.0,       # 旋转视角速度倍率
    "panSensitivity": 1.0,   # 平移灵敏度
    "moveSpeed": 1.0,        # 浏览模式移动速度
    "keys": {
        "forward": "w", "back": "s", "left": "a", "right": "d",
        "up": "q", "down": "e",
    },
}


def loadPreferences():
    """读取偏好；缺失或损坏时返回默认副本。"""
    data = json.loads(json.dumps(DEFAULT_PREFS))   # 深拷贝默认值
    if not PREFS_FILE.exists():
        return data
    try:
        saved = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            for k in data:
                if k in saved and saved[k] is not None:
                    data[k] = saved[k]
            if isinstance(saved.get("keys"), dict):
                data["keys"].update(saved["keys"])
    except (json.JSONDecodeError, OSError):
        pass
    return data


def savePreferences(prefs):
    """保存偏好到 Editor/preferences.json。"""
    PREFS_FILE.write_text(
        json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8"
    )