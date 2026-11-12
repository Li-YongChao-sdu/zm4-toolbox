# -*- mode: python ; coding: utf-8 -*-
"""造梦西游4活动工具箱 打包配置。

统一入口：run.py
构建命令：python -m PyInstaller --noconfirm --clean "造梦西游4活动工具箱.spec"
产物目录：dist/造梦西游4活动工具箱/
"""
import os

from PyInstaller.utils.hooks import collect_all

ROOT = SPECPATH

# 运行时需要随包发布的资源；不存在的目录自动跳过，方便在开发目录和仓库目录复用。
DATA_ITEMS = [
    ('output_cg1_20260921_1_2', 'output_cg1_20260921_1_2'),
    ('config_review_20261012_2', 'config_review_20261012_2'),
    ('jiuzhuan_rl_model', 'jiuzhuan_rl_model'),
    ('独立附件', '独立附件'),
    ('question-model-solver-3.py', '.'),
    ('craft_books.json', '.'),
    ('book_equip_attrs.json', '.'),
    ('moyuan_weekly_config.json', '.'),
]

datas = [(os.path.join(ROOT, source), target)
         for source, target in DATA_ITEMS
         if os.path.exists(os.path.join(ROOT, source))]
binaries = []
hiddenimports = []

for package in ('Crypto', 'certifi', 'charset_normalizer'):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception:
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ['run.py'],
    pathex=[ROOT],
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
