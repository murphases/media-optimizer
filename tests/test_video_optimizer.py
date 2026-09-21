"""
Tests for media_optimizer.video_optimizer module.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from media_optimizer.ffmpeg_tools import VideoMetadata
from media_optimizer.video_optimizer import VideoOptimizationResult, VideoOptimizer


def test_video_optimization_result_defaults():
    res = VideoOptimizationResult()
    assert res.total_files == 0
    assert res.saved_bytes == 0
    assert res.error_details == []


def test_find_videos(temp_workspace):
    optimizer = VideoOptimizer()
    videos = optimizer.find_videos(temp_workspace["input_dir"])
    assert len(videos) == 1
    assert videos[0].name == "video_teste.mov"

    assert optimizer.find_videos(Path("/non/existent/dir")) == []


def test_optimize_video_dry_run_and_skip(temp_workspace, tmp_path):
    # Dry run
    optimizer_dry = VideoOptimizer(dry_run=True)
    dest_dry = tmp_path / "dry.mov"
    orig_sz, new_sz = optimizer_dry.optimize_single_video(temp_workspace["video"], dest_dry)
    assert not dest_dry.exists()
    assert new_sz < orig_sz

    # Skip existing
    dest_skip = tmp_path / "skip.mov"
    dest_skip.write_bytes(b"existing_video_bytes")
    optimizer_skip = VideoOptimizer(skip_existing=True)
    orig_sz2, new_sz2 = optimizer_skip.optimize_single_video(temp_workspace["video"], dest_skip)
    assert new_sz2 == len(b"existing_video_bytes")


def test_optimize_video_missing_ffmpeg(temp_workspace, tmp_path):
    optimizer = VideoOptimizer(ffmpeg_path=None)
    optimizer.ffmpeg_exe = None
    with pytest.raises(RuntimeError, match="FFmpeg não encontrado"):
        optimizer.optimize_single_video(temp_workspace["video"], tmp_path / "out.mov")


def test_optimize_video_success(temp_workspace, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    optimizer = VideoOptimizer(ffmpeg_path=fake_ffmpeg, codec="libx264")

    mock_proc = MagicMock()
    mock_proc.pid = 9999
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    dest = tmp_path / "out_success.mov"

    # Simulate creation of the temp file inside Popen
    def side_effect_popen(cmd, *args, **kwargs):
        temp_file = Path(cmd[-1])
        temp_file.write_bytes(b"compressed_video_result")
        return mock_proc

    with patch("subprocess.Popen", side_effect=side_effect_popen), \
         patch("media_optimizer.video_optimizer.probe_video") as mock_probe:
        mock_probe.return_value = VideoMetadata(width=1920, height=1080, fps=60.0)

        orig_sz, new_sz = optimizer.optimize_single_video(temp_workspace["video"], dest)
        assert dest.exists()
        assert dest.read_bytes() == b"compressed_video_result"


def test_optimize_video_nvenc_fallback_to_libx264(temp_workspace, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    optimizer = VideoOptimizer(ffmpeg_path=fake_ffmpeg, codec="h264_nvenc")

    proc_fail = MagicMock(pid=1001, returncode=1)
    proc_fail.communicate.return_value = (b"", b"NVENC failed")

    proc_success = MagicMock(pid=1002, returncode=0)
    proc_success.communicate.return_value = (b"", b"")

    call_count = [0]
    def side_effect_popen(cmd, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return proc_fail
        # Second call (fallback) creates file
        temp_file = Path(cmd[-1])
        temp_file.write_bytes(b"fallback_video_ok")
        return proc_success

    dest = tmp_path / "fallback.mov"

    with patch("subprocess.Popen", side_effect=side_effect_popen), \
         patch("media_optimizer.video_optimizer.probe_video", return_value=None):
        orig_sz, new_sz = optimizer.optimize_single_video(temp_workspace["video"], dest)
        assert dest.exists()
        assert dest.read_bytes() == b"fallback_video_ok"
        assert call_count[0] == 2


def test_optimize_video_fatal_failure(temp_workspace, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    optimizer = VideoOptimizer(ffmpeg_path=fake_ffmpeg, codec="libx264")

    mock_proc = MagicMock(pid=9999, returncode=1)
    mock_proc.communicate.return_value = (b"", b"Fatal encoding error")

    with patch("subprocess.Popen", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="FFmpeg falhou"):
            optimizer.optimize_single_video(temp_workspace["video"], tmp_path / "fatal.mov")


def test_video_optimizer_run_full(temp_workspace, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    optimizer = VideoOptimizer(ffmpeg_path=fake_ffmpeg, workers=2)

    mock_proc = MagicMock(pid=9999, returncode=0)
    mock_proc.communicate.return_value = (b"", b"")

    def side_effect_popen(cmd, *args, **kwargs):
        Path(cmd[-1]).write_bytes(b"vid_ok")
        return mock_proc

    with patch("subprocess.Popen", side_effect=side_effect_popen):
        res = optimizer.run(
            input_dir=temp_workspace["input_dir"],
            output_dir=tmp_path / "out",
        )
        assert res.total_files == 1
        assert res.optimized == 1
        assert res.orig_bytes > 0


def test_video_optimizer_run_skips(temp_workspace, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    optimizer = VideoOptimizer(ffmpeg_path=fake_ffmpeg, workers=2, skip_existing=True)

    out_dir = tmp_path / "out_skips"
    out_dir.mkdir(parents=True)
    existing_dest = out_dir / "video_teste.mov"
    existing_dest.write_bytes(b"already_processed_mov")

    progress_messages = []
    res = optimizer.run(
        input_dir=temp_workspace["input_dir"],
        output_dir=out_dir,
        progress_callback=lambda c, t, n: progress_messages.append(n),
    )
    assert res.skipped == 1
    assert res.optimized == 0
    assert any("Ignorado" in msg for msg in progress_messages)


def test_video_optimizer_run_errors(temp_workspace, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    optimizer = VideoOptimizer(ffmpeg_path=fake_ffmpeg, workers=2)

    with patch.object(VideoOptimizer, "optimize_single_video", side_effect=RuntimeError("FFmpeg crash")):
        res = optimizer.run(
            input_dir=temp_workspace["input_dir"],
            output_dir=tmp_path / "out_err",
        )
        assert res.errors == 1
        assert len(res.error_details) == 1


def test_video_optimizer_cancel_and_empty(tmp_path):
    optimizer = VideoOptimizer()
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    res_empty = optimizer.run(empty_dir, tmp_path / "out")
    assert res_empty.total_files == 0

    full_dir = tmp_path / "full"
    full_dir.mkdir()
    (full_dir / "clip.mov").touch()
    res_cancel = optimizer.run(
        full_dir,
        tmp_path / "out",
        cancel_check=lambda: True,
    )
    assert res_cancel.optimized == 0


def test_video_optimize_temp_cleanup_on_error(temp_workspace, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    optimizer = VideoOptimizer(ffmpeg_path=fake_ffmpeg)

    dest = tmp_path / "fail_vid.mov"

    def side_effect_fail(cmd, *args, **kwargs):
        temp_file = Path(cmd[-1])
        temp_file.write_bytes(b"broken_temp_bytes")
        raise RuntimeError("Subprocess exploded")

    with patch("subprocess.Popen", side_effect=side_effect_fail), \
         patch("media_optimizer.video_optimizer.probe_video", return_value=None):
        with pytest.raises(RuntimeError):
            optimizer.optimize_single_video(temp_workspace["video"], dest)
        assert not (tmp_path / "fail_vid.mov.tmp.mov").exists()


def test_video_optimizer_overwrite_existing(temp_workspace, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    optimizer = VideoOptimizer(ffmpeg_path=fake_ffmpeg, skip_existing=False)

    dest = tmp_path / "overwrite_vid.mov"
    dest.write_bytes(b"prior_video_data")

    mock_proc = MagicMock(pid=123, returncode=0)
    mock_proc.communicate.return_value = (b"", b"")

    def side_effect_p(cmd, *args, **kwargs):
        Path(cmd[-1]).write_bytes(b"new_video_data")
        return mock_proc

    with patch("subprocess.Popen", side_effect=side_effect_p), \
         patch("media_optimizer.video_optimizer.probe_video", return_value=None):
        orig_sz, new_sz = optimizer.optimize_single_video(temp_workspace["video"], dest)
        assert dest.exists()
        assert dest.read_bytes() == b"new_video_data"


def test_video_optimizer_relpath_exception(tmp_path):
    in_dir = tmp_path / "vid_in_custom"
    in_dir.mkdir()
    (in_dir / "v1.mov").touch()

    optimizer = VideoOptimizer()
    with patch.object(VideoOptimizer, "optimize_single_video", return_value=(200, 100)):
        with patch.object(Path, "relative_to", side_effect=ValueError("Different drive")):
            res = optimizer.run(in_dir, tmp_path / "out")
            assert res.total_files == 1
            assert res.optimized == 1


def test_video_optimizer_cancel_during_as_completed(tmp_path):
    in_dir = tmp_path / "vid_in_cancel"
    in_dir.mkdir()
    (in_dir / "v1.mov").touch()
    (in_dir / "v2.mov").touch()

    optimizer = VideoOptimizer(workers=1)

    cancel_flag = [False]
    def mock_opt(*args, **kwargs):
        cancel_flag[0] = True
        return (200, 100)

    with patch.object(VideoOptimizer, "optimize_single_video", side_effect=mock_opt):
        res = optimizer.run(in_dir, tmp_path / "out", cancel_check=lambda: cancel_flag[0])
        assert res.total_files == 2



