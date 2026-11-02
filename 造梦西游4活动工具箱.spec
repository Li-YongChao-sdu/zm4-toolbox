# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('output_cg1_20260921_1_2', 'output_cg1_20260921_1_2'), ('question-model-solver-3.py', '.'), ('craft_books.json', '.'), ('book_equip_attrs.json', '.'), ('moyuan_weekly_config.json', '.')]
binaries = [('C:/ProgramData/miniconda3/Library/bin/' + dll, '.') for dll in ['tcl86t.dll', 'tk86t.dll', 'ffi.dll', 'libmpdec-4.dll']]
hiddenimports = []
tmp_ret = collect_all('Crypto')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['zm4_toolbox.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide6', 'pandas', 'matplotlib', 'scipy', 'IPython', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='造梦西游4活动工具箱',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='造梦西游4活动工具箱',
)


