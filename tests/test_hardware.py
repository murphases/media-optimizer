"""
Tests for media_optimizer.hardware module.
"""

import sys
import subprocess
from unittest.mock import MagicMock, patch
import pytest
from media_optimizer.hardware import (
    HardwareMonitor,
    SystemTelemetry,
    format_bytes,
    format_time,
)


def test_format_bytes():
    assert "500.00 B" == format_bytes(500)
    assert "1.00 KB" == format_bytes(1024)
    assert "1.50 MB" == format_bytes(1.5 * 1024 * 1024)
    assert "2.00 GB" == format_bytes(2 * 1024 * 1024 * 1024)
    assert "1.00 TB" == format_bytes(1024**4)
    assert "1.00 PB" == format_bytes(1024**5)


def test_format_time():
    assert "00:05" == format_time(5)
    assert "02:15" == format_time(135)
    assert "01:01:05" == format_time(3665)
    assert "00:00" == format_time(-10)


def test_get_cpu_name_cached():
    monitor = HardwareMonitor()
    monitor._cpu_name = "Mocked Ryzen 9"
    assert monitor.get_cpu_name() == "Mocked Ryzen 9"


def test_get_cpu_name_darwin(monkeypatch):
    monitor = HardwareMonitor()
    monkeypatch.setattr(sys, "platform", "darwin")

    def mock_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="Apple M3 Max\n")

    monkeypatch.setattr(subprocess, "run", mock_run)
    assert monitor.get_cpu_name() == "Apple M3 Max"


def test_get_cpu_name_linux(monkeypatch, tmp_path):
    monitor = HardwareMonitor()
    monkeypatch.setattr(sys, "platform", "linux")

    fake_cpuinfo = "processor\t: 0\nmodel name\t: AMD EPYC 7763 64-Core Processor\n"
    cpuinfo_path = tmp_path / "cpuinfo"
    cpuinfo_path.write_text(fake_cpuinfo, encoding="utf-8")

    real_open = open
    def mock_open(path, *args, **kwargs):
        if path == "/proc/cpuinfo":
            return real_open(cpuinfo_path, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open)
    assert "AMD EPYC" in monitor.get_cpu_name()


def test_get_telemetry_and_throttling():
    monitor = HardwareMonitor(memory_throttle_percent=80.0)
    telemetry = monitor.get_telemetry()
    assert isinstance(telemetry, SystemTelemetry)
    assert telemetry.cpu_count >= 1
    assert telemetry.ram_total_bytes >= 0


def test_get_telemetry_throttling_triggered(monkeypatch):
    monitor = HardwareMonitor(memory_throttle_percent=75.0)

    mock_vm = MagicMock()
    mock_vm.total = 32 * 1024**3
    mock_vm.used = 28 * 1024**3
    mock_vm.percent = 87.5

    with patch("psutil.virtual_memory", return_value=mock_vm):
        telemetry = monitor.get_telemetry()
        assert telemetry.is_throttling is True


def test_poll_gpu_nvml_success(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()

    mock_handle = MagicMock()
    mock_mem = MagicMock(total=6 * 1024**3, used=2 * 1024**3)
    mock_rates = MagicMock(gpu=45)

    with patch("media_optimizer.hardware.HAS_NVML", True), \
         patch("pynvml.nvmlDeviceGetHandleByIndex", return_value=mock_handle), \
         patch("pynvml.nvmlDeviceGetName", return_value=b"NVIDIA GeForce RTX 4060"), \
         patch("pynvml.nvmlDeviceGetMemoryInfo", return_value=mock_mem), \
         patch("pynvml.nvmlDeviceGetUtilizationRates", return_value=mock_rates), \
         patch("pynvml.nvmlDeviceGetTemperature", return_value=55):
        monitor._poll_gpu(telemetry)
        assert telemetry.gpu_available is True
        assert "RTX 4060" in telemetry.gpu_name
        assert telemetry.gpu_load_percent == 45.0
        assert telemetry.gpu_temp_c == 55.0


def test_poll_gpu_smi_fallback(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()

    def mock_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="GeForce GTX 1650, 30, 4096, 1024, 48\n",
        )

    with patch("media_optimizer.hardware.HAS_NVML", False), \
         patch("subprocess.run", mock_run):
        monitor._poll_gpu(telemetry)
        assert telemetry.gpu_available is True
        assert "GTX 1650" in telemetry.gpu_name
        assert telemetry.gpu_load_percent == 30.0
        assert telemetry.gpu_temp_c == 48.0


def test_adjust_process_priority(monkeypatch):
    mock_proc = MagicMock()
    with patch("psutil.Process", return_value=mock_proc):
        # Windows branch
        monkeypatch.setattr(sys, "platform", "win32")
        HardwareMonitor.adjust_process_priority(1234)
        mock_proc.nice.assert_called()

        # Unix branch
        monkeypatch.setattr(sys, "platform", "linux")
        mock_proc.nice.return_value = 0
        HardwareMonitor.adjust_process_priority(1234)
        mock_proc.nice.assert_called_with(10)

        # Exception branch
        mock_proc.nice.side_effect = RuntimeError("Denied")
        HardwareMonitor.adjust_process_priority(1234)  # should not raise


def test_get_cpu_name_win32_registry(monkeypatch):
    monitor = HardwareMonitor()
    monkeypatch.setattr(sys, "platform", "win32")

    mock_winreg = MagicMock()
    mock_winreg.OpenKey.return_value = "key"
    mock_winreg.QueryValueEx.return_value = ("Intel Core i9-14900K", 1)

    with patch.dict(sys.modules, {"winreg": mock_winreg}):
        name = monitor.get_cpu_name()
        assert "Intel Core i9" in name


def test_get_cpu_name_fallback_empty_processor(monkeypatch):
    monitor = HardwareMonitor()
    monkeypatch.setattr("platform.processor", lambda: "")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(sys, "platform", "unknown_os")
    assert monitor.get_cpu_name() == "x86_64"


def test_get_cpu_name_darwin_error(monkeypatch):
    monitor = HardwareMonitor()
    monkeypatch.setattr(sys, "platform", "darwin")
    with patch("subprocess.run", side_effect=Exception("Failed sysctl")):
        # Should not raise, returns processor or machine
        name = monitor.get_cpu_name()
        assert name is not None


def test_get_cpu_name_linux_error(monkeypatch):
    monitor = HardwareMonitor()
    monkeypatch.setattr(sys, "platform", "linux")
    with patch("builtins.open", side_effect=IOError("No proc")):
        name = monitor.get_cpu_name()
        assert name is not None


def test_poll_gpu_nvml_error(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()

    with patch("media_optimizer.hardware.HAS_NVML", True), \
         patch("pynvml.nvmlDeviceGetHandleByIndex", side_effect=Exception("NVML error")), \
         patch("subprocess.run", side_effect=Exception("smi error")):
        monitor._poll_gpu(telemetry)
        assert telemetry.gpu_available is False


def test_poll_gpu_smi_invalid_format(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()

    def mock_run(*args, **kwargs):
        # Return incomplete columns
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="gpu_only\n")

    with patch("media_optimizer.hardware.HAS_NVML", False), \
         patch("subprocess.run", mock_run):
        monitor._poll_gpu(telemetry)
        assert telemetry.gpu_available is False


def test_no_psutil_branches(monkeypatch):
    monitor = HardwareMonitor()
    monkeypatch.setattr("media_optimizer.hardware.psutil", None)
    telemetry = monitor.get_telemetry()
    assert telemetry.cpu_count >= 1

    HardwareMonitor.adjust_process_priority(999)  # Should return immediately

