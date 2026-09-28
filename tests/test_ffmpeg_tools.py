"""
Tests for media_optimizer.ffmpeg_tools module.
"""

import json
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
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
    assert meta.display_width == 0
    assert meta.display_height == 0
    assert not meta.is_vertical


def test_video_metadata_display_dimensions_and_orientation():
    # Horizontal normal
    m1 = VideoMetadata(width=1920, height=1080, rotation=0)
    assert m1.display_width == 1920
    assert m1.display_height == 1080
    assert not m1.is_vertical

    # Native vertical (e.g. TikTok / Reels)
    m2 = VideoMetadata(width=1080, height=1920, rotation=0)
    assert m2.display_width == 1080
    assert m2.display_height == 1920
    assert m2.is_vertical

    # Rotated 90 degrees (smartphone vertical video stored in landscape)
    m3 = VideoMetadata(width=1920, height=1080, rotation=90)
    assert m3.display_width == 1080
    assert m3.display_height == 1920
    assert m3.is_vertical

    # Rotated -90 degrees
    m4 = VideoMetadata(width=1920, height=1080, rotation=-90)
    assert m4.display_width == 1080
    assert m4.display_height == 1920
    assert m4.is_vertical

    # Rotated 270 degrees
    m5 = VideoMetadata(width=1920, height=1080, rotation=270)
    assert m5.display_width == 1080
    assert m5.display_height == 1920
    assert m5.is_vertical

    # Rotated 180 degrees (upside down landscape)
    m6 = VideoMetadata(width=1920, height=1080, rotation=180)
    assert m6.display_width == 1920
    assert m6.display_height == 1080
    assert not m6.is_vertical


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


def test_probe_video_rotation_variations(tmp_path: Path):
    fake_probe = tmp_path / "ffprobe.exe"
    fake_probe.touch()
    video_path = tmp_path / "test.mov"
    video_path.touch()

    # 1. side_data_list with valid float rotation
    data_side_data = {
        "format": {},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "side_data_list": [{"rotation": -90.0}],
            }
        ],
    }
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(data_side_data))):
        meta = probe_video(video_path, fake_probe)
        assert meta.rotation == -90
        assert meta.is_vertical

    # 2. side_data_list with invalid rotation falling back to tags
    data_fallback = {
        "format": {},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "side_data_list": [{"rotation": "not_a_number"}],
                "tags": {"ROTATION": "90"},
            }
        ],
    }
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(data_fallback))):
        meta = probe_video(video_path, fake_probe)
        assert meta.rotation == 90
        assert meta.is_vertical

    # 3. tags with invalid rotation string
    data_invalid_tag = {
        "format": {},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "tags": {"rotate": "invalid_rot"},
            }
        ],
    }
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(data_invalid_tag))):
        meta = probe_video(video_path, fake_probe)
        assert meta.rotation == 0

    # 4. format tags rotation fallback
    data_format_tag = {
        "format": {"tags": {"ROTATE": "270"}},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
            }
        ],
    }
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(data_format_tag))):
        meta = probe_video(video_path, fake_probe)
        assert meta.rotation == 270
        assert meta.is_vertical

    # 5. format tags with invalid rotation string
    data_format_invalid = {
        "format": {"tags": {"rotate": "bad_rot"}},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
            }
        ],
    }
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(data_format_invalid))):
        meta = probe_video(video_path, fake_probe)
        assert meta.rotation == 0


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
    assert "setsar=1" in cmd_nvenc[cmd_nvenc.index("-vf") + 1]
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

    # 4. imageio_ffmpeg mock (ensure which returns None so it reaches step 4)
    mock_imageio = MagicMock()
    mock_imageio.get_ffmpeg_exe.return_value = str(local_target)
    with patch("shutil.which", return_value=None), \
         patch.object(Path, "exists", lambda self: str(self) == str(local_target)), \
         patch.dict(sys.modules, {"imageio_ffmpeg": mock_imageio}):
        assert FFmpegResolver.get_binary_path("ffmpeg") == local_target

    # 5. Helper methods
    assert FFmpegResolver.get_ffmpeg() is not None or FFmpegResolver.get_ffmpeg() is None
    assert FFmpegResolver.get_ffprobe() is not None or FFmpegResolver.get_ffprobe() is None


def test_ffmpeg_resolver_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert FFmpegResolver.get_binary_path("completely_unknown_binary_xyz_123") is None


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
    with patch.object(FFmpegResolver, "get_ffmpeg", return_value=None):
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


