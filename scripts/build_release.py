#!/usr/bin/env python3
"""打包一个可部署的发布包。

产物（默认输出到 dist/）：
- PureMemo-<tag>-web.zip   静态站点：index.html / sw.js / manifest / assets/icons
- SHA256SUMS.txt           对上面 zip 的校验和

zip 内部使用固定的时间戳与文件权限，同一份源码多次打包字节一致（可复现），
这样发布包的校验和才有意义。

用法：
    python scripts/build_release.py v1.1.0
    python scripts/build_release.py            # 取 index.html 里的 app-version
"""
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'dist'
INCLUDE = ['index.html', 'sw.js', 'manifest.webmanifest', 'LICENSE']
INCLUDE_DIRS = ['assets/icons']

FIXED_TIME = (1980, 1, 1, 0, 0, 0)
TAG_RE = re.compile(r'^v\d+\.\d+\.\d+$')


def meta_version():
    """index.html 里的 app-version 是版本号的唯一来源。"""
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    m = re.search(r'<meta\s+name="app-version"\s+content="([^"]+)"', html)
    if not m:
        sys.exit('index.html 缺少 <meta name="app-version">，无法确定版本号')
    return m.group(1)


def check_version(tag):
    """标签版本必须和 index.html 里的 app-version 一致，避免发了包却写着旧版本。"""
    version = tag[1:]
    actual = meta_version()
    if actual != version:
        sys.exit(f'版本不一致：tag 是 {version}，index.html 里是 {actual}')


def collect():
    files = [ROOT / name for name in INCLUDE]
    for d in INCLUDE_DIRS:
        files.extend(sorted(p for p in (ROOT / d).rglob('*') if p.is_file()))
    missing = [str(p.relative_to(ROOT)) for p in files if not p.is_file()]
    if missing:
        sys.exit('缺少打包文件：' + ', '.join(missing))
    return files


def build(tag):
    check_version(tag)
    files = collect()
    OUT.mkdir(exist_ok=True)
    zip_path = OUT / f'PureMemo-{tag}-web.zip'

    # 先写临时文件再改名，避免打包中断留下半个 zip
    tmp = zip_path.with_suffix('.zip.part')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(rel, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    tmp.replace(zip_path)

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (OUT / 'SHA256SUMS.txt').write_text(f'{digest}  {zip_path.name}\n', encoding='utf-8')

    size_kb = zip_path.stat().st_size / 1024
    print(f'{zip_path.relative_to(ROOT)}  {size_kb:.1f} KB  ({len(files)} 个文件)')
    print(f'SHA256 {digest}')


if __name__ == '__main__':
    tag = sys.argv[1] if len(sys.argv) > 1 else 'v' + meta_version()
    if not TAG_RE.match(tag):
        sys.exit(f'版本号格式不对：{tag}（应形如 v1.1.0）')
    build(tag)
