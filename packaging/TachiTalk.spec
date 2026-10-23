# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
ROOT = Path(SPECPATH).parent


a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[],
    binaries=[],
    datas=[(str(ROOT / 'app/services/system_speech.ps1'), 'app/services'),
           (str(ROOT / 'packaging/release_keys.json'), 'packaging'),
           (str(ROOT / 'packaging/download_sources.json'), 'packaging')],
    hiddenimports=['PySide6.QtUiTools', '_cffi_backend'],
    hookspath=[str(ROOT / 'packaging/hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TachiTalk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ROOT / 'packaging/app.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TachiTalk',
)
