# -*- coding: utf-8 -*-
"""用 Pillow 生成编辑器工具栏图标 PNG（Editor/assets/icons/）。

用法：python Editor/tools/make_icons.py
生成的图标：cube.png（创建立方体）/ sphere.png（创建球体）/ play.png（播放）。
"""

from pathlib import Path

import sys

from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
SIZE = 32


def _drawCube():
    """立方体线框图标（深蓝体 + 淡蓝顶面）。"""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 顶面 + 立柱
    d.polygon([(8, 7), (24, 7), (27, 10), (11, 10)], fill=(200, 220, 255, 255))
    d.polygon([(8, 7), (11, 10), (11, 24), (8, 21)], fill=(150, 175, 225, 255))
    d.polygon([(24, 7), (27, 10), (27, 24), (24, 21)], fill=(110, 140, 200, 255))
    d.line([(8, 7), (24, 7), (27, 10), (27, 24), (11, 24), (11, 10), (8, 7), (8, 21), (11, 24)], fill=(30, 40, 60, 255), width=2)
    d.line([(8, 21), (27, 21)], fill=(30, 40, 60, 255), width=2)
    return img


def _drawSphere():
    """球体图标（渐变圆 + 高光）。"""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    boxes = [(4, 4, 28, 28)]
    d.ellipse(boxes[0], fill=(170, 200, 255, 255), outline=(30, 40, 60, 255), width=2)
    d.arc((10, 8, 26, 24), start=180, end=300, fill=(230, 240, 255, 255), width=2)  # 高光
    d.ellipse((11, 9, 14, 12), fill=(235, 245, 255, 255))                            # 高光点
    return img


def _drawPlay():
    """播放三角图标。"""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(10, 7), (26, 16), (10, 25)], fill=(120, 200, 120, 255),
              outline=(20, 60, 25, 255))
    return img


def ensureIcons():
    """生成缺失的图标；已存在则跳过。返回图标是否存在。"""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    makers = {"cube.png": _drawCube, "sphere.png": _drawSphere, "play.png": _drawPlay}
    for name, maker in makers.items():
        target = ASSETS_DIR / name
        if not target.exists():
            maker().save(target, "PNG")
    return all((ASSETS_DIR / n).exists() for n in makers)


def main():
    ok = ensureIcons()
    print("[图标] 生成完成：" + (", ".join(p.name for p in sorted(ASSETS_DIR.glob("*.png")))))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())