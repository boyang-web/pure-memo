#!/usr/bin/env python3
"""校验仓库里与当前版本对应的 APK 是否可被 Android 11+ 安装。

不需要 Android SDK，只看 APK 这个 zip 的结构。CI 里跑这一步，能在没有
build-tools 的情况下挡住「resources.arsc 被压缩 / 未对齐」这类致命打包错误。

用法：
    python scripts/check_apk.py
"""

import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def die(msg):
    sys.exit(f'✗ {msg}')


def version():
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    m = re.search(r'<meta\s+name="app-version"\s+content="([^"]+)"', html)
    if not m:
        die('index.html 缺少 <meta name="app-version">')
    return m.group(1)


def check():
    v = version()
    apk = ROOT / 'release' / f'PureMemo-v{v}.apk'
    if not apk.is_file():
        die(f'找不到 {apk.relative_to(ROOT)}（改了版本号就要重新构建 APK）')

    with zipfile.ZipFile(apk) as z, open(apk, 'rb') as f:
        names = set(z.namelist())

        if 'classes.dex' not in names:
            die('APK 里没有 classes.dex')

        info = z.getinfo('resources.arsc')
        if info.compress_type != zipfile.ZIP_STORED:
            die('resources.arsc 被压缩：targetSdk >= 30 的 APK 必须未压缩存放，Android 11+ 会拒绝安装')

        f.seek(info.header_offset + 26)
        name_len, extra_len = struct.unpack('<HH', f.read(4))
        offset = info.header_offset + 30 + name_len + extra_len
        if offset % 4:
            die(f'resources.arsc 未按 4 字节对齐（数据偏移 {offset}）')

        if not any(n.startswith('META-INF/') and n.endswith(('.RSA', '.DSA', '.EC')) for n in names):
            die('没有找到 v1 签名块（META-INF/*.RSA），老设备可能装不上')

        print(f'APK 校验通过：PureMemo-v{v}.apk')
        print(f'  resources.arsc 未压缩、4 字节对齐（偏移 {offset}）')
        print(f'  classes.dex 存在，v1 签名存在')


if __name__ == '__main__':
    check()