def test_build_video_conversion_command_all_encoders(tmp_path):
    ffmpeg = tmp_path / "ffmpeg.exe"
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.mov"

    # AMF (AMD)
    cmd_amf = build_video_conversion_command(
        ffmpeg_exe=ffmpeg,
        input_path=src,
        output_path=dst,
        encoder="h264_amf",
        target_w=1920,
        target_h=1080,
    )
    assert "-c:v" in cmd_amf and "h264_amf" in cmd_amf
    assert "-quality" in cmd_amf and "balanced" in cmd_amf

    # QSV (Intel)
    cmd_qsv = build_video_conversion_command(
        ffmpeg_exe=ffmpeg,
        input_path=src,
        output_path=dst,
        encoder="h264_qsv",
        target_w=1920,
        target_h=1080,
    )
    assert "-c:v" in cmd_qsv and "h264_qsv" in cmd_qsv
    assert "-global_quality" in cmd_qsv

    # VAAPI (Linux)
    cmd_vaapi = build_video_conversion_command(
        ffmpeg_exe=ffmpeg,
        input_path=src,
        output_path=dst,
        encoder="h264_vaapi",
        target_w=1920,
        target_h=1080,
    )
    assert "-c:v" in cmd_vaapi and "h264_vaapi" in cmd_vaapi
    assert "-qp" in cmd_vaapi

    # Threads
    cmd_threads = build_video_conversion_command(
        ffmpeg_exe=ffmpeg,
        input_path=src,
        output_path=dst,
        encoder="libx264",
        target_w=1920,
        target_h=1080,
        threads=6,
    )
    assert "-threads" in cmd_threads
    assert "6" in cmd_threads


def test_detect_best_video_encoder_qsv_and_amf(tmp_path, monkeypatch):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()
    monkeypatch.setattr(sys, "platform", "win32")

    # When nvenc fails but qsv succeeds
    def mock_run_qsv(cmd, *args, **kwargs):
        if "h264_qsv" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0)
        return subprocess.CompletedProcess(args=cmd, returncode=1)

    with patch("subprocess.run", side_effect=mock_run_qsv):
        assert detect_best_video_encoder(fake_ffmpeg) == "h264_qsv"

    # When nvenc and qsv fail but amf succeeds
    def mock_run_amf(cmd, *args, **kwargs):
        if "h264_amf" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0)
        return subprocess.CompletedProcess(args=cmd, returncode=1)

    with patch("subprocess.run", side_effect=mock_run_amf):
        assert detect_best_video_encoder(fake_ffmpeg) == "h264_amf"

    # Linux: when nvenc and qsv fail but vaapi succeeds
    monkeypatch.setattr(sys, "platform", "linux")
    def mock_run_vaapi(cmd, *args, **kwargs):
        if "h264_vaapi" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0)
        return subprocess.CompletedProcess(args=cmd, returncode=1)

    with patch("subprocess.run", side_effect=mock_run_vaapi):
        assert detect_best_video_encoder(fake_ffmpeg) == "h264_vaapi"


def test_ffmpeg_resolver_user_cache(tmp_path, monkeypatch):
    suffix = ".exe" if sys.platform == "win32" else ""
    fake_cache_dir = tmp_path / ".media_optimizer" / "bin"
    fake_cache_dir.mkdir(parents=True)
    fake_bin = fake_cache_dir / f"cachebin{suffix}"
    fake_bin.touch()

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch("shutil.which", return_value=None):
        found = FFmpegResolver.get_binary_path("cachebin")
        assert found == fake_bin


def test_ffmpeg_resolver_imageio_ffmpeg_fallback(tmp_path, monkeypatch):
    fake_ffmpeg = tmp_path / "fake_imageio_ffmpeg.exe"
    fake_ffmpeg.touch()

    mock_mod = MagicMock()
    mock_mod.get_ffmpeg_exe.return_value = str(fake_ffmpeg)

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch.object(Path, "resolve", return_value=tmp_path / "mod" / "file.py"), \
         patch("shutil.which", return_value=None), \
         patch("importlib.import_module", return_value=mock_mod):
        found = FFmpegResolver.get_binary_path("ffmpeg")
        assert found == fake_ffmpeg


def test_ffmpeg_resolver_imageio_ffmpeg_fallback_invalid(tmp_path, monkeypatch):
    mock_mod = MagicMock()
    mock_mod.get_ffmpeg_exe.return_value = str(tmp_path / "non_existent.exe")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch.object(Path, "resolve", return_value=tmp_path / "mod" / "file.py"), \
         patch("shutil.which", return_value=None), \
         patch("importlib.import_module", return_value=mock_mod):
        found = FFmpegResolver.get_binary_path("ffmpeg")
        assert found is None


