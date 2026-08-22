# -*- coding: utf-8 -*-
"""生成应用图标 assets/app_icon.ico：蓝底圆角 + 白色放大镜 + 镜片内「词」字。

用 QPainter 绘制，无需 Pillow；ICO 采用 PNG 内嵌格式（Vista+ 支持），
内含 256/128/64/48/32/16 六个尺寸。
用法：python scripts/make_icon.py
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "app_icon.ico"
SIZES = [256, 128, 64, 48, 32, 16]

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage,
                           QLinearGradient, QPainter, QPen)


def draw_icon(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0  # 以 256 为基准缩放

    # 背景：蓝渐变圆角方块（留 8px 边距）
    margin = 8 * s
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    grad = QLinearGradient(QPointF(0, margin), QPointF(0, size - margin))
    grad.setColorAt(0.0, QColor("#4f8ef7"))
    grad.setColorAt(1.0, QColor("#1d4ed8"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(rect, 52 * s, 52 * s)

    # 放大镜圆环（白色，粗 13）
    cx, cy, r = 98 * s, 96 * s, 58 * s
    pen = QPen(QColor("#ffffff"), 13 * s)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r)

    # 手柄（白色圆头，从圆环右下斜伸）
    import math
    ang = math.radians(45)
    x1 = cx + r * math.cos(ang)
    y1 = cy + r * math.sin(ang)
    x2 = cx + (r + 46 * s) * math.cos(ang)
    y2 = cy + (r + 46 * s) * math.sin(ang)
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    # 镜片内「词」字（白色，微软雅黑粗体）
    font = QFont("Microsoft YaHei", int(66 * s))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(cx - r, cy - r * 1.05, 2 * r, 2 * r),
               Qt.AlignCenter, "词")
    p.end()
    return img


def write_ico(images: dict) -> None:
    """把 {size: QImage} 写成 PNG 内嵌的多尺寸 ICO。"""
    pngs = {}
    from PySide6.QtCore import QBuffer, QIODevice
    for size, img in images.items():
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        ok = img.save(buf, "PNG")
        assert ok, f"PNG encode failed for {size}"
        pngs[size] = bytes(buf.data())
    sizes = sorted(pngs.keys(), reverse=True)
    count = len(sizes)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    offset = 6 + 16 * count
    for sz in sizes:
        w = 0 if sz >= 256 else sz
        h = 0 if sz >= 256 else sz
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32,
                               len(pngs[sz]), offset)
        offset += len(pngs[sz])
    blob = header + entries + b"".join(pngs[s] for s in sizes)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(blob)
    print(f"icon written: {OUT} ({len(blob)} bytes, sizes={sizes})")


def main():
    app = QGuiApplication(sys.argv)  # QPainter 需要
    images = {sz: draw_icon(sz) for sz in SIZES}
    write_ico(images)
    print("OK")


if __name__ == "__main__":
    main()
