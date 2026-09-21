"""
Image converter engine.
Converts various image formats (including HEIC, RAW, AVIF, WebP, PNG)
to standard JPG/WebP with EXIF preservation, orientation fixing, and atomic writes.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

try:
    from PIL import Image, ImageFile, ImageOps
    ImageFile.LOAD_TRUNCATED_IMAGES = True
except ImportError:
    Image = None
    ImageOps = None

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

try:
    import rawpy
except Exception:
    rawpy = None


SUPPORTED_IMAGE_EXTENSIONS: Set[str] = {
    ".heic", ".heif", ".png", ".webp", ".avif",
    ".arw", ".cr2", ".nef", ".dng", ".raw",
    ".jpeg", ".jpg", ".jpe", ".bmp", ".tiff", ".tif"
}

RAW_EXTENSIONS: Set[str] = {".arw", ".cr2", ".nef", ".dng", ".raw"}


@dataclass
class ConversionResult:
    """Summary of the image conversion operation."""

    total_files: int = 0
    converted: int = 0
    skipped: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0
    error_details: List[Dict[str, str]] = None  # type: ignore

    def __post_init__(self):
        if self.error_details is None:
            self.error_details = []


class ImageConverter:
    """Engine responsible for converting images in batch."""

    def __init__(
        self,
        quality: int = 95,
        target_format: str = "JPG",
        workers: int = 8,
        skip_existing: bool = True,
        dry_run: bool = False,
        logger: Optional[logging.Logger] = None,
    ):
        self.quality = max(1, min(100, quality))
        self.target_format = target_format.upper()
        self.workers = max(1, workers)
        self.skip_existing = skip_existing
        self.dry_run = dry_run
        self.logger = logger or logging.getLogger("ImageConverter")

    def find_images(self, input_dir: Path) -> List[Path]:
        """Recursively lists all supported image files in input directory."""
        if not input_dir.exists():
            return []
        found: List[Path] = []
        for root, _, files in os.walk(input_dir):
            for file in files:
                ext = Path(file).suffix.lower()
                if ext in SUPPORTED_IMAGE_EXTENSIONS:
                    found.append(Path(root) / file)
        return sorted(found)

    def convert_single_image(
        self,
        src_path: Path,
        dest_path: Path,
    ) -> bool:
        """
        Converts a single image file to target format with atomic write and EXIF preservation.
        Returns True on success or skip, False on error.
        """
        if self.skip_existing and dest_path.exists() and dest_path.stat().st_size > 0:
            return True

        if self.dry_run:
            return True

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = dest_path.with_name(f"{dest_path.name}.tmp")

        try:
            stat = src_path.stat()
            orig_mtime = stat.st_mtime
            orig_atime = stat.st_atime

            ext = src_path.suffix.lower()
            exif_bytes = None

            if ext in RAW_EXTENSIONS and rawpy is not None:
                with rawpy.imread(str(src_path)) as raw:
                    rgb = raw.postprocess(use_camera_wb=True)
                    img = Image.fromarray(rgb)
            else:
                img = Image.open(src_path)
                try:
                    exif_bytes = img.info.get("exif")
                except Exception:
                    exif_bytes = None

                # Correct EXIF orientation
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass

                # Handle transparency (RGBA / LA / P)
                if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                    img = img.convert("RGBA")
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")

            # Save to temporary file first (atomic write)
            save_kwargs = {
                "quality": self.quality,
                "optimize": True,
            }
            if exif_bytes and self.target_format in ("JPG", "JPEG"):
                save_kwargs["exif"] = exif_bytes

            format_name = "JPEG" if self.target_format in ("JPG", "JPEG") else self.target_format
            img.save(temp_path, format=format_name, **save_kwargs)
            img.close()

            # Preserve original timestamp
            try:
                os.utime(temp_path, (orig_atime, orig_mtime))
            except Exception:
                pass

            # Atomic replace
            if dest_path.exists():
                dest_path.unlink()
            temp_path.rename(dest_path)
            return True

        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            self.logger.error(f"Erro convertendo {src_path.name}: {e}")
            raise e

    def run(
        self,
        input_dir: Path,
        output_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> ConversionResult:
        """Runs the conversion pipeline on all discovered images."""
        start_time = time.time()
        files = self.find_images(input_dir)
        result = ConversionResult(total_files=len(files))

        if not files:
            result.elapsed_seconds = time.time() - start_time
            return result

        ext_target = ".jpg" if self.target_format in ("JPG", "JPEG") else f".{self.target_format.lower()}"

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            future_to_file = {}
            for src_path in files:
                if cancel_check and cancel_check():
                    break
                try:
                    rel_path = src_path.relative_to(input_dir)
                except ValueError:
                    rel_path = Path(src_path.name)
                dest_path = (output_dir / rel_path).with_suffix(ext_target)

                if self.skip_existing and dest_path.exists() and dest_path.stat().st_size > 0:
                    result.skipped += 1
                    if progress_callback:
                        progress_callback(
                            result.converted + result.skipped + result.errors,
                            result.total_files,
                            f"Ignorado: {src_path.name}",
                        )
                    continue

                future = executor.submit(self.convert_single_image, src_path, dest_path)
                future_to_file[future] = (src_path, dest_path)

            for future in as_completed(future_to_file):
                if cancel_check and cancel_check():
                    break
                src_path, _ = future_to_file[future]
                try:
                    success = future.result()
                    if success:
                        result.converted += 1
                except Exception as e:
                    result.errors += 1
                    result.error_details.append({"file": str(src_path), "error": str(e)})

                if progress_callback:
                    processed = result.converted + result.skipped + result.errors
                    progress_callback(processed, result.total_files, src_path.name)

        result.elapsed_seconds = time.time() - start_time
        return result
