# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单目录版（dist/VanityGen/），内含 node.exe 与 GPU 内核

用法（在项目根执行）：
    .build-env\\Scripts\\pyinstaller.exe --noconfirm --clean vanity.spec

产物：dist\\VanityGen\\VanityGen.exe —— 双击即用，目标机器不需要装 Python / Node。
"""
import os

ROOT = os.path.abspath(os.getcwd())

datas = []
for name in sorted(os.listdir(os.path.join(ROOT, "engine"))):
    if name.endswith(".js"):
        datas.append((os.path.join("engine", name), "engine"))
for name in sorted(os.listdir(os.path.join(ROOT, "gpu"))):
    if name.endswith(".cl"):
        datas.append((os.path.join("gpu", name), "gpu"))

binaries = []
node = os.path.join(ROOT, "runtime", "node.exe")
if os.path.isfile(node):
    binaries.append((node, "runtime"))

a = Analysis(
    [os.path.join(ROOT, "app", "main.py")],
    pathex=[os.path.join(ROOT, "app"), os.path.join(ROOT, "gpu")],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "opencl", "keccak_py", "license", "device_id",
        "xlsx_writer", "state_store", "qr_code", "gpu_engine",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "PIL", "pytest", "unittest", "pydoc"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VanityGen",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # GUI 程序，不弹黑窗
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
    upx=False,
    upx_exclude=[],
    name="VanityGen",
)
