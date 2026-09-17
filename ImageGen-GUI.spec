# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/shiha/OneDrive/Desktop/Automations/imagegen/gui/main.py'],
    pathex=['C:/Users/shiha/OneDrive/Desktop/Automations/imagegen'],
    binaries=[],
    datas=[('C:/Users/shiha/OneDrive/Desktop/Automations/imagegen/gui/config/command_schema.json', 'gui/config')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ImageGen-GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='NONE',
)
