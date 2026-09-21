"""
Video optimization engine.
Resizes video (1080p max), dynamically caps FPS (>30 -> 30, <=30 kept),
leverages hardware acceleration (NVENC, VideoToolbox, VAAPI) with CPU fallback,
and preserves audio fidelity and original timestamps.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from media_optimizer.ffmpeg_tools import (
    FFmpegResolver,
    build_video_conversion_command,
    calculate_target_dimensions,
    detect_best_video_encoder,
    probe_video,
)
from media_optimizer.hardware import HardwareMonitor


SUPPORTED_VIDEO_EXTENSIONS: Set[str] = {
    ".mov", ".mp4", ".m4v", ".avi", ".mkv",
    ".3gp", ".wmv", ".webm", ".flv", ".mts", ".m2ts", ".ts"
}


@dataclass
class VideoOptimizationResult:
    """Summary of the video optimization stage."""

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


class VideoOptimizer:
    """Engine for compressing and re-encoding video collections."""

    def __init__(
        self,
        max_dim: int = 1920,
        max_fps: int = 30,
        target_format: str = "mov",
        codec: str = "auto",
        crf: int = 23,
        audio_bitrate: str = "128k",
        workers: int = 2,
        skip_existing: bool = True,
        dry_run: bool = False,
        ffmpeg_path: Optional[Path] = None,
        ffprobe_path: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.max_dim = max_dim
        self.max_fps = max_fps
        self.target_format = target_format.lower().lstrip(".")
        self.codec_preference = codec
        self.crf = crf
        self.audio_bitrate = audio_bitrate
        self.workers = max(1, workers)
        self.skip_existing = skip_existing
        self.dry_run = dry_run
        self.logger = logger or logging.getLogger("VideoOptimizer")

        self.ffmpeg_exe = ffmpeg_path or FFmpegResolver.get_ffmpeg()
        self.ffprobe_exe = ffprobe_path or FFmpegResolver.get_ffprobe()

        if self.codec_preference == "auto":
            self.active_encoder = detect_best_video_encoder(self.ffmpeg_exe)
        else:
            self.active_encoder = self.codec_preference

    def find_videos(self, input_dir: Path) -> List[Path]:
        """Lists all supported video files."""
        if not input_dir.exists():
            return []
        found: List[Path] = []
        for root, _, files in os.walk(input_dir):
            for file in files:
                if Path(file).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                    found.append(Path(root) / file)
        return sorted(found)

    def optimize_single_video(
        self,
        src_path: Path,
        dest_path: Path,
    ) -> tuple[int, int]:
        """
        Optimizes a single video file using FFmpeg with atomic output.
        Returns tuple of (original_size_bytes, optimized_size_bytes).
        """
        orig_size = src_path.stat().st_size
        if self.skip_existing and dest_path.exists() and dest_path.stat().st_size > 0:
            return (orig_size, dest_path.stat().st_size)

        if self.dry_run:
            return (orig_size, int(orig_size * 0.4))

        if not self.ffmpeg_exe:
            raise RuntimeError("FFmpeg não encontrado no sistema ou empacotamento.")

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = dest_path.with_name(f"{dest_path.name}.tmp.{self.target_format}")

        try:
            stat = src_path.stat()
            orig_mtime = stat.st_mtime
            orig_atime = stat.st_atime

            # Probe video metadata
            meta = probe_video(src_path, self.ffprobe_exe)
            if meta and meta.width > 0 and meta.height > 0:
                target_w, target_h = calculate_target_dimensions(meta.width, meta.height, self.max_dim)
                target_fps = self.max_fps if meta.fps > self.max_fps else None
            else:
                # Fallback conservative values
                target_w, target_h = (1920, 1080)
                target_fps = self.max_fps

            cmd = build_video_conversion_command(
                ffmpeg_exe=self.ffmpeg_exe,
                input_path=src_path,
                output_path=temp_path,
                encoder=self.active_encoder,
                target_w=target_w,
                target_h=target_h,
                target_fps=target_fps,
                crf=self.crf,
                audio_bitrate=self.audio_bitrate,
            )

            startupinfo = None
            if sys.platform == "win32" and hasattr(subprocess, "STARTUPINFO"):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
            )
            HardwareMonitor.adjust_process_priority(proc.pid)

            _, stderr = proc.communicate()

            # If hardware encoder failed, try fallback to libx264
            if proc.returncode != 0 and self.active_encoder != "libx264":
                self.logger.warning(
                    f"Falha no encoder {self.active_encoder} em {src_path.name}. Tentando fallback para libx264..."
                )
                cmd = build_video_conversion_command(
                    ffmpeg_exe=self.ffmpeg_exe,
                    input_path=src_path,
                    output_path=temp_path,
                    encoder="libx264",
                    target_w=target_w,
                    target_h=target_h,
                    target_fps=target_fps,
                    crf=self.crf,
                    audio_bitrate=self.audio_bitrate,
                )
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                )
                HardwareMonitor.adjust_process_priority(proc.pid)
                _, stderr = proc.communicate()
                if proc.returncode == 0:
                    self.active_encoder = "libx264"

            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"FFmpeg falhou (código {proc.returncode}): {err_msg[:300]}")

            # Preserve original timestamps
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
            self.logger.error(f"Erro otimizando vídeo {src_path.name}: {e}")
            raise e

    def run(
        self,
        input_dir: Path,
        output_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> VideoOptimizationResult:
        """Runs the video optimization pipeline."""
        start_time = time.time()
        files = self.find_videos(input_dir)
        result = VideoOptimizationResult(total_files=len(files))

        if not files:
            result.elapsed_seconds = time.time() - start_time
            return result

        ext_target = f".{self.target_format}"

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

                future = executor.submit(self.optimize_single_video, src_path, dest_path)
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