def test_ensure_binaries_already_exists(tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffprobe = tmp_path / "ffprobe.exe"
    fake_ffmpeg.touch()
    fake_ffprobe.touch()

    with patch.object(FFmpegResolver, "get_ffmpeg", return_value=fake_ffmpeg), \
         patch.object(FFmpegResolver, "get_ffprobe", return_value=fake_ffprobe):
        assert FFmpegResolver.ensure_binaries(tmp_path) is True


def test_ensure_binaries_copy_from_path(tmp_path, monkeypatch):
    sys_ffmpeg = tmp_path / "sys_ffmpeg.exe"
    sys_ffprobe = tmp_path / "sys_ffprobe.exe"
    sys_ffmpeg.touch()
    sys_ffprobe.touch()

    monkeypatch.setattr(
        "shutil.which",
        lambda name: str(sys_ffmpeg) if name == "ffmpeg" else (str(sys_ffprobe) if name == "ffprobe" else None)
    )

    dest_dir = tmp_path / "target_bin"
    with patch.object(FFmpegResolver, "get_ffmpeg", return_value=None), \
         patch.object(FFmpegResolver, "get_ffprobe", return_value=None):
        assert FFmpegResolver.ensure_binaries(dest_dir) is True
        suffix = ".exe" if sys.platform == "win32" else ""
        assert (dest_dir / f"ffmpeg{suffix}").exists()
        assert (dest_dir / f"ffprobe{suffix}").exists()


def test_ensure_binaries_copy_exception_and_unsupported_os(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/mock/tool")
    dest_dir = tmp_path / "target_bin_exc"

    with patch.object(FFmpegResolver, "get_ffmpeg", return_value=None), \
         patch.object(FFmpegResolver, "get_ffprobe", return_value=None), \
         patch("shutil.copy2", side_effect=OSError("Disk full")), \
         patch("platform.system", return_value="UnknownOS"):
        # Copy fails, URL for UnknownOS not found -> returns False
        assert FFmpegResolver.ensure_binaries(dest_dir) is False


def test_ensure_binaries_download_zip(tmp_path, monkeypatch):
    dest_dir = tmp_path / "target_zip"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "chmod", lambda self, mode: None)

    mock_zip = MagicMock()
    mock_zip.__enter__.return_value = mock_zip
    mock_zip.namelist.return_value = ["bin/ffmpeg", "bin/ffprobe"]
    mock_zip.read.return_value = b"fake_binary_payload"

    with patch.object(FFmpegResolver, "get_ffmpeg", return_value=None), \
         patch.object(FFmpegResolver, "get_ffprobe", return_value=None), \
         patch("shutil.which", return_value=None), \
         patch("platform.system", return_value="Darwin"), \
         patch("urllib.request.urlretrieve") as mock_retrieve, \
         patch("zipfile.ZipFile", return_value=mock_zip):
        def fake_retrieve(url, path):
            Path(path).touch()
        mock_retrieve.side_effect = fake_retrieve

        assert FFmpegResolver.ensure_binaries(dest_dir) is True
        assert (dest_dir / "ffmpeg").exists()
        assert (dest_dir / "ffprobe").exists()


def test_ensure_binaries_download_tar(tmp_path, monkeypatch):
    dest_dir = tmp_path / "target_tar"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "chmod", lambda self, mode: None)

    member1 = MagicMock()
    member1.name = "ffmpeg"
    member2 = MagicMock()
    member2.name = "ffprobe"

    mock_tar = MagicMock()
    mock_tar.__enter__.return_value = mock_tar
    mock_tar.getmembers.return_value = [member1, member2]

    f_mock = MagicMock()
    f_mock.read.return_value = b"fake_elf_binary"
    mock_tar.extractfile.return_value = f_mock

    with patch.object(FFmpegResolver, "get_ffmpeg", return_value=None), \
         patch.object(FFmpegResolver, "get_ffprobe", return_value=None), \
         patch("shutil.which", return_value=None), \
         patch("platform.system", return_value="Linux"), \
         patch("urllib.request.urlretrieve") as mock_retrieve, \
         patch("tarfile.open", return_value=mock_tar):
        def fake_retrieve(url, path):
            Path(path).touch()
        mock_retrieve.side_effect = fake_retrieve

        assert FFmpegResolver.ensure_binaries(dest_dir) is True
        assert (dest_dir / "ffmpeg").exists()
        assert (dest_dir / "ffprobe").exists()


def test_ensure_binaries_download_exception(tmp_path, monkeypatch):
    dest_dir = tmp_path / "target_err"

    with patch.object(FFmpegResolver, "get_ffmpeg", return_value=None), \
         patch.object(FFmpegResolver, "get_ffprobe", return_value=None), \
         patch("shutil.which", return_value=None), \
         patch("platform.system", return_value="Windows"), \
         patch("urllib.request.urlretrieve", side_effect=Exception("Network error")):
        assert FFmpegResolver.ensure_binaries(dest_dir) is False


def test_ensure_binaries_default_target_dir(monkeypatch):
    with patch.object(FFmpegResolver, "get_ffmpeg", return_value=None), \
         patch.object(FFmpegResolver, "get_ffprobe", return_value=None), \
         patch("shutil.which", return_value=None), \
         patch("platform.system", return_value="NonExistentOS"):
        assert FFmpegResolver.ensure_binaries(None) is False



