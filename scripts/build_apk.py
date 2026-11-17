#!/usr/bin/env python3
"""打包 Android WebView 壳 APK。

不需要 Gradle：直接调用 SDK 的 aapt2 / javac / d8 / zipalign / apksigner。
依赖只有 JDK 17 与 Android SDK（build-tools + platforms）。

用法：
    python scripts/build_apk.py                 # 版本号取 index.html 的 app-version
    python scripts/build_apk.py --skip-sign     # 只出未签名包，用于排查打包问题

环境变量：
    JAVA_HOME       不设则回落到 ~/.local/toolchain/jdk-*/Contents/Home
    ANDROID_HOME    不设则回落到 ~/.local/toolchain/android-sdk
    PUREMEMO_STORE_PASS  签名口令；不设则从 android/keystore/keystore.properties 读，
                         首次运行会生成密钥并写回该文件
"""

import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build' / 'apk'
ANDROID = ROOT / 'android'
RELEASE = ROOT / 'release'
KEYSTORE = ANDROID / 'keystore' / 'purememo-release.jks'
KEY_PROPS = ANDROID / 'keystore' / 'keystore.properties'
KEY_ALIAS = 'purememo'

# 随包分发的运行时文件：与 web 版 zip 里的一致，但没有 sw.js
# （壳里资源随包走、不会热更新，Service Worker 无意义，MainActivity 对它直接回 404）
RUNTIME_FILES = ['index.html', 'manifest.webmanifest']
RUNTIME_DIRS = ['assets/icons']

FIXED_TIME = (1980, 1, 1, 0, 0, 0)
MIN_SDK = 24
TARGET_SDK = 34


def die(msg):
    sys.exit(f'✗ {msg}')


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write((r.stdout or '') + (r.stderr or ''))
        die(f'命令失败：{" ".join(str(c) for c in cmd)}')
    return r


def find_java_home():
    env = os.environ.get('JAVA_HOME')
    if env and (Path(env) / 'bin' / 'javac').exists():
        return Path(env)
    for base in (Path.home() / '.local' / 'toolchain', Path.home() / 'Library' / 'Java' / 'JavaVirtualMachines'):
        for candidate in sorted(base.glob('jdk-*'), reverse=True):
            for home in (candidate / 'Contents' / 'Home', candidate):
                if (home / 'bin' / 'javac').exists():
                    return home
    die('找不到 JDK 17，请设置 JAVA_HOME（macOS: brew install --cask temurin@17）')


def find_sdk():
    for key in ('ANDROID_HOME', 'ANDROID_SDK_ROOT'):
        env = os.environ.get(key)
        if env and (Path(env) / 'build-tools').is_dir():
            return Path(env)
    fallback = Path.home() / '.local' / 'toolchain' / 'android-sdk'
    if (fallback / 'build-tools').is_dir():
        return fallback
    die('找不到 Android SDK，请设置 ANDROID_HOME（需含 build-tools 与 platforms）')


def newest(paths):
    if not paths:
        return None
    def key(p):
        return [int(x) for x in re.findall(r'\d+', p.name)]
    return sorted(paths, key=key)[-1]


def app_version():
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    m = re.search(r'<meta\s+name="app-version"\s+content="([^"]+)"', html)
    if not m:
        die('index.html 缺少 <meta name="app-version">，无法确定版本号')
    version = m.group(1)
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        die(f'版本号格式不对：{version}（应形如 1.1.1）')
    return version


def version_code(version):
    major, minor, patch = (int(x) for x in version.split('.'))
    # 与旧包的 versionCode 1 相比依然更大，可覆盖安装
    return major * 10000 + minor * 100 + patch


def stage_assets():
    assets = BUILD / 'assets'
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir(parents=True)
    for name in RUNTIME_FILES:
        shutil.copy2(ROOT / name, assets / name)
    for d in RUNTIME_DIRS:
        shutil.copytree(ROOT / d, assets / d)
    return assets


# Android 11（API 30）起，targetSdk >= 30 的 APK 必须把 resources.arsc
# 未压缩存放且 4 字节对齐，否则系统会直接拒绝安装（INSTALL_FAILED_INVALID_APK）。
# classes.dex 也按最佳实践未压缩存放，ART 可以直接 mmap。
STORED_ENTRIES = {'resources.arsc', 'classes.dex'}


