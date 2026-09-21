#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper script to download and stage static FFmpeg and FFprobe binaries
for bundling into standalone packages (.exe, AppImage, .dmg).
Ensures end users have zero setup requirements.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

# Base directories
ROOT_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT_DIR / "bin"


# URLs for pre-compiled static FFmpeg builds
FFMPEG_URLS = {
    "windows": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    "linux": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
    "darwin": "https://evermeet.cx/ffmpeg/getrelease/zip",
}


def download_file(url: str, dest_path: Path) -> None:
    """Download a file with progress reporting."""
    print(f"⬇️ Baixando FFmpeg de: {url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    def report(count, block_size, total_size):
        if total_size > 0:
            percent = int(count * block_size * 100 / total_size)
            print(f"\rProgresso: {percent}%", end="", flush=True)

    urllib.request.urlretrieve(url, dest_path, reporthook=report)
    print("\n✅ Download concluído!")


def stage_ffmpeg_windows(archive_path: Path, target_dir: Path) -> None:
    """Extract ffmpeg.exe and ffprobe.exe from Windows zip."""
    print(f"📦 Extraindo binários para {target_dir}...")
    with zipfile.ZipFile(archive_path, "r") as z:
        for member in z.namelist():
            filename = Path(member).name
            if filename.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                data = z.read(member)
                dest = target_dir / filename
                dest.write_bytes(data)
                print(f"  -> Extraído: {dest}")


def stage_ffmpeg_linux(archive_path: Path, target_dir: Path) -> None:
    """Extract ffmpeg and ffprobe from Linux tar."""
    print(f"📦 Extraindo binários para {target_dir}...")
    with tarfile.open(archive_path, "r:*") as t:
        for member in t.getmembers():
            filename = Path(member.name).name
            if filename in ("ffmpeg", "ffprobe"):
                f = t.extractfile(member)
                if f:
                    dest = target_dir / filename
                    dest.write_bytes(f.read())
                    dest.chmod(0o755)
                    print(f"  -> Extraído: {dest}")


def ensure_bundled_binaries(target_os: str | None = None) -> Path:
    """Ensures ffmpeg and ffprobe exist in bin/ folder for current or specified OS."""
    current_os = (target_os or platform.system()).lower()
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    exe_suffix = ".exe" if current_os == "windows" else ""
    ffmpeg_target = BIN_DIR / f"ffmpeg{exe_suffix}"
    ffprobe_target = BIN_DIR / f"ffprobe{exe_suffix}"

    if ffmpeg_target.exists() and ffprobe_target.exists():
        print(f"✅ Binários do FFmpeg já disponíveis em: {BIN_DIR}")
        return BIN_DIR

    # Check system PATH as source to copy
    sys_ffmpeg = shutil.which("ffmpeg")
    sys_ffprobe = shutil.which("ffprobe")
    if sys_ffmpeg and sys_ffprobe:
        print("📋 Copiando FFmpeg e FFprobe do PATH do sistema para bin/...")
        shutil.copy2(sys_ffmpeg, ffmpeg_target)
        shutil.copy2(sys_ffprobe, ffprobe_target)
        print("✅ Binários copiados com sucesso!")
        return BIN_DIR

    # Otherwise download
    url = FFMPEG_URLS.get(current_os)
    if not url:
        print(f"⚠️ Não há URL automática configurada para: {current_os}")
        return BIN_DIR

    archive_ext = ".zip" if url.endswith(".zip") else ".tar.xz"
    archive_path = BIN_DIR / f"ffmpeg_download{archive_ext}"

    try:
        download_file(url, archive_path)
        if current_os == "windows":
            stage_ffmpeg_windows(archive_path, BIN_DIR)
        elif current_os == "linux":
            stage_ffmpeg_linux(archive_path, BIN_DIR)
        archive_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"⚠️ Não foi possível baixar binários automaticamente ({e}).")

    return BIN_DIR


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    ensure_bundled_binaries(target)
