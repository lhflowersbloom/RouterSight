#!/usr/bin/env python3
"""Linux 打包流水线：PyInstaller(onedir) -> AppDir -> 单文件 .AppImage

用法（建议在干净的 venv 里跑，见 README-linux.md）：
    python linux/build_appimage.py                # 完整流程，输出 dist_linux/RouterSight-1.0-x86_64.AppImage
    python linux/build_appimage.py --skip-pyinstaller   # 复用上次的 PyInstaller 结果，只重组 AppImage
    python linux/build_appimage.py --appdir-only        # 只生成 AppDir，不压 AppImage

说明：
- 版本号取自 RouterSight.py 里的 setApplicationVersion / README，可在命令行覆盖 --version。
- appimagetool 默认从 AppImage 官方 release 下载并缓存到 .tools/；离线环境用 APPIMAGETOOL 环境变量指定。
- 不依赖 FUSE：appimagetool 以 --appimage-extract 方式解包后运行，容器里也能跑。
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, '.tools')
APPID = 'routersight'
BIN_NAME = 'RouterSight'
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

DESKTOP = """[Desktop Entry]
Type=Application
Name=RouterSight
Name[zh_CN]=RouterSight 路由视界
GenericName=Router Monitor
GenericName[zh_CN]=路由器监控组件
Comment=Live CPU / memory / disk / network stats of an OpenWrt router over SSH
Comment[zh_CN]=通过 SSH 直读 iStoreOS / OpenWrt 的 /proc，桌面实时显示路由器的 CPU、内存、磁盘与上下行速率
Exec={exec_name}
Icon={appid}
Terminal=false
Categories=System;Monitor;Network;
Keywords=router;monitor;openwrt;istoreos;netdata;ssh;
StartupNotify=false
StartupWMClass={bin_name}
X-GNOME-UsesNotifications=false
"""


def log(message: str) -> None:
    print('\033[36m==>\033[0m %s' % message, flush=True)


def run(cmd, **kwargs):
    log(' '.join(cmd))
    return subprocess.call(cmd, **kwargs)


def pyinstaller(dist_dir: str) -> str:
    """跑 PyInstaller onedir，返回生成的程序目录。"""
    work = os.path.join(ROOT, 'build_linux')
    cmd = [sys.executable, '-m', 'PyInstaller', os.path.join(ROOT, 'RouterSight.py'),
           '--onedir', '--noconfirm', '--clean',
           '--name', BIN_NAME,
           '--distpath', dist_dir, '--workpath', work, '--specpath', work,
           '--add-data', '%s:assets' % os.path.join(ROOT, 'assets'),
           '--hidden-import', 'routersight_router',
           '--hidden-import', 'paramiko',
           '--hidden-import', 'cryptography',
           '--exclude-module', 'tkinter',
           '--exclude-module', 'PyQt5.QtWebEngineWidgets',
           '--exclude-module', 'PyQt5.QtQml',
           '--exclude-module', 'PyQt5.QtQuick',
           '--exclude-module', 'PyQt5.QtMultimedia',
           '--exclude-module', 'PyQt5.QtBluetooth',
           ]
    rc = run(cmd, cwd=ROOT)
    if rc != 0:
        raise SystemExit('PyInstaller 失败，退出码 %d' % rc)
    bundle = os.path.join(dist_dir, BIN_NAME)
    if not os.path.isdir(bundle):
        raise SystemExit('未找到 PyInstaller 输出目录: %s' % bundle)
    return bundle


def make_icons(appdir: str) -> None:
    """把 assets/logo.png 缩放成 hicolor 各尺寸图标。"""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImage

    src = QImage(os.path.join(ROOT, 'assets', 'logo.png'))
    if src.isNull():
        raise SystemExit('assets/logo.png 读取失败')

    for size in ICON_SIZES:
        icon_dir = os.path.join(appdir, 'usr/share/icons/hicolor', '%dx%d' % (size, size), 'apps')
        os.makedirs(icon_dir, exist_ok=True)
        # 原图 256px，缩小用平滑插值；更大尺寸（如 512）留给发行版自己合成
        target = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        out = os.path.join(icon_dir, '%s.png' % APPID)
        if not target.save(out, 'PNG'):
            raise SystemExit('图标写出失败: %s' % out)

    root_icon = os.path.join(appdir, '%s.png' % APPID)
    src.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(root_icon, 'PNG')
    dir_icon = os.path.join(appdir, '.DirIcon')
    if os.path.lexists(dir_icon):
        os.remove(dir_icon)
    os.symlink('%s.png' % APPID, dir_icon)


def trim_bundle(exe_root: str) -> None:
    """瘦身：剥掉动态库的调试符号。

    python-build-standalone 的 libpython 带完整调试符号（约 240MB），
    strip --strip-debug 后降到 ~30MB，对运行没有影响，但体积少 200MB。
    """
    strip = shutil.which('strip')
    if not strip:
        log('未找到 strip，跳过符号剥离')
    else:
        count = 0
        for root, _dirs, files in os.walk(exe_root):
            for name in files:
                if '.so' not in name:
                    continue
                path = os.path.join(root, name)
                if os.path.islink(path):
                    continue
                try:
                    subprocess.call([strip, '--strip-debug', path],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    count += 1
                except Exception:
                    pass
        log('已剥离 %d 个动态库的调试符号' % count)


def build_appdir(bundle: str, appdir: str, version: str) -> None:
    if os.path.isdir(appdir):
        shutil.rmtree(appdir)
    os.makedirs(appdir)

    bin_dest = os.path.join(appdir, 'usr', 'bin')
    os.makedirs(bin_dest)
    # PyInstaller onedir 需要一个目录装 exe + _internal，放进 usr/lib 更符合 AppDir 规范，
    # 再在 usr/bin 里做软链，桌面文件里的 Exec 就能写成干净的程序名。
    lib_dest = os.path.join(appdir, 'usr', 'lib', APPID)
    os.makedirs(os.path.dirname(lib_dest), exist_ok=True)
    shutil.copytree(bundle, lib_dest, symlinks=True)

    exe = os.path.join(lib_dest, BIN_NAME)
    if not os.path.exists(exe):
        raise SystemExit('程序入口缺失: %s' % exe)
    os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.symlink(os.path.join('..', 'lib', APPID, BIN_NAME), os.path.join(bin_dest, BIN_NAME))

    # AppRun
    apprun_src = os.path.join(HERE, 'AppRun')
    shutil.copy2(apprun_src, os.path.join(appdir, 'AppRun'))
    os.chmod(os.path.join(appdir, 'AppRun'), 0o755)

    make_icons(appdir)
    trim_bundle(lib_dest)

    desktop = DESKTOP.format(exec_name=BIN_NAME, appid=APPID, bin_name=BIN_NAME)
    with open(os.path.join(appdir, '%s.desktop' % APPID), 'w', encoding='utf-8') as handle:
        handle.write(desktop)
    os.makedirs(os.path.join(appdir, 'usr/share/applications'), exist_ok=True)
    with open(os.path.join(appdir, 'usr/share/applications', '%s.desktop' % APPID), 'w', encoding='utf-8') as handle:
        handle.write(desktop)

    # AppStream 元数据（appimagetool 校验时用得到，缺失也只是警告）
    meta_dir = os.path.join(appdir, 'usr/share/metainfo')
    os.makedirs(meta_dir, exist_ok=True)
    with open(os.path.join(meta_dir, '%s.appdata.xml' % APPID), 'w', encoding='utf-8') as handle:
        handle.write("""<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>%s</id>
  <name>RouterSight</name>
  <summary>OpenWrt router monitor widget</summary>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <description>
    <p>Reads /proc from iStoreOS / OpenWrt over SSH and shows CPU, memory, disk I/O,
    download/upload rate and TCP/UDP connections as a desktop widget. No Netdata required.</p>
  </description>
  <launchable type="desktop-id">%s.desktop</launchable>
  <releases><release version="%s" date="2026-10-29"/></releases>
