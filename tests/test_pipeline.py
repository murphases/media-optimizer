"""
Tests for media_optimizer.pipeline module.
"""

from unittest.mock import MagicMock, patch
import pytest

from media_optimizer.config import OptimizerSettings
from media_optimizer.hardware import SystemTelemetry
from media_optimizer.pipeline import PipelineOrchestrator, PipelineSummary


def test_pipeline_summary_defaults():
    summary = PipelineSummary()
    assert summary.total_elapsed_seconds == 0.0
    assert summary.total_saved_bytes == 0
    assert summary.cancelled is False


def test_pipeline_pause_and_resume():
    settings = OptimizerSettings()
    orchestrator = PipelineOrchestrator(settings=settings)

    assert orchestrator._is_paused.is_set()
    orchestrator.pause()
    assert not orchestrator._is_paused.is_set()
    orchestrator.resume()
    assert orchestrator._is_paused.is_set()


def test_pipeline_cancel():
    settings = OptimizerSettings()
    orchestrator = PipelineOrchestrator(settings=settings)

    assert not orchestrator.is_cancelled()
    orchestrator.cancel()
    assert orchestrator.is_cancelled()
    assert orchestrator._is_paused.is_set()


def test_pipeline_throttling_sleep(monkeypatch):
    settings = OptimizerSettings()
    mock_hw = MagicMock()
    mock_hw.get_telemetry.return_value = SystemTelemetry(is_throttling=True)

    orchestrator = PipelineOrchestrator(settings=settings, hardware_monitor=mock_hw)

    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    orchestrator._wait_if_paused_or_throttle()
    assert len(slept) == 1
    assert slept[0] == 0.5


def test_pipeline_run_full(temp_workspace, tmp_path):
    settings = OptimizerSettings(
        input_dir=str(temp_workspace["input_dir"]),
        converted_dir=str(tmp_path / "conv"),
        optimized_images_dir=str(tmp_path / "opt_img"),
        optimized_videos_dir=str(tmp_path / "opt_vid"),
        dry_run=True,
    )
    orchestrator = PipelineOrchestrator(settings=settings)

    stages_started = []
    progress_items = []

    def on_stage(name):
        stages_started.append(name)

    def on_prog(stage, curr, tot, name):
        progress_items.append((stage, curr, tot, name))

    summary = orchestrator.run_full_pipeline(
        on_stage_start=on_stage,
        progress_cb=on_prog,
    )

    assert len(stages_started) == 3
    assert summary.stage1_result is not None
    assert summary.stage2_result is not None
    assert summary.stage3_result is not None
    assert summary.cancelled is False
    assert summary.total_elapsed_seconds >= 0


def test_wait_if_paused_or_throttle_cancelled():
    settings = OptimizerSettings()
    orchestrator = PipelineOrchestrator(settings=settings)
    orchestrator.cancel()
    orchestrator._wait_if_paused_or_throttle()
    assert orchestrator.is_cancelled()


def test_pipeline_run_cancelled_early(temp_workspace, tmp_path):
    settings = OptimizerSettings(
        input_dir=str(temp_workspace["input_dir"]),
        converted_dir=str(tmp_path / "conv"),
        optimized_images_dir=str(tmp_path / "opt_img"),
        optimized_videos_dir=str(tmp_path / "opt_vid"),
    )
    orchestrator = PipelineOrchestrator(settings=settings)
    orchestrator.cancel()

    summary = orchestrator.run_full_pipeline()
    assert summary.cancelled is True


def test_pipeline_individual_stages_with_progress(temp_workspace, tmp_path):
    settings = OptimizerSettings(
        input_dir=str(temp_workspace["input_dir"]),
        converted_dir=str(tmp_path / "conv"),
        optimized_images_dir=str(tmp_path / "opt_img"),
        optimized_videos_dir=str(tmp_path / "opt_vid"),
        dry_run=True,
    )
    orchestrator = PipelineOrchestrator(settings=settings)

    calls = []
    def cb(c, t, n):
        calls.append((c, t, n))

    res1 = orchestrator.run_stage_1(progress_cb=cb)
    assert res1.total_files == 3

    # Create dummy images in converted_dir to test stage 2 progress
    (tmp_path / "conv").mkdir(parents=True, exist_ok=True)
    (tmp_path / "conv" / "dummy.jpg").touch()
    res2 = orchestrator.run_stage_2(progress_cb=cb)
    assert res2.total_files == 1

    res3 = orchestrator.run_stage_3(progress_cb=cb)
    assert res3.total_files == 1

