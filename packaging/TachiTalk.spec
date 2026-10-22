# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/TachiTalk/main.py'],
    pathex=[],
    binaries=[],
    datas=[('D:/TachiTalk/app/services/system_speech.ps1', 'app/services')],
    hiddenimports=['PySide6.QtUiTools', '_cffi_backend'],
    hookspath=['D:/TachiTalk/packaging/hooks'],
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
    icon=['D:/TachiTalk/packaging/app.ico'],
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
