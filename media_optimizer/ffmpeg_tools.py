"""
FFmpeg and FFprobe utilities.
Finds bundled or system binaries, probes media files, detects hardware encoders,
and builds optimized conversion commands.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class VideoMetadata:
    """Detailed metadata extracted from video file."""

    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    bitrate: int = 0
    rotation: int = 0

    @property
    def display_width(self) -> int:
        """Visual width accounting for 90° or 270° display rotation."""
        if abs(self.rotation) in (90, 270):
            return self.height
        return self.width

    @property
    def display_height(self) -> int:
        """Visual height accounting for 90° or 270° display rotation."""
        if abs(self.rotation) in (90, 270):
            return self.width
        return self.height

    @property
    def is_vertical(self) -> bool:
        """Returns True if the video is displayed in portrait/vertical orientation."""
        return self.display_height > self.display_width


class FFmpegResolver:
    """Locates and manages FFmpeg/FFprobe binaries across platforms."""

    FFMPEG_URLS = {
        "windows": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "linux": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
        "darwin": "https://evermeet.cx/ffmpeg/getrelease/zip",
    }

    @classmethod
    def get_binary_path(cls, binary_name: str) -> Optional[Path]:
        """
        Locates executable by checking:
        1. PyInstaller frozen bundled directory (_MEIPASS / executable folder).
        2. Application root /bin or /resources directory.
        3. User cache directory (~/.media_optimizer/bin).
        4. System PATH.
        5. imageio_ffmpeg fallback.
        """
        suffix = ".exe" if sys.platform == "win32" else ""
        target_name = f"{binary_name}{suffix}"

        # 1. PyInstaller bundle
        if hasattr(sys, "_MEIPASS"):
            bundled = Path(getattr(sys, "_MEIPASS")) / target_name
            if bundled.exists():
                return bundled
            bundled_bin = Path(getattr(sys, "_MEIPASS")) / "bin" / target_name
            if bundled_bin.exists():
                return bundled_bin

        # Check next to running executable
        exe_dir = Path(sys.executable).parent
        local_target = exe_dir / target_name
        if local_target.exists():
            return local_target
        local_bin = exe_dir / "bin" / target_name
        if local_bin.exists():
            return local_bin

        # 2. Workspace / repository bin or resources
        repo_root = Path(__file__).resolve().parent.parent
        repo_bin = repo_root / "bin" / target_name
        if repo_bin.exists():
            return repo_bin
        repo_resources = repo_root / "resources" / target_name
        if repo_resources.exists():
            return repo_resources

        # 3. User cache directory (~/.media_optimizer/bin)
        user_cache = Path.home() / ".media_optimizer" / "bin" / target_name
        if user_cache.exists():
            return user_cache

        # 4. System PATH
        which_path = shutil.which(binary_name)
        if which_path:
            return Path(which_path)

        # 5. imageio_ffmpeg fallback if available
        if binary_name == "ffmpeg":
            try:
                import importlib
                imageio_ffmpeg = importlib.import_module("imageio_ffmpeg")
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                if ffmpeg_path and Path(ffmpeg_path).exists():
                    return Path(ffmpeg_path)
            except Exception:
                pass

        return None

    @classmethod
    def get_ffmpeg(cls) -> Optional[Path]:
        return cls.get_binary_path("ffmpeg")

    @classmethod
    def get_ffprobe(cls) -> Optional[Path]:
        return cls.get_binary_path("ffprobe")

    @classmethod
    def ensure_binaries(cls, target_dir: Optional[Path] = None) -> bool:
        """
        Ensures ffmpeg and ffprobe are available. If missing, attempts to copy from PATH
        or download static builds for the current platform into target_dir.
        """
        if cls.get_ffmpeg() and cls.get_ffprobe():
            return True

        if target_dir is None:
            repo_root = Path(__file__).resolve().parent.parent
            target_dir = repo_root / "bin"

        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".exe" if sys.platform == "win32" else ""
        ffmpeg_target = target_dir / f"ffmpeg{suffix}"
        ffprobe_target = target_dir / f"ffprobe{suffix}"

        # 1. Try copy from system PATH if available
        sys_ffmpeg = shutil.which("ffmpeg")
        sys_ffprobe = shutil.which("ffprobe")
        if sys_ffmpeg and sys_ffprobe:
            try:
                shutil.copy2(sys_ffmpeg, ffmpeg_target)
                shutil.copy2(sys_ffprobe, ffprobe_target)
                return True
            except Exception:
                pass

        # 2. Download pre-compiled static release
        current_os = platform.system().lower()
        url = cls.FFMPEG_URLS.get(current_os)
        if not url:
            return False

        archive_ext = ".zip" if "zip" in url else ".tar.xz"
        archive_path = target_dir / f"ffmpeg_download{archive_ext}"

        try:
            urllib.request.urlretrieve(url, archive_path)

            if archive_ext == ".zip":
                with zipfile.ZipFile(archive_path, "r") as z:
                    for member in z.namelist():
                        fname = Path(member).name.lower()
                        if fname in (f"ffmpeg{suffix}", f"ffprobe{suffix}"):
                            data = z.read(member)
                            dest = target_dir / Path(member).name
                            dest.write_bytes(data)
                            if sys.platform != "win32":
                                dest.chmod(0o755)
            else:
                with tarfile.open(archive_path, "r:*") as t:
                    for member in t.getmembers():
                        fname = Path(member.name).name
                        if fname in ("ffmpeg", "ffprobe"):
                            f = t.extractfile(member)
                            if f:
                                dest = target_dir / fname
                                dest.write_bytes(f.read())
                                dest.chmod(0o755)

            archive_path.unlink(missing_ok=True)
            return ffmpeg_target.exists() and ffprobe_target.exists()
        except Exception:
            if archive_path.exists():
                try:
                    archive_path.unlink()
                except Exception:
                    pass
            return False


def probe_video(video_path: Path, ffprobe_exe: Optional[Path] = None) -> Optional[VideoMetadata]:
    """Inspects video file using ffprobe and extracts metadata."""
    probe = ffprobe_exe or FFmpegResolver.get_ffprobe()
    if not probe or not video_path.exists():
        return None

    cmd = [
        str(probe),
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(video_path)
    ]

    try:
        startupinfo = None
        if sys.platform == "win32" and hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15, startupinfo=startupinfo)
        if res.returncode != 0 or not res.stdout.strip():
            return None

        data = json.loads(res.stdout)
        meta = VideoMetadata()

        # Format info
        fmt = data.get("format", {})
        meta.duration = float(fmt.get("duration", 0.0) or 0.0)
        meta.bitrate = int(fmt.get("bit_rate", 0) or 0)

        # Stream info
        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type")
            if codec_type == "video" and meta.width == 0:
                meta.width = int(stream.get("width", 0) or 0)
                meta.height = int(stream.get("height", 0) or 0)
                meta.video_codec = stream.get("codec_name", "")

                # Parse frame rate (fraction e.g. "30000/1001" or "30/1")
                fps_str = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
                try:
                    num, den = fps_str.split("/")
                    num_f, den_f = float(num), float(den)
                    meta.fps = round(num_f / den_f, 2) if den_f != 0 else 0.0
                except Exception:
                    meta.fps = 0.0

                # Rotation detection: check side_data_list (Display Matrix) and tags
                found_rotation = False
                for side_data in stream.get("side_data_list", []):
                    rot = side_data.get("rotation")
                    if rot is not None:
                        try:
                            meta.rotation = int(round(float(rot)))
                            found_rotation = True
                            break
                        except (ValueError, TypeError):
                            pass

                if not found_rotation:
                    tags = stream.get("tags", {}) or {}
                    for key, val in tags.items():
                        if key.lower() in ("rotate", "rotation"):
                            try:
                                meta.rotation = int(round(float(val)))
                                found_rotation = True
                                break
                            except (ValueError, TypeError):
                                pass

                if not found_rotation:
                    fmt_tags = fmt.get("tags", {}) or {}
                    for key, val in fmt_tags.items():
                        if key.lower() in ("rotate", "rotation"):
                            try:
                                meta.rotation = int(round(float(val)))
                                found_rotation = True
                                break
                            except (ValueError, TypeError):
                                pass

            elif codec_type == "audio" and not meta.audio_codec:
                meta.audio_codec = stream.get("codec_name", "")

        return meta
    except Exception:
        return None


def detect_best_video_encoder(ffmpeg_exe: Optional[Path] = None) -> str:
    """
    Tests and returns the fastest supported video hardware encoder,
    falling back to libx264.
    Supports NVIDIA (NVENC), Intel Arc/Iris/UHD (QSV), AMD Radeon/RX (AMF/VAAPI),
    Apple Silicon (VideoToolbox), and CPU (libx264).
    """
    ffmpeg = ffmpeg_exe or FFmpegResolver.get_ffmpeg()
    if not ffmpeg:
        return "libx264"

    if sys.platform == "win32":
        encoders_to_test = ["h264_nvenc", "h264_qsv", "h264_amf", "libx264"]
    elif sys.platform == "darwin":
        encoders_to_test = ["h264_videotoolbox", "libx264"]
    else:
        encoders_to_test = ["h264_nvenc", "h264_qsv", "h264_vaapi", "libx264"]

    startupinfo = None
    if sys.platform == "win32" and hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    for encoder in encoders_to_test:
        if encoder == "libx264":
            return "libx264"

        cmd = [
            str(ffmpeg),
            "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
            "-c:v", encoder,
            "-f", "null", "-"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, startupinfo=startupinfo)
            if res.returncode == 0:
                return encoder
        except Exception:
            continue

    return "libx264"  # pragma: no cover


def calculate_target_dimensions(
    orig_w: int, orig_h: int, max_dim: int
) -> Tuple[int, int]:
    """
    Computes output dimensions preserving aspect ratio and ensuring even numbers.
    Never upscales.
    """
    if orig_w <= 0 or orig_h <= 0:
        return (1920, 1080)

    major = max(orig_w, orig_h)
    if major <= max_dim:
        # Round to even for codecs
        target_w = orig_w if orig_w % 2 == 0 else orig_w - 1
        target_h = orig_h if orig_h % 2 == 0 else orig_h - 1
        return (max(2, target_w), max(2, target_h))

    scale = max_dim / float(major)
    target_w = int(orig_w * scale)
    target_h = int(orig_h * scale)

    # Ensure even numbers required by H.264
    if target_w % 2 != 0:
        target_w -= 1
    if target_h % 2 != 0:
        target_h -= 1

    return (max(2, target_w), max(2, target_h))


def build_video_conversion_command(
    ffmpeg_exe: Path,
    input_path: Path,
    output_path: Path,
    encoder: str,
    target_w: int,
    target_h: int,
    target_fps: Optional[float] = None,
    crf: int = 23,
    audio_bitrate: str = "128k",
    threads: Optional[int] = None,
) -> List[str]:
    """Constructs robust FFmpeg command for video compression across all GPU/CPU encoders."""
    cmd = [
        str(ffmpeg_exe),
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(input_path),
    ]

    # Video filters
    vf_filters = [f"scale={target_w}:{target_h}:flags=lanczos", "setsar=1"]
    if target_fps is not None and target_fps > 0:
        vf_filters.append(f"fps={target_fps}")

    cmd.extend(["-vf", ",".join(vf_filters)])

    # Video codec options
    cmd.extend(["-c:v", encoder])
    if encoder == "h264_nvenc":
        cmd.extend(["-preset", "p6", "-cq", str(crf), "-rc", "vbr", "-pix_fmt", "yuv420p"])
    elif encoder == "h264_amf":
        cmd.extend(["-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf), "-quality", "balanced", "-pix_fmt", "yuv420p"])
    elif encoder == "h264_qsv":
        cmd.extend(["-global_quality", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"])
    elif encoder == "h264_vaapi":
        cmd.extend(["-qp", str(crf)])
    elif encoder == "h264_videotoolbox":
        cmd.extend(["-q:v", str(crf), "-pix_fmt", "yuv420p"])
    else:  # libx264 (CPU)
        cmd.extend(["-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"])

    if threads is not None and threads > 0:
        cmd.extend(["-threads", str(threads)])

    # Audio codec
    cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])

    # Streaming, metadata preservation, and explicitly reset video rotation metadata
    cmd.extend(["-movflags", "+faststart", "-map_metadata", "0", "-metadata:s:v:0", "rotate=0"])

    cmd.append(str(output_path))
    return cmd
