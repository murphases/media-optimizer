"""
Pytest fixtures and test environment configuration.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from PIL import Image


@pytest.fixture
def temp_workspace(tmp_path: Path) -> dict[str, Path]:
    """Creates a temporary workspace structure with test files."""
    input_dir = tmp_path / "Originais"
    input_dir.mkdir(parents=True, exist_ok=True)

    converted_dir = tmp_path / "Convertidos" / "JPG"
    opt_images_dir = tmp_path / "Otimizadas" / "JPG"
    opt_videos_dir = tmp_path / "Otimizadas" / "MOV"
    logs_dir = tmp_path / "logs"

    # Create dummy images
    # 1. Standard RGB image
    img1 = Image.new("RGB", (2000, 1000), color="blue")
    img1_path = input_dir / "foto_grande.jpg"
    img1.save(img1_path, "JPEG")

    # 2. Small RGBA image (transparency)
    img2 = Image.new("RGBA", (500, 500), color=(255, 0, 0, 128))
    img2_path = input_dir / "transparente.png"
    img2.save(img2_path, "PNG")

    # 3. Small image (under limits)
    img3 = Image.new("RGB", (800, 600), color="green")
    img3_path = input_dir / "foto_pequena.jpg"
    img3.save(img3_path, "JPEG")

    # 4. Dummy video file
    vid_path = input_dir / "video_teste.mov"
    vid_path.write_bytes(b"dummy_video_content_data_1234567890")

    return {
        "root": tmp_path,
        "input_dir": input_dir,
        "converted_dir": converted_dir,
        "opt_images_dir": opt_images_dir,
        "opt_videos_dir": opt_videos_dir,
        "logs_dir": logs_dir,
        "img_large": img1_path,
        "img_rgba": img2_path,
        "img_small": img3_path,
        "video": vid_path,
    }
