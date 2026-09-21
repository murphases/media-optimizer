"""
Tests for media_optimizer.config module.
"""

from pathlib import Path
import pytest
from media_optimizer.config import ConfigManager, OptimizerSettings


def test_settings_to_and_from_dict():
    s = OptimizerSettings(
        input_dir="/tmp/in",
        convert_quality=80,
        opt_video_max_fps=24,
    )
    d = s.to_dict()
    assert d["input_dir"] == "/tmp/in"
    assert d["convert_quality"] == 80
    assert d["opt_video_max_fps"] == 24

    # Extra unexpected keys should be ignored
    d["invalid_key"] = "test"
    loaded = OptimizerSettings.from_dict(d)
    assert loaded.input_dir == "/tmp/in"
    assert not hasattr(loaded, "invalid_key")


def test_config_manager_defaults(tmp_path: Path):
    cfg_file = tmp_path / "test_config.json"
    mgr = ConfigManager(config_path=cfg_file)

    defaults = mgr.get_default_settings()
    assert "Originais" in defaults.input_dir
    assert defaults.convert_quality == 95
    assert defaults.opt_image_max_dim == 1350


def test_config_manager_save_and_load(tmp_path: Path):
    cfg_file = tmp_path / "sub" / "test_config.json"
    mgr = ConfigManager(config_path=cfg_file)

    settings = mgr.settings
    settings.input_dir = "/custom/input"
    settings.convert_quality = 88
    assert mgr.save(settings) is True

    # New manager instance reading saved file
    mgr2 = ConfigManager(config_path=cfg_file)
    loaded = mgr2.load()
    assert loaded.input_dir == "/custom/input"
    assert loaded.convert_quality == 88


def test_config_manager_load_corrupted_fallback(tmp_path: Path):
    cfg_file = tmp_path / "corrupted.json"
    cfg_file.write_text("{invalid_json_content", encoding="utf-8")

    mgr = ConfigManager(config_path=cfg_file)
    loaded = mgr.load()
    assert loaded.convert_quality == 95  # Fallback default


def test_config_manager_reset_defaults(tmp_path: Path):
    cfg_file = tmp_path / "test_reset.json"
    mgr = ConfigManager(config_path=cfg_file)
    mgr.settings.convert_quality = 55
    mgr.save()

    reset_settings = mgr.reset_defaults()
    assert reset_settings.convert_quality == 95
    assert mgr.load().convert_quality == 95


def test_config_manager_save_error(tmp_path: Path, monkeypatch):
    cfg_file = tmp_path / "error_config.json"
    mgr = ConfigManager(config_path=cfg_file)

    def mock_write(*args, **kwargs):
        raise PermissionError("Denied")

    monkeypatch.setattr(Path, "write_text", mock_write)
    assert mgr.save() is False


def test_get_default_workspace(monkeypatch, tmp_path: Path):
    fake_home = tmp_path / "user_home"
    pictures = fake_home / "Pictures"
    pictures.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    ws = ConfigManager.get_default_workspace()
    assert ws == pictures / "MediaOptimizer"

    # Test when Pictures does not exist
    pictures.rmdir()
    ws2 = ConfigManager.get_default_workspace()
    assert ws2 == fake_home / "MediaOptimizer"
