# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ETS2 Garage.

Build with:  python -m PyInstaller ETS2Garage.spec --noconfirm
Output:      dist/ETS2Garage/ETS2Garage.exe   (one-folder build)
             or dist/ETS2Garage.exe           (if ONE_FILE = True)
"""
import os

ONE_FILE = os.environ.get('ETS2GARAGE_ONEFILE', '1') == '1'

ROOT = os.path.abspath(os.getcwd())
PKG = os.path.join(ROOT, 'ets2garage')
WEB = os.path.join(ROOT, 'web')

hidden = [
    'catalog', 'model3d', 'mat', 'pmd', 'pmg', 'sii', 'scs', 'cityhash64',
    'tokens', 'texture', 'server',
    'PIL', 'PIL.Image', 'PIL.ImageFile', 'PIL.DdsImagePlugin',
    'numpy', 'numpy.core', 'numpy._core',
    'webview', 'webview.platforms.edgechromium', 'webview.platforms.winforms',
    'clr_loader', 'pythonnet', 'bottle', 'proxy_tools',
]

binaries = []
for cand in ('gdeflate.dll',):
    p = os.path.join(PKG, cand)
    if os.path.exists(p):
        binaries.append((p, '.'))

a = Analysis(
    [os.path.join(PKG, 'app.py')],
    pathex=[PKG, ROOT],
    binaries=binaries,
    datas=[(WEB, 'web')],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pytest', 'PyQt5', 'PySide6'],
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONE_FILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name='ETS2Garage',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        icon=None,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name='ETS2Garage',
        debug=False,
        strip=False,
        upx=False,
        console=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                   name='ETS2Garage')