def deterministic_zip(entries, out):
    """写一个时间戳与权限都固定的 zip，便于核对哈希。"""
    if not out.parent.is_dir():
        out.parent.mkdir(parents=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for arcname, data in entries:
            info = zipfile.ZipInfo(arcname, date_time=FIXED_TIME)
            info.compress_type = (zipfile.ZIP_STORED if arcname in STORED_ENTRIES
                                  else zipfile.ZIP_DEFLATED)
            info.external_attr = 0o600 << 16
            z.writestr(info, data)
    return out


def check_apk_alignment(apk):
    """显式校验 resources.arsc 未压缩且 4 字节对齐——zipalign -c 查不出被压缩的情况。"""
    with zipfile.ZipFile(apk) as z:
        info = z.getinfo('resources.arsc')
        if info.compress_type != zipfile.ZIP_STORED:
            die('resources.arsc 被压缩了，Android 11+ 会拒绝安装')
        with open(apk, 'rb') as f:
            f.seek(info.header_offset + 26)
            name_len, extra_len = struct.unpack('<HH', f.read(4))
        offset = info.header_offset + 30 + name_len + extra_len
        if offset % 4:
            die(f'resources.arsc 未按 4 字节对齐（偏移 {offset}）')
        return info.file_size, offset


def rewrite_apk(src, extra, out):
    """把 aapt2 产物重新打包成时间戳固定的 zip，并塞入额外条目。"""
    entries = []
    with zipfile.ZipFile(src) as z:
        for name in z.namelist():
            entries.append((name, z.read(name)))
    entries.extend(extra)
    return deterministic_zip(sorted(entries, key=lambda e: e[0]), out)


def ensure_keystore(java_home):
    if KEYSTORE.exists():
        return
    if KEY_PROPS.exists():
        props = dict(
            line.strip().split('=', 1)
            for line in KEY_PROPS.read_text(encoding='utf-8').splitlines()
            if '=' in line
        )
        password = props.get('storePassword')
        if not password:
            die(f'{KEY_PROPS} 里没有 storePassword')
    else:
        password = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
        if not KEY_PROPS.parent.is_dir():
            KEY_PROPS.parent.mkdir(parents=True)
        KEY_PROPS.write_text(
            f'storePassword={password}\nkeyPassword={password}\nalias={KEY_ALIAS}\n',
            encoding='utf-8',
        )
        KEY_PROPS.chmod(0o600)

    print(f'  生成签名密钥 {KEYSTORE.relative_to(ROOT)}（口令存在 keystore.properties，务必备份）')
    run([
        str(java_home / 'bin' / 'keytool'), '-genkeypair', '-noprompt',
        '-keystore', str(KEYSTORE), '-storetype', 'PKCS12',
        '-alias', KEY_ALIAS, '-keyalg', 'RSA', '-keysize', '4096',
        '-validity', '10000', '-dname', 'CN=PureMemo,O=baiyang,C=CN',
        '-storepass', password, '-keypass', password,
    ])
    KEYSTORE.chmod(0o600)


def keystore_password():
    env = os.environ.get('PUREMEMO_STORE_PASS')
    if env:
        return env
    if KEY_PROPS.exists():
        for line in KEY_PROPS.read_text(encoding='utf-8').splitlines():
            if line.startswith('storePassword='):
                return line.split('=', 1)[1].strip()
    die(f'读不到签名口令（{KEY_PROPS}）')


def main():
    skip_sign = '--skip-sign' in sys.argv

    java_home = find_java_home()
    # build-tools 里的 d8 / apksigner 是 shell 包装脚本，靠 JAVA_HOME 或 PATH 找 java
    os.environ['JAVA_HOME'] = str(java_home)
    os.environ['PATH'] = str(java_home / 'bin') + os.pathsep + os.environ.get('PATH', '')
    sdk = find_sdk()
    build_tools = newest([p for p in (sdk / 'build-tools').iterdir() if p.is_dir()])
    platform = newest([p for p in (sdk / 'platforms').iterdir() if p.name.startswith('android-')])
    if not build_tools or not platform:
        die('SDK 缺少 build-tools 或 platforms/android-*')
    android_jar = platform / 'android.jar'

    version = app_version()
    code = version_code(version)
    apk_name = f'PureMemo-v{version}.apk'

    print(f'纯粹备忘录 APK  {version}（versionCode {code}）')
    print(f'  JDK     {java_home}')
    print(f'  SDK     {sdk}  ({build_tools.name} / {platform.name})')

    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    assets = stage_assets()
    print(f'  资源    已收集 {sum(1 for _ in assets.rglob("*") if _.is_file())} 个文件到 assets/')

    print('  aapt2   编译资源')
    res_zip = BUILD / 'res.zip'
    run([str(build_tools / 'aapt2'), 'compile', '--dir', str(ANDROID / 'res'), '-o', str(res_zip)])

    print('  aapt2   链接清单')
    linked = BUILD / 'linked.apk'
    run([
        str(build_tools / 'aapt2'), 'link',
        '-o', str(linked),
        '-I', str(android_jar),
        '--manifest', str(ANDROID / 'AndroidManifest.xml'),
        '-A', str(assets),
        '--min-sdk-version', str(MIN_SDK),
        '--target-sdk-version', str(TARGET_SDK),
        '--version-code', str(code),
        '--version-name', version,
        str(res_zip),
    ])

    print('  javac   编译壳代码')
    classes = BUILD / 'classes'
    classes.mkdir()
    sources = [str(p) for p in (ANDROID / 'src').rglob('*.java')]
    run([
        str(java_home / 'bin' / 'javac'),
        '-source', '8', '-target', '8', '-nowarn', '-Xlint:-options',
        '-encoding', 'UTF-8',
        '-classpath', str(android_jar),
        '-d', str(classes),
    ] + sources)

    print('  d8      生成 dex')
    dex_dir = BUILD / 'dex'
    dex_dir.mkdir()
    class_files = [str(p) for p in classes.rglob('*.class')]
    run([
        str(build_tools / 'd8'),
        '--release', '--min-api', str(MIN_SDK),
        '--lib', str(android_jar),
        '--output', str(dex_dir),
    ] + class_files)
    dex = (dex_dir / 'classes.dex').read_bytes()

    print('  打包    合并 assets + classes.dex')
    unsigned = rewrite_apk(linked, [('classes.dex', dex)], BUILD / 'unsigned.apk')

    print('  zipalign 4 字节对齐')
    aligned = BUILD / 'aligned.apk'
    run([str(build_tools / 'zipalign'), '-f', '-p', '4', str(unsigned), str(aligned)])
    size, offset = check_apk_alignment(aligned)
    print(f'  校验    resources.arsc 未压缩、偏移 {offset} 4 字节对齐（{size} 字节）')

    if not RELEASE.is_dir():
        RELEASE.mkdir(parents=True)
    target = RELEASE / apk_name

    if skip_sign:
        shutil.copy2(aligned, target)
    else:
        ensure_keystore(java_home)
        password = keystore_password()
        print('  apksigner 签名（v1 + v2 + v3）')
        if target.exists():
            target.unlink()
        run([
            str(build_tools / 'apksigner'), 'sign',
            '--ks', str(KEYSTORE), '--ks-key-alias', KEY_ALIAS,
            '--ks-pass', f'pass:{password}', '--key-pass', f'pass:{password}',
            '--min-sdk-version', str(MIN_SDK),
            '--v1-signing-enabled', 'true',
            '--v2-signing-enabled', 'true',
            '--v3-signing-enabled', 'true',
            '--v4-signing-enabled', 'false',   # v4 的 .idsig 只在 adb 增量安装时有用，不随包发布
            '--out', str(target), str(aligned),
        ])
        verify = run([str(build_tools / 'apksigner'), 'verify', '--print-certs', str(target)])
        cert = next((l for l in verify.stdout.splitlines() if 'SHA-256' in l), '')
        print(f'  校验    {cert.strip()}')

    check_apk_alignment(target)   # 签名不应改变对齐，最终包再查一遍

    badging = run([str(build_tools / 'aapt2'), 'dump', 'badging', str(target)]).stdout
    summary = [l for l in badging.splitlines() if l.startswith(('package:', 'sdkVersion', 'targetSdkVersion', 'launchable-activity'))]
    for line in summary:
        print(f'          {line}')

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    size = target.stat().st_size
    print(f'\n✓ {target.relative_to(ROOT)}  {size / 1024:.1f} KB  sha256:{digest[:16]}…')

    sums = RELEASE / f'SHA256SUMS-v{version}.txt'
    sums.write_text(f'{digest}  {apk_name}\n', encoding='utf-8')
    print(f'✓ {sums.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
