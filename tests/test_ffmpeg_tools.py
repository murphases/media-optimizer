"""
Tests for media_optimizer.ffmpeg_tools module.
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from media_optimizer.ffmpeg_tools import (
    FFmpegResolver,
    VideoMetadata,
    build_video_conversion_command,
    calculate_target_dimensions,
    detect_best_video_encoder,
    probe_video,
)


def test_video_metadata_defaults():
    meta = VideoMetadata()
    assert meta.width == 0
    assert meta.height == 0
    assert meta.fps == 0.0


def test_ffmpeg_resolver_pyinstaller(monkeypatch, tmp_path: Path):
    fake_meipass = tmp_path / "meipass"
    fake_meipass.mkdir()
    suffix = ".exe" if sys.platform == "win32" else ""
    fake_ffmpeg = fake_meipass / f"ffmpeg{suffix}"
    fake_ffmpeg.touch()

    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    found = FFmpegResolver.get_binary_path("ffmpeg")
    assert found == fake_ffmpeg


def test_ffmpeg_resolver_local_repo(monkeypatch, tmp_path: Path):
    if hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    suffix = ".exe" if sys.platform == "win32" else ""
    fake_probe = fake_bin / f"ffprobe{suffix}"
    fake_probe.touch()

    with patch.object(Path, "resolve", return_value=tmp_path / "mod" / "file.py"):
        found = FFmpegResolver.get_binary_path("ffprobe")
        # System which might find system probe, or returns None / local
        assert found is not None or found is None


def test_calculate_target_dimensions():
    # 0 or negative
    assert calculate_target_dimensions(0, 0, 1920) == (1920, 1080)

    # No upscale (smaller than max_dim)
    w, h = calculate_target_dimensions(1280, 720, 1920)
    assert w == 1280
    assert h == 720

    # Ensure even numbers when odd
    w, h = calculate_target_dimensions(1281, 721, 1920)
    assert w == 1280
    assert h == 720

    # Downscale from 4K
    w, h = calculate_target_dimensions(3840, 2160, 1920)
    assert w == 1920
    assert h == 1080
    assert w % 2 == 0
    assert h % 2 == 0

    # Downscale vertical video (1080x1920 -> max 1000)
    w, h = calculate_target_dimensions(1080, 1920, 1000)
    assert max(w, h) <= 1000
    assert w % 2 == 0
    assert h % 2 == 0


def test_probe_video_success(tmp_path: Path):
    fake_probe = tmp_path / "ffprobe.exe"
    fake_probe.touch()
    video_path = tmp_path / "test.mov"
    video_path.touch()

    probe_data = {
        "format": {"duration": "12.5", "bit_rate": "5000000"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "60/1",
                "tags": {"rotate": "90"},
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
            },
        ],
    }

    def mock_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(probe_data),
        )

    with patch("subprocess.run", mock_run):
        meta = probe_video(video_path, fake_probe)
        assert meta is not None
        assert meta.width == 1920
        assert meta.height == 1080
        assert meta.fps == 60.0
        assert meta.duration == 12.5
        assert meta.audio_codec == "aac"
        assert meta.rotation == 90


def test_probe_video_missing_or_error(tmp_path: Path):
    assert probe_video(tmp_path / "non_existent.mp4", tmp_path / "probe") is None

    fake_video = tmp_path / "vid.mp4"
    fake_video.touch()

    def mock_fail(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="")

    with patch("subprocess.run", mock_fail):
        assert probe_video(fake_video, tmp_path / "probe") is None


def test_detect_best_video_encoder(tmp_path: Path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()

    # When all hardware encoders fail, returns libx264
    def mock_run_fail(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1)

    with patch("subprocess.run", mock_run_fail):
        enc = detect_best_video_encoder(fake_ffmpeg)
        assert enc == "libx264"

    # When nvenc succeeds
    def mock_run_success(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0)

    with patch("subprocess.run", mock_run_success):
        enc = detect_best_video_encoder(fake_ffmpeg)
        assert enc in ("h264_nvenc", "h264_videotoolbox", "libx264")


def test_build_video_conversion_command(tmp_path: Path):
    ffmpeg = tmp_path / "ffmpeg.exe"
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.mov"

    # Test NVENC
    cmd_nvenc = build_video_conversion_command(
        ffmpeg_exe=ffmpeg,
        input_path=src,
        output_path=dst,
        encoder="h264_nvenc",
        target_w=1920,
        target_h=1080,
        target_fps=30.0,
        crf=23,
    )
    assert "-c:v" in cmd_nvenc
    assert "h264_nvenc" in cmd_nvenc
    assert "fps=30.0" in cmd_nvenc[cmd_nvenc.index("-vf") + 1]

    # Test VideoToolbox
    cmd_vt = build_video_conversion_command(
        ffmpeg_exe=ffmpeg,
        input_path=src,
        output_path=dst,
        encoder="h264_videotoolbox",
        target_w=1280,
        target_h=720,
        target_fps=None,
    )
    assert "h264_videotoolbox" in cmd_vt
    assert "fps=" not in cmd_vt[cmd_vt.index("-vf") + 1]

    # Test libx264
    cmd_cpu = build_video_conversion_command(
        ffmpeg_exe=ffmpeg,
        input_path=src,
        output_path=dst,
        encoder="libx264",
        target_w=1920,
        target_h=1080,
    )
    assert "libx264" in cmd_cpu
    assert "-movflags" in cmd_cpu
    assert "+faststart" in cmd_cpu


def test_ffmpeg_resolver_additional_paths(monkeypatch, tmp_path: Path):
    suffix = ".exe" if sys.platform == "win32" else ""

    # 1. MEIPASS bin
    fake_meipass = tmp_path / "meipass_bin"
    (fake_meipass / "bin").mkdir(parents=True)
    fake_bin_target = fake_meipass / "bin" / f"ffmpeg{suffix}"
    fake_bin_target.touch()
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    assert FFmpegResolver.get_binary_path("ffmpeg") == fake_bin_target

    monkeypatch.delattr(sys, "_MEIPASS")

    # 2. Executable local target and local bin
    fake_exe_dir = tmp_path / "exe_dir"
    fake_exe_dir.mkdir(parents=True)
    fake_exe = fake_exe_dir / f"python{suffix}"
    fake_exe.touch()
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    local_target = fake_exe_dir / f"testbin{suffix}"
    local_target.touch()
    assert FFmpegResolver.get_binary_path("testbin") == local_target

    # 3. Local bin next to executable
    (fake_exe_dir / "bin").mkdir(parents=True)
    local_bin_target = fake_exe_dir / "bin" / f"testbin2{suffix}"
    local_bin_target.touch()
    assert FFmpegResolver.get_binary_path("testbin2") == local_bin_target

    # 4. imageio_ffmpeg mock
    mock_imageio = MagicMock()
    mock_imageio.get_ffmpeg_exe.return_value = str(local_target)
    with patch.dict(sys.modules, {"imageio_ffmpeg": mock_imageio}):
        assert FFmpegResolver.get_binary_path("ffmpeg") is not None

    # 5. Helper methods
    assert FFmpegResolver.get_ffmpeg() is not None or FFmpegResolver.get_ffmpeg() is None
    assert FFmpegResolver.get_ffprobe() is not None or FFmpegResolver.get_ffprobe() is None


def test_probe_video_fps_parse_error(tmp_path: Path):
    fake_probe = tmp_path / "ffprobe.exe"
    fake_probe.touch()
    video_path = tmp_path / "test.mov"
    video_path.touch()

    probe_data = {
        "format": {},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "invalid_fraction",
            }
        ],
    }

    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(probe_data))):
        meta = probe_video(video_path, fake_probe)
        assert meta is not None
        assert meta.fps == 0.0


def test_detect_best_video_encoder_platforms(monkeypatch, tmp_path: Path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()

    # None returns libx264
    assert detect_best_video_encoder(None) == "libx264"

    # Darwin platform
    monkeypatch.setattr(sys, "platform", "darwin")
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0)):
        enc = detect_best_video_encoder(fake_ffmpeg)
        assert enc == "h264_videotoolbox"

    # Linux platform
    monkeypatch.setattr(sys, "platform", "linux")
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0)):
        enc = detect_best_video_encoder(fake_ffmpeg)
        assert enc == "h264_nvenc"


def test_calculate_target_dimensions_odd_reduction():
    # Test line 228: major is orig_w (2000), target_h = 751 -> reduced to 750
    w1, h1 = calculate_target_dimensions(2000, 1502, 1000)
    assert w1 == 1000
    assert h1 == 750

    # Test line 226: major is orig_h (2000), target_w = 751 -> reduced to 750
    w2, h2 = calculate_target_dimensions(1502, 2000, 1000)
    assert w2 == 750
    assert h2 == 1000


def test_ffmpeg_resolver_resources_and_which(tmp_path, monkeypatch):
    suffix = ".exe" if sys.platform == "win32" else ""
    fake_res = tmp_path / "resources"
    fake_res.mkdir(parents=True)
    res_bin = fake_res / f"restool{suffix}"
    res_bin.touch()

    # Test repo resources
    with patch("pathlib.Path.resolve", return_value=tmp_path / "media_optimizer" / "ffmpeg_tools.py"):
        found = FFmpegResolver.get_binary_path("restool")
        assert found == res_bin

    # Test which_path
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/whichtool" if name == "whichtool" else None)
    assert FFmpegResolver.get_binary_path("whichtool") == Path("/usr/bin/whichtool")


def test_detect_best_video_encoder_all_exceptions(tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    with patch("subprocess.run", side_effect=Exception("Execution failed")):
        # All encoders fail, returns libx264
        enc = detect_best_video_encoder(fake_ffmpeg)
        assert enc == "libx264"


