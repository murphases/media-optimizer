"""
Configuration and settings management for Media Optimizer.
Provides persistent settings, presets, and platform-aware defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class OptimizerSettings:
    """Stores all user-configurable parameters for processing."""

    # Paths
    input_dir: str = ""
    converted_dir: str = ""
    optimized_images_dir: str = ""
    optimized_videos_dir: str = ""
    logs_dir: str = ""

    # Image Conversion Settings
    convert_quality: int = 95
    convert_target_format: str = "JPG"  # "JPG", "WEBP", "PNG"
    convert_workers: int = 8
    convert_raw_enabled: bool = True

    # Image Optimization Settings
    opt_image_quality: int = 70
    opt_image_max_dim: int = 1350
    opt_image_progressive: bool = True
    opt_image_optimize_tables: bool = True
    opt_image_workers: int = 8

    # Video Optimization Settings
    opt_video_max_dim: int = 1920
    opt_video_max_fps: int = 30
    opt_video_format: str = "mov"  # "mov", "mp4", "mkv"
    opt_video_codec: str = "auto"  # "auto", "h264_nvenc", "libx264", "h264_videotoolbox", "h264_qsv"
    opt_video_crf: int = 23
    opt_video_audio_bitrate: str = "128k"
    opt_video_workers: int = 2

    # Engine & Safety Settings
    dry_run: bool = False
    skip_existing: bool = True
    memory_threshold_percent: float = 88.0
    theme: str = "Dark"  # "Dark", "Light", "System"
    accent_color: str = "blue"  # "blue", "green", "dark-blue"
    language: str = "pt_BR"

    # Custom attributes / metadata
    custom_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OptimizerSettings:
        """Create settings instance from dictionary, ignoring unknown fields."""
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


class ConfigManager:
    """Manages loading, saving, and persisting application configuration."""

    DEFAULT_CONFIG_FILENAME = "media_optimizer_config.json"

    def __init__(self, config_path: Optional[Path] = None):
        if config_path:
            self.config_file = Path(config_path)
        else:
            base_dir = Path(os.environ.get("APPDATA", Path.home() / ".config"))
            self.config_file = base_dir / "MediaOptimizer" / self.DEFAULT_CONFIG_FILENAME

        self.settings: OptimizerSettings = self.get_default_settings()

    @staticmethod
    def get_default_workspace() -> Path:
        """Determines default media directory based on system conventions."""
        home = Path.home()
        # Fallback to User Pictures or Downloads
        pictures = home / "Pictures"
        if pictures.exists():
            return pictures / "MediaOptimizer"
        return home / "MediaOptimizer"

    @classmethod
    def get_default_settings(cls) -> OptimizerSettings:
        """Returns standard default settings with dynamically calculated directories."""
        workspace = cls.get_default_workspace()
        return OptimizerSettings(
            input_dir=str(workspace / "Originais"),
            converted_dir=str(workspace / "Convertidos" / "JPG"),
            optimized_images_dir=str(workspace / "Otimizadas" / "JPG"),
            optimized_videos_dir=str(workspace / "Otimizadas" / "MOV"),
            logs_dir=str(workspace / "logs"),
        )

    def load(self) -> OptimizerSettings:
        """Loads configuration from JSON file or creates default if non-existent."""
        if not self.config_file.exists():
            self.settings = self.get_default_settings()
            return self.settings

        try:
            content = self.config_file.read_text(encoding="utf-8")
            data = json.loads(content)
            self.settings = OptimizerSettings.from_dict(data)
        except Exception:
            # Fallback to defaults on corrupted file
            self.settings = self.get_default_settings()

        return self.settings

    def save(self, settings: Optional[OptimizerSettings] = None) -> bool:
        """Saves configuration to JSON file."""
        if settings is not None:
            self.settings = settings

        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.settings.to_dict(), indent=2, ensure_ascii=False)
            # Atomic save
            temp_file = self.config_file.with_suffix(".tmp")
            temp_file.write_text(payload, encoding="utf-8")
            if self.config_file.exists():
                self.config_file.unlink()
            temp_file.rename(self.config_file)
            return True
        except Exception:
            return False

    def reset_defaults(self) -> OptimizerSettings:
        """Resets in-memory settings to default and saves to disk."""
        self.settings = self.get_default_settings()
        self.save()
        return self.settings
