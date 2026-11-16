"""校验项目内的本地资源引用是否完整。

检查范围：
- index.html 中的 link / script / img / source 引用
- index.html 中 <use href="#..."> 引用的 SVG symbol 是否存在
- manifest.webmanifest 中的 start_url / scope / icons
- sw.js 中 ASSETS 列表的预缓存文件

用法：python scripts/check_references.py
退出码：0 全部通过；1 存在缺失或格式错误。
"""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / 'index.html'
MANIFEST = ROOT / 'manifest.webmanifest'
SW = ROOT / 'sw.js'

SKIP_PREFIXES = ('#', 'data:', 'mailto:', 'tel:', 'javascript:', 'blob:')


class RefParser(HTMLParser):
    """收集 HTML 中的本地资源引用与 SVG symbol 定义。"""

    ATTRS = {
        'link': 'href',
        'script': 'src',
        'img': 'src',
        'source': 'src',
        'use': 'href',
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs = []
        self.symbols = set()
        self.used_symbols = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'symbol' and attrs.get('id'):
            self.symbols.add(attrs['id'])
        attr = self.ATTRS.get(tag)
        if not attr or not attrs.get(attr):
            return
        value = attrs[attr].strip()
        if tag == 'use' and value.startswith('#'):
            self.used_symbols.append(value[1:])
        else:
            self.refs.append((tag, value))


def is_local(ref):
    return ref and not ref.startswith(SKIP_PREFIXES) and not urlsplit(ref).scheme


def resolve(base, ref):
    path = unquote(urlsplit(ref).path)
    if not path:
        return base
    return (base / path.lstrip('/')).resolve()


def check_ref(origin, ref, errors):
    target = resolve(origin.parent, ref)
    try:
        target.relative_to(ROOT)
    except ValueError:
        errors.append(f'{origin.name}: 引用越界 -> {ref}')
        return
    if ref.endswith('/'):
        ok = target.is_dir()
    else:
        ok = target.is_file()
    if not ok:
        errors.append(f'{origin.name}: 缺少资源 -> {ref}')


def main():
    errors = []

    for path in (INDEX, MANIFEST, SW):
        if not path.is_file():
            errors.append(f'缺少必需文件 -> {path.name}')

    if errors:
        print('\n'.join(errors))
        return 1

    # index.html
    parser = RefParser()
    parser.feed(INDEX.read_text(encoding='utf-8'))
    checked = 0
    for tag, ref in parser.refs:
        if is_local(ref):
            check_ref(INDEX, ref, errors)
            checked += 1
    for name in parser.used_symbols:
        if name not in parser.symbols:
            errors.append(f'index.html: 未定义的 SVG symbol -> #{name}')
    if not parser.symbols:
        errors.append('index.html: 未找到任何 SVG symbol 定义')

    # manifest.webmanifest
    try:
        manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        errors.append(f'manifest.webmanifest: JSON 解析失败 -> {exc}')
        manifest = {}

    for key in ('name', 'short_name', 'start_url', 'display', 'icons'):
        if key not in manifest:
            errors.append(f'manifest.webmanifest: 缺少字段 -> {key}')

    for key in ('start_url', 'scope'):
        ref = manifest.get(key)
        if isinstance(ref, str) and is_local(ref):
            check_ref(MANIFEST, ref, errors)
            checked += 1

    icons = manifest.get('icons', [])
    if not isinstance(icons, list) or not icons:
        errors.append('manifest.webmanifest: icons 必须是非空数组')
        icons = []
    for icon in icons:
        ref = icon.get('src') if isinstance(icon, dict) else None
        if not ref:
            errors.append('manifest.webmanifest: 图标缺少 src')
            continue
        if is_local(ref):
            check_ref(MANIFEST, ref, errors)
            checked += 1
        if not icon.get('sizes') or not icon.get('type'):
            errors.append(f'manifest.webmanifest: 图标缺少 sizes/type -> {ref}')

    # sw.js
    sw_text = SW.read_text(encoding='utf-8')
    assets_match = re.search(r'ASSETS\s*=\s*\[(.*?)\];', sw_text, re.S)
    if not assets_match:
        errors.append('sw.js: 未找到 ASSETS 数组')
        assets = []
    else:
        assets = re.findall(r'[\'"]([^\'"]+)[\'"]', assets_match.group(1))

    if not assets:
        errors.append('sw.js: ASSETS 数组为空')
    for ref in assets:
        if is_local(ref):
            check_ref(SW, ref, errors)
            checked += 1

    if not re.search(r"CACHE\s*=\s*['\"]purememo-v\d+['\"]", sw_text):
        errors.append('sw.js: CACHE 版本号格式不符合 purememo-vN')

    if errors:
        print('资源校验失败：')
        for err in errors:
            print('  - ' + err)
        return 1

    print(f'资源校验通过：{checked} 个本地引用，{len(parser.symbols)} 个 SVG symbol。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