</component>
""" % (APPID, APPID, version))


def get_appimagetool() -> str:
    """返回可直接调用的 appimagetool 运行命令（解包后的 AppRun，不依赖 FUSE）。"""
    override = os.environ.get('APPIMAGETOOL')
    if override:
        return override
    os.makedirs(TOOLS, exist_ok=True)
    image = os.path.join(TOOLS, 'appimagetool-x86_64.AppImage')
    extracted = os.path.join(TOOLS, 'squashfs-root', 'AppRun')
    if os.path.exists(extracted):
        return extracted
    if not os.path.exists(image):
        url = 'https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage'
        log('下载 appimagetool ...')
        rc = run(['curl', '-fL', '--retry', '3', '-o', image, url])
        if rc != 0:
            raise SystemExit('appimagetool 下载失败，可手动下载后用 APPIMAGETOOL=/path/to/AppRun 指定')
        os.chmod(image, 0o755)
    log('解包 appimagetool（绕开 FUSE 依赖）')
    rc = run([image, '--appimage-extract'], cwd=TOOLS)
    if rc != 0 or not os.path.exists(extracted):
        raise SystemExit('appimagetool 解包失败')
    return extracted


def build_appimage(appdir: str, out_path: str) -> None:
    tool = get_appimagetool()
    env = dict(os.environ)
    env['ARCH'] = 'x86_64'
    env.setdefault('TMPDIR', os.path.join(ROOT, '.tmp'))
    os.makedirs(env['TMPDIR'], exist_ok=True)
    rc = subprocess.call([tool, '--no-appstream', appdir, out_path], env=env)
    if rc != 0:
        raise SystemExit('appimagetool 失败，退出码 %d' % rc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='1.0')
    parser.add_argument('--skip-pyinstaller', action='store_true')
    parser.add_argument('--appdir-only', action='store_true')
    args = parser.parse_args()

    dist_dir = os.path.join(ROOT, 'dist_linux')
    appdir = os.path.join(ROOT, 'dist_linux', 'RouterSight.AppDir')
    os.makedirs(dist_dir, exist_ok=True)

    bundle = os.path.join(dist_dir, BIN_NAME)
    if args.skip_pyinstaller and os.path.isdir(bundle):
        log('复用已有 PyInstaller 输出: %s' % bundle)
    else:
        bundle = pyinstaller(dist_dir)

    build_appdir(bundle, appdir, args.version)
    log('AppDir 就绪: %s' % appdir)

    if args.appdir_only:
        return 0

    out = os.path.join(dist_dir, 'RouterSight-%s-x86_64.AppImage' % args.version)
    build_appimage(appdir, out)
    size = os.path.getsize(out) / (1024 * 1024)
    log('完成: %s (%.1f MB)' % (out, size))
    return 0


if __name__ == '__main__':
    sys.exit(main())
