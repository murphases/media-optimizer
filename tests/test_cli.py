"""
Tests for media_optimizer.cli module.
"""

from unittest.mock import MagicMock, patch
import pytest

from media_optimizer.cli import build_parser, main, print_telemetry


def test_build_parser():
    parser = build_parser()
    args = parser.parse_args(["--input", "/tmp/in", "--mode", "convert", "--dry-run"])
    assert args.input == "/tmp/in"
    assert args.mode == "convert"
    assert args.dry_run is True


def test_print_telemetry(capsys):
    print_telemetry()
    captured = capsys.readouterr()
    assert "TELEMETRIA DE HARDWARE" in captured.out
    assert "CPU:" in captured.out


def test_print_telemetry_no_gpu(capsys, monkeypatch):
    from media_optimizer.hardware import SystemTelemetry
    mock_mon = MagicMock()
    mock_mon.get_telemetry.return_value = SystemTelemetry(gpu_available=False)
    monkeypatch.setattr("media_optimizer.cli.HardwareMonitor", lambda: mock_mon)
    print_telemetry()
    captured = capsys.readouterr()
    assert "Nenhuma GPU dedicada detectada" in captured.out


def test_cli_telemetry_flag():
    with patch("media_optimizer.cli.print_telemetry") as mock_tel:
        assert main(["--telemetry"]) == 0
        mock_tel.assert_called_once()


def test_cli_mode_convert(temp_workspace, tmp_path, capsys):
    out = tmp_path / "cli_out"
    code = main([
        "--input", str(temp_workspace["input_dir"]),
        "--output", str(out),
        "--mode", "convert",
        "--dry-run",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "Conversão concluída" in captured.out


def test_cli_mode_opt_images(temp_workspace, tmp_path, capsys):
    out = tmp_path / "cli_out"
    code = main([
        "--input", str(temp_workspace["input_dir"]),
        "--output", str(out),
        "--mode", "opt-images",
        "--dry-run",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "Otimização de imagens concluída" in captured.out


def test_cli_mode_opt_videos(temp_workspace, tmp_path, capsys):
    out = tmp_path / "cli_out"
    code = main([
        "--input", str(temp_workspace["input_dir"]),
        "--output", str(out),
        "--mode", "opt-videos",
        "--dry-run",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "Otimização de vídeos concluída" in captured.out


def test_cli_mode_all(temp_workspace, tmp_path, capsys):
    out = tmp_path / "cli_out"
    code = main([
        "--input", str(temp_workspace["input_dir"]),
        "--output", str(out),
        "--mode", "all",
        "--dry-run",
        "--workers", "4",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "PIPELINE CONCLUÍDO COM SUCESSO" in captured.out
