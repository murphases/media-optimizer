"""
Image optimization engine.
Resizes high-resolution images (downscale without upscale), optimizes Huffman tables,
generates progressive JPEGs, preserves EXIF, and reports space savings.
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
    LANCZOS_FILTER = getattr(Image.Resampling, "LANCZOS", getattr(Image, "LANCZOS", 1))
except ImportError:
    Image = None
    ImageOps = None
    LANCZOS_FILTER = 1


SUPPORTED_OPTIMIZE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".jpe", ".webp"}


@dataclass
class OptimizationResult:
    """Summary of the image optimization stage."""

    total_files: int = 0
    optimized: int = 0
    skipped: int = 0
    errors: int = 0
    orig_bytes: int = 0
    optimized_bytes: int = 0
    saved_bytes: int = 0
    savings_percent: float = 0.0
    elapsed_seconds: float = 0.0
    error_details: List[Dict[str, str]] = None  # type: ignore

    def __post_init__(self):
        if self.error_details is None:
            self.error_details = []


class ImageOptimizer:
    """Optimizes and downsizes images for storage and web delivery."""

    def __init__(
        self,
        quality: int = 70,
        max_dim: int = 1350,
        progressive: bool = True,
        workers: int = 8,
        skip_existing: bool = True,
        dry_run: bool = False,
        logger: Optional[logging.Logger] = None,
    ):
        self.quality = max(1, min(100, quality))
        self.max_dim = max_dim
        self.progressive = progressive
        self.workers = max(1, workers)
        self.skip_existing = skip_existing
        self.dry_run = dry_run
        self.logger = logger or logging.getLogger("ImageOptimizer")

    def find_images(self, input_dir: Path) -> List[Path]:
        """Lists all JPEG/WebP files in directory."""
        if not input_dir.exists():
            return []
        found: List[Path] = []
        for root, _, files in os.walk(input_dir):
            for file in files:
                if Path(file).suffix.lower() in SUPPORTED_OPTIMIZE_EXTENSIONS:
                    found.append(Path(root) / file)
        return sorted(found)

    def optimize_single_image(
        self,
        src_path: Path,
        dest_path: Path,
    ) -> tuple[int, int]:
        """
        Optimizes a single image file.
        Returns tuple of (original_size_bytes, optimized_size_bytes).
        """
        orig_size = src_path.stat().st_size
        if self.skip_existing and dest_path.exists() and dest_path.stat().st_size > 0:
            return (orig_size, dest_path.stat().st_size)

        if self.dry_run:
            return (orig_size, int(orig_size * 0.45))

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = dest_path.with_name(f"{dest_path.name}.tmp")

        try:
            stat = src_path.stat()
            orig_mtime = stat.st_mtime
            orig_atime = stat.st_atime

            with Image.open(src_path) as img:
                exif_bytes = None
                try:
                    exif_bytes = img.info.get("exif")
                except Exception:
                    pass

                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass

                if img.mode != "RGB":
                    img = img.convert("RGB")

                width, height = img.size
                major_dim = max(width, height)

                # Resize if exceeding max_dim (no upscale)
                if major_dim > self.max_dim:
                    scale = self.max_dim / float(major_dim)
                    new_w = max(1, int(width * scale))
                    new_h = max(1, int(height * scale))
                    img = img.resize((new_w, new_h), resample=LANCZOS_FILTER)

                save_kwargs = {
                    "quality": self.quality,
                    "optimize": True,
                    "progressive": self.progressive,
                }
                if exif_bytes:
                    save_kwargs["exif"] = exif_bytes

                img.save(temp_path, format="JPEG", **save_kwargs)

            try:
                os.utime(temp_path, (orig_atime, orig_mtime))
            except Exception:
                pass

            if dest_path.exists():
                dest_path.unlink()
            temp_path.rename(dest_path)

            new_size = dest_path.stat().st_size
            return (orig_size, new_size)

        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            self.logger.error(f"Erro otimizando {src_path.name}: {e}")
            raise e

    def run(
        self,
        input_dir: Path,
        output_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> OptimizationResult:
        """Runs optimization on all matching images."""
        start_time = time.time()
        files = self.find_images(input_dir)
        result = OptimizationResult(total_files=len(files))

        if not files:
            result.elapsed_seconds = time.time() - start_time
            return result

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            future_to_file = {}
            for src_path in files:
                if cancel_check and cancel_check():
                    break
                try:
                    rel_path = src_path.relative_to(input_dir)
                except ValueError:
                    rel_path = Path(src_path.name)
                dest_path = (output_dir / rel_path).with_suffix(".jpg")

                if self.skip_existing and dest_path.exists() and dest_path.stat().st_size > 0:
                    result.skipped += 1
                    orig_sz = src_path.stat().st_size
                    new_sz = dest_path.stat().st_size
                    result.orig_bytes += orig_sz
                    result.optimized_bytes += new_sz
                    if progress_callback:
                        progress_callback(
                            result.optimized + result.skipped + result.errors,
                            result.total_files,
                            f"Ignorado: {src_path.name}",
                        )
                    continue

                future = executor.submit(self.optimize_single_image, src_path, dest_path)
                future_to_file[future] = (src_path, dest_path)

            for future in as_completed(future_to_file):
                if cancel_check and cancel_check():
                    break
                src_path, _ = future_to_file[future]
                try:
                    orig_sz, new_sz = future.result()
                    result.optimized += 1
                    result.orig_bytes += orig_sz
                    result.optimized_bytes += new_sz
                except Exception as e:
                    result.errors += 1
                    result.error_details.append({"file": str(src_path), "error": str(e)})

                if progress_callback:
                    processed = result.optimized + result.skipped + result.errors
                    progress_callback(processed, result.total_files, src_path.name)

        result.saved_bytes = max(0, result.orig_bytes - result.optimized_bytes)
        if result.orig_bytes > 0:
            result.savings_percent = round((result.saved_bytes / result.orig_bytes) * 100, 2)
        result.elapsed_seconds = time.time() - start_time
        return result
