# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

BASE_DIR = Path(os.path.abspath(SPECPATH)).parent.parent
BIN_DIR = BASE_DIR / "bin"
RESOURCES_DIR = BASE_DIR / "resources"

# Collect CustomTkinter assets
datas = collect_data_files("customtkinter")

# Include bundled FFmpeg binaries if available in bin/
binaries = []
ffmpeg_exe = BIN_DIR / "ffmpeg.exe"
ffprobe_exe = BIN_DIR / "ffprobe.exe"
if ffmpeg_exe.exists():
    binaries.append((str(ffmpeg_exe), "."))
if ffprobe_exe.exists():
    binaries.append((str(ffprobe_exe), "."))

# Include pillow_heif and rawpy submodules
hiddenimports = [
    "customtkinter",
    "darkdetect",
    "PIL",
    "PIL.Image",
    "PIL.ImageOps",
    "PIL.ImageFile",
    "pillow_heif",
    "rawpy",
    "psutil",
    "pynvml",
    "media_optimizer",
] + collect_submodules("pillow_heif")

a = Analysis(
    [str(BASE_DIR / "main.py")],
    pathex=[str(BASE_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MediaOptimizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(RESOURCES_DIR / "icon.ico") if (RESOURCES_DIR / "icon.ico").exists() else None,
)
