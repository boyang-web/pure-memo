"""生成 PWA / iOS 主屏幕图标（纯标准库，无需 Pillow）。

运行：python scripts/generate_icons.py
输出：assets/icons/icon-180.png / icon-192.png / icon-512.png
"""
import math
import os
import struct
import zlib

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets', 'icons'))
LINE = (102, 102, 207)
DOT = (87, 73, 214)


def rounded_rect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    dx = max(x0 + r - x, 0.0, x - (x1 - r))
    dy = max(y0 + r - y, 0.0, y - (y1 - r))
    return dx * dx + dy * dy <= r * r


def mix(bg, fg, a):
    return (bg[0] * (1 - a) + fg[0] * a,
            bg[1] * (1 - a) + fg[1] * a,
            bg[2] * (1 - a) + fg[2] * a)


def sample(x, y):
    # 紫蓝渐变底
    t = min(1.0, max(0.0, x * 0.55 + y * 0.75))
    c = (108 + 76 * t, 124 - 20 * t, 255 - 17 * t)
    glow = max(0.0, 1.0 - math.hypot(x - 0.12, y - 0.05) / 0.9)
    c = (c[0] + 26 * glow, c[1] + 22 * glow, c[2] + 14 * glow)

    # 卡片投影
    if rounded_rect(x + 0.012, y + 0.016, 0.218, 0.195, 0.782, 0.805, 0.09):
        c = mix(c, (40, 30, 90), 0.20)

    # 玻璃白卡片 + 三条文字线
    if rounded_rect(x, y, 0.218, 0.195, 0.782, 0.805, 0.09):
        g = (y - 0.195) / 0.61
        c = mix(c, (255 - 16 * g, 255 - 14 * g, 255 - 2 * g), 0.97)
        for ly, lw, la in ((0.324, 0.406, 0.76), (0.438, 0.406, 0.45), (0.551, 0.277, 0.28)):
            if rounded_rect(x, y, 0.297, ly, 0.297 + lw, ly + 0.043, 0.021):
                c = mix(c, LINE, la)
                break

    # 右下角「新增」圆点
    dx, dy = x - 0.715, y - 0.715
    if dx * dx + dy * dy <= 0.105 ** 2:
        c = DOT
        if (abs(dx) <= 0.055 and abs(dy) <= 0.014) or (abs(dy) <= 0.055 and abs(dx) <= 0.014):
            c = (255, 255, 255)
    return c


def chunk(tag, data):
    return (struct.pack('>I', len(data)) + tag + data +
            struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))


def render(size, ss, filename):
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            r = g = b = 0.0
            for sy in range(ss):
                y = (py + (sy + 0.5) / ss) / size
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) / size
                    cr, cg, cb = sample(x, y)
                    r += cr
                    g += cg
                    b += cb
            n = ss * ss
            row.append((min(255, int(r / n + 0.5)),
                        min(255, int(g / n + 0.5)),
                        min(255, int(b / n + 0.5)), 255))
        rows.append(row)

    raw = bytearray()
    for row in rows:
        raw.append(0)
        for px in row:
            raw.extend(px)
    data = (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(bytes(raw), 6)) +
            chunk(b'IEND', b''))
    path = os.path.join(OUT, filename)
    with open(path, 'wb') as f:
        f.write(data)
    print('%s  %dx%d  %d bytes' % (filename, size, size, len(data)))


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    render(180, 3, 'icon-180.png')
    render(192, 3, 'icon-192.png')
    render(512, 2, 'icon-512.png')
