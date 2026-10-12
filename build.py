"""Build both frozen variants of the router-mode RouterSight widget.

    python build.py            # both variants
    python build.py onefile
    python build.py onedir

onefile  -> dist\\RouterSight.exe        (single portable exe)
onedir   -> dirdist\\RouterSight_dir\\   (faster start; rename exe to RouterSight.exe freely)
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, 'assets')
ICON = os.path.join(ASSETS, 'logo.ico')
ARROWS = ['arrow_up_dark.png', 'arrow_down_dark.png', 'arrow_up_light.png', 'arrow_down_light.png']

COMMON = [
    '--windowed',
    '--noconfirm',
    '--clean',
    '--icon', ICON,
    '--add-data', '%s;.' % ICON,
    '--hidden-import', 'routersight_router',
    '--hidden-import', 'paramiko',
    '--hidden-import', 'cryptography',
    '--exclude-module', 'tkinter',
    '--exclude-module', 'PyQt5.QtWebEngineWidgets',
]
for name in ARROWS:
    COMMON += ['--add-data', '%s;assets' % os.path.join(ASSETS, name)]


def build(variant):
    work = os.path.join(HERE, 'build_' + variant)
    out = os.path.join(HERE, 'dist' if variant == 'onefile' else 'dirdist')
    cmd = [sys.executable, '-m', 'PyInstaller', 'RouterSight.py',
           '--%s' % variant, '--name', 'RouterSight' if variant == 'onefile' else 'RouterSight_dir',
           '--distpath', out, '--workpath', work, '--specpath', work] + COMMON
    print('=== %s ===' % variant)
    print(' '.join(cmd))
    rc = subprocess.call(cmd, cwd=HERE)
    print('exit', rc)
    return rc


def main():
    want = sys.argv[1:] or ['onefile', 'onedir']
    rc = 0
    for variant in want:
        rc |= build(variant)
    for variant in want:
        work = os.path.join(HERE, 'build_' + variant)
        if os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
