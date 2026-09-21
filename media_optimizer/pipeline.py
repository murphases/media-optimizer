"""
Pipeline orchestrator.
Executes conversion and optimization stages with pause, resume, cancel,
auto-throttling, and unified progress reporting.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from media_optimizer.config import OptimizerSettings
from media_optimizer.converter import ConversionResult, ImageConverter
from media_optimizer.hardware import HardwareMonitor, SystemTelemetry, format_bytes, format_time
from media_optimizer.image_optimizer import ImageOptimizer, OptimizationResult
from media_optimizer.video_optimizer import VideoOptimizationResult, VideoOptimizer


@dataclass
class PipelineSummary:
    """Consolidated metrics across all pipeline stages."""

    stage1_result: Optional[ConversionResult] = None
    stage2_result: Optional[OptimizationResult] = None
    stage3_result: Optional[VideoOptimizationResult] = None
    total_elapsed_seconds: float = 0.0
    total_orig_bytes: int = 0
    total_optimized_bytes: int = 0
    total_saved_bytes: int = 0
    total_savings_percent: float = 0.0
    cancelled: bool = False


class PipelineOrchestrator:
    """Coordinates multi-stage processing of image and video libraries."""

    def __init__(
        self,
        settings: OptimizerSettings,
        logger: Optional[logging.Logger] = None,
        hardware_monitor: Optional[HardwareMonitor] = None,
    ):
        self.settings = settings
        self.logger = logger or logging.getLogger("PipelineOrchestrator")
        self.hw_monitor = hardware_monitor or HardwareMonitor(
            memory_throttle_percent=settings.memory_threshold_percent
        )

        self._is_paused = threading.Event()
        self._is_paused.set()  # Unpaused initially
        self._cancel_requested = threading.Event()
        self._is_running = False

    def is_cancelled(self) -> bool:
        return self._cancel_requested.is_set()

    def cancel(self) -> None:
        """Signals pipeline to stop immediately."""
        self._cancel_requested.set()
        self._is_paused.set()  # Resume to allow loop to exit

    def pause(self) -> None:
        """Pauses processing."""
        self._is_paused.clear()

    def resume(self) -> None:
        """Resumes paused processing."""
        self._is_paused.set()

    def _wait_if_paused_or_throttle(self) -> None:
        """Checks pause status and handles memory auto-throttling."""
        self._is_paused.wait()
        if self._cancel_requested.is_set():
            return

        # Check telemetry for auto-throttling
        telemetry = self.hw_monitor.get_telemetry()
        if telemetry.is_throttling:
            time.sleep(0.5)

    def run_stage_1(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> ConversionResult:
        """Executes Stage 1: Convert raw/diverse images to standard JPG."""
        converter = ImageConverter(
            quality=self.settings.convert_quality,
            target_format=self.settings.convert_target_format,
            workers=self.settings.convert_workers,
            skip_existing=self.settings.skip_existing,
            dry_run=self.settings.dry_run,
            logger=self.logger,
        )

        def checked_progress(curr: int, tot: int, name: str):
            self._wait_if_paused_or_throttle()
            if progress_cb:
                progress_cb(curr, tot, name)

        return converter.run(
            input_dir=Path(self.settings.input_dir),
            output_dir=Path(self.settings.converted_dir),
            progress_callback=checked_progress,
            cancel_check=self.is_cancelled,
        )

    def run_stage_2(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> OptimizationResult:
        """Executes Stage 2: Optimize and resize images."""
        optimizer = ImageOptimizer(
            quality=self.settings.opt_image_quality,
            max_dim=self.settings.opt_image_max_dim,
            progressive=self.settings.opt_image_progressive,
            workers=self.settings.opt_image_workers,
            skip_existing=self.settings.skip_existing,
            dry_run=self.settings.dry_run,
            logger=self.logger,
        )

        def checked_progress(curr: int, tot: int, name: str):
            self._wait_if_paused_or_throttle()
            if progress_cb:
                progress_cb(curr, tot, name)

        return optimizer.run(
            input_dir=Path(self.settings.converted_dir),
            output_dir=Path(self.settings.optimized_images_dir),
            progress_callback=checked_progress,
            cancel_check=self.is_cancelled,
        )

    def run_stage_3(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> VideoOptimizationResult:
        """Executes Stage 3: Optimize videos."""
        optimizer = VideoOptimizer(
            max_dim=self.settings.opt_video_max_dim,
            max_fps=self.settings.opt_video_max_fps,
            target_format=self.settings.opt_video_format,
            codec=self.settings.opt_video_codec,
            crf=self.settings.opt_video_crf,
            audio_bitrate=self.settings.opt_video_audio_bitrate,
            workers=self.settings.opt_video_workers,
            skip_existing=self.settings.skip_existing,
            dry_run=self.settings.dry_run,
            logger=self.logger,
        )

        def checked_progress(curr: int, tot: int, name: str):
            self._wait_if_paused_or_throttle()
            if progress_cb:
                progress_cb(curr, tot, name)

        return optimizer.run(
            input_dir=Path(self.settings.input_dir),
            output_dir=Path(self.settings.optimized_videos_dir),
            progress_callback=checked_progress,
            cancel_check=self.is_cancelled,
        )

    def run_full_pipeline(
        self,
        on_stage_start: Optional[Callable[[str], None]] = None,
        progress_cb: Optional[Callable[[str, int, int, str], None]] = None,
    ) -> PipelineSummary:
        """Executes full sequence: Stage 1 -> Stage 2 -> Stage 3."""
        start_time = time.time()
        self._is_paused.set()
        self._is_running = True

        summary = PipelineSummary()

        # Stage 1
        if not self.is_cancelled():
            if on_stage_start:
                on_stage_start("1. Conversão de Imagens para JPG")
            summary.stage1_result = self.run_stage_1(
                progress_cb=lambda c, t, n: progress_cb("Conversão de Imagens", c, t, n) if progress_cb else None
            )

        # Stage 2
        if not self.is_cancelled():
            if on_stage_start:
                on_stage_start("2. Otimização de Imagens (Resize & Compressão)")
            summary.stage2_result = self.run_stage_2(
                progress_cb=lambda c, t, n: progress_cb("Otimização de Imagens", c, t, n) if progress_cb else None
            )

        # Stage 3
        if not self.is_cancelled():
            if on_stage_start:
                on_stage_start("3. Otimização de Vídeos")
            summary.stage3_result = self.run_stage_3(
                progress_cb=lambda c, t, n: progress_cb("Otimização de Vídeos", c, t, n) if progress_cb else None
            )

        summary.cancelled = self.is_cancelled()
        summary.total_elapsed_seconds = time.time() - start_time

        # Calculate totals
        if summary.stage2_result:
            summary.total_orig_bytes += summary.stage2_result.orig_bytes
            summary.total_optimized_bytes += summary.stage2_result.optimized_bytes
            summary.total_saved_bytes += summary.stage2_result.saved_bytes

        if summary.stage3_result:
            summary.total_orig_bytes += summary.stage3_result.orig_bytes
            summary.total_optimized_bytes += summary.stage3_result.optimized_bytes
            summary.total_saved_bytes += summary.stage3_result.saved_bytes

        if summary.total_orig_bytes > 0:
            summary.total_savings_percent = round(
                (summary.total_saved_bytes / summary.total_orig_bytes) * 100, 2
            )

        self._is_running = False
        return summary
