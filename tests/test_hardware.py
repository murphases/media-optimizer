"""
Tests for media_optimizer.hardware module.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from media_optimizer.hardware import (
    HardwareMonitor,
    SystemTelemetry,
    classify_cpu,
    classify_gpu,
    format_bytes,
    format_time,
)


def test_format_bytes():
    assert "500.00 B" == format_bytes(500)
    assert "1.00 KB" == format_bytes(1024)
    assert "1.50 MB" == format_bytes(1.5 * 1024 * 1024)
    assert "2.00 GB" == format_bytes(2 * 1024 * 1024 * 1024)
    assert "1.00 TB" == format_bytes(1024**4)
    assert "PB" in format_bytes(1024**6)


def test_format_time():
    assert "00:05" == format_time(5)
    assert "02:15" == format_time(135)
    assert "01:01:05" == format_time(3665)
    assert "00:00" == format_time(-10)


def test_classify_cpu(monkeypatch):
    # x64 Intel
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    arch, vendor = classify_cpu("13th Gen Intel(R) Core(TM) i7-13650HX")
    assert arch == "x64"
    assert vendor == "Intel"

    # x86 AMD Ryzen
    monkeypatch.setattr("platform.machine", lambda: "i686")
    arch, vendor = classify_cpu("AMD Ryzen 7 5800X 8-Core Processor")
    assert arch == "x86"
    assert vendor == "AMD"

    # arm64 Apple
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    arch, vendor = classify_cpu("Apple M2 Pro")
    assert arch == "arm64"
    assert vendor == "Apple"

    # arm 32-bit Qualcomm Snapdragon
    monkeypatch.setattr("platform.machine", lambda: "armv7l")
    arch, vendor = classify_cpu("Snapdragon X Elite")
    assert arch == "arm"
    assert vendor == "Qualcomm"

    # Generic CPU with unusual arch
    monkeypatch.setattr("platform.machine", lambda: "riscv64")
    arch, vendor = classify_cpu("Unknown Chipset")
    assert arch == "riscv64"
    assert vendor == "Generic CPU"


def test_classify_gpu(monkeypatch):
    # Empty or N/A
    assert classify_gpu("") == ("N/A", "N/A", "libx264")
    assert classify_gpu("N/A") == ("N/A", "N/A", "libx264")
    assert classify_gpu("Unknown GPU") == ("N/A", "N/A", "libx264")

    # NVIDIA
    v, s, e = classify_gpu("NVIDIA GeForce RTX 4080")
    assert v == "NVIDIA" and s == "RTX" and e == "h264_nvenc"

    v, s, e = classify_gpu("GeForce GTX 1660 Ti")
    assert v == "NVIDIA" and s == "GTX" and e == "h264_nvenc"

    v, s, e = classify_gpu("NVIDIA GeForce GT 1030")
    assert v == "NVIDIA" and s == "GT" and e == "libx264"

    v, s, e = classify_gpu("Quadro RTX 4000")
    assert v == "NVIDIA" and s == "RTX" and e == "h264_nvenc"

    v, s, e = classify_gpu("NVIDIA Quadro P600")
    assert v == "NVIDIA" and s == "Quadro" and e == "h264_nvenc"

    v, s, e = classify_gpu("Tesla T4")
    assert v == "NVIDIA" and s == "Tesla" and e == "h264_nvenc"

    v, s, e = classify_gpu("NVIDIA TITAN RTX")
    assert v == "NVIDIA" and s == "RTX" and e == "h264_nvenc"

    v, s, e = classify_gpu("NVIDIA GeForce MX450")
    assert v == "NVIDIA" and s == "GeForce" and e == "h264_nvenc"

    # AMD Windows
    monkeypatch.setattr(sys, "platform", "win32")
    v, s, e = classify_gpu("AMD Radeon RX 7900 XTX")
    assert v == "AMD" and s == "Radeon RX" and e == "h264_amf"

    v, s, e = classify_gpu("AMD Radeon RX Vega 56")
    assert v == "AMD" and s == "Radeon RX" and e == "h264_amf"

    v, s, e = classify_gpu("AMD Radeon Vega 11")
    assert v == "AMD" and s == "Radeon Vega" and e == "h264_amf"

    v, s, e = classify_gpu("Radeon Pro W6600")
    assert v == "AMD" and s == "Radeon Pro" and e == "h264_amf"

    v, s, e = classify_gpu("AMD Radeon Graphics")
    assert v == "AMD" and s == "Radeon" and e == "h264_amf"

    # AMD Linux (VAAPI)
    monkeypatch.setattr(sys, "platform", "linux")
    v, s, e = classify_gpu("AMD Radeon RX 6800 XT")
    assert v == "AMD" and s == "Radeon RX" and e == "h264_vaapi"

    # Intel
    v, s, e = classify_gpu("Intel(R) Arc(TM) A770 Graphics")
    assert v == "Intel" and s == "Intel Arc" and e == "h264_qsv"

    v, s, e = classify_gpu("Intel Iris Xe Graphics")
    assert v == "Intel" and s == "Intel Iris" and e == "h264_qsv"

    v, s, e = classify_gpu("Intel(R) UHD Graphics 770")
    assert v == "Intel" and s == "Intel UHD" and e == "h264_qsv"

    v, s, e = classify_gpu("Intel HD Graphics 620")
    assert v == "Intel" and s == "Intel HD" and e == "h264_qsv"

    # Apple
    v, s, e = classify_gpu("Apple M3 Max")
    assert v == "Apple" and s == "Apple Silicon" and e == "h264_videotoolbox"

    # Generic / Unknown
    v, s, e = classify_gpu("Matrox Millennium G200")
    assert v == "Outro" and s == "Genérico" and e == "libx264"


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
    assert telemetry.cpu_arch != ""
    assert telemetry.cpu_vendor != ""


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
        monkeypatch.setattr("psutil.BELOW_NORMAL_PRIORITY_CLASS", 16384, raising=False)
        HardwareMonitor.adjust_process_priority(1234)
        mock_proc.nice.assert_called_with(16384)

        # Unix branch
        monkeypatch.setattr(sys, "platform", "linux")
        mock_proc.nice.reset_mock()
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
         patch("subprocess.run", side_effect=Exception("smi error")), \
         patch.object(monitor, "_poll_windows_gpu"), \
         patch.object(monitor, "_poll_linux_gpu"), \
         patch.object(monitor, "_poll_macos_gpu"):
        monitor._poll_gpu(telemetry)
        assert telemetry.gpu_available is False


def test_poll_gpu_smi_invalid_format(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()

    def mock_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="gpu_only\n")

    with patch("media_optimizer.hardware.HAS_NVML", False), \
         patch("subprocess.run", mock_run), \
         patch.object(monitor, "_poll_windows_gpu"), \
         patch.object(monitor, "_poll_linux_gpu"), \
         patch.object(monitor, "_poll_macos_gpu"):
        monitor._poll_gpu(telemetry)
        assert telemetry.gpu_available is False


def test_get_telemetry_no_gpu(monkeypatch):
    monitor = HardwareMonitor()
    with patch.object(monitor, "_poll_gpu"):
        t = monitor.get_telemetry()
        assert t.gpu_available is False
        assert t.recommended_encoder == "libx264"


def test_get_telemetry_with_gpu():
    monitor = HardwareMonitor()
    def fake_poll(t):
        t.gpu_available = True
        t.gpu_name = "NVIDIA GeForce RTX 3080"
    with patch.object(monitor, "_poll_gpu", side_effect=fake_poll):
        t = monitor.get_telemetry()
        assert t.gpu_available is True
        assert t.gpu_vendor == "NVIDIA"
        assert t.gpu_series == "RTX"
        assert t.recommended_encoder == "h264_nvenc"


def test_poll_windows_gpu_registry(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()

    mock_winreg = MagicMock()
    mock_base_key = MagicMock()
    mock_sub_0 = MagicMock()
    mock_sub_1 = MagicMock()
    mock_sub_2 = MagicMock()

    # EnumKey returns 0000, 0001, 0002, Properties (non-digit), then raises OSError
    mock_winreg.EnumKey.side_effect = ["0000", "0001", "0002", "Properties", OSError()]

    def mock_open_key(key, subkey):
        if subkey == "0000":
            return mock_sub_0
        elif subkey == "0001":
            return mock_sub_1
        elif subkey == "0002":
            return mock_sub_2
        return mock_base_key

    mock_winreg.OpenKey.side_effect = mock_open_key

    # Sub 0: Microsoft Basic Display Adapter (should be ignored)
    # Sub 1: Intel Iris Xe Graphics (score 2)
    # Sub 2: Intel Arc A770 (score 3, memory as bytes)
    def mock_query_val(key, val_name):
        if key == mock_sub_0:
            if val_name == "DriverDesc":
                return ("Microsoft Basic Render Driver", 1)
        elif key == mock_sub_1:
            if val_name == "DriverDesc":
                return ("Intel Iris Xe Graphics", 1)
        elif key == mock_sub_2:
            if val_name == "DriverDesc":
                return ("Intel(R) Arc(TM) A770 Graphics", 1)
            elif val_name == "HardwareInformation.qwMemorySize":
                return ((16 * 1024**3).to_bytes(8, "little"), 3)
        raise FileNotFoundError()

    mock_winreg.QueryValueEx.side_effect = mock_query_val

    with patch.dict(sys.modules, {"winreg": mock_winreg}):
        monitor._poll_windows_gpu(telemetry)
        assert telemetry.gpu_available is True
        assert "Intel(R) Arc(TM) A770" in telemetry.gpu_name
        assert telemetry.gpu_mem_total_bytes == 16 * 1024**3


def test_poll_windows_gpu_with_int_memory(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()

    mock_winreg = MagicMock()
    mock_sub = MagicMock()

    mock_winreg.EnumKey.side_effect = ["0000", OSError()]
    mock_winreg.OpenKey.side_effect = lambda k, s: mock_sub

    def mock_query(key, val):
        if val == "DriverDesc":
            return ("AMD Radeon RX 6700 XT", 1)
        if val == "HardwareInformation.qwMemorySize":
            return (12 * 1024**3, 4)
        raise FileNotFoundError()

    mock_winreg.QueryValueEx.side_effect = mock_query

    with patch.dict(sys.modules, {"winreg": mock_winreg}):
        monitor._poll_windows_gpu(telemetry)
        assert telemetry.gpu_available is True
        assert "Radeon RX 6700" in telemetry.gpu_name
        assert telemetry.gpu_mem_total_bytes == 12 * 1024**3


def test_poll_windows_gpu_error(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()
    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = Exception("Registry error")
    with patch.dict(sys.modules, {"winreg": mock_winreg}):
        monitor._poll_windows_gpu(telemetry)
        assert telemetry.gpu_available is False


def test_poll_linux_gpu(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()

    # Success
    fake_lspci = (
        "00:00.0 Host bridge: Intel Corporation\n"
        "01:00.0 VGA compatible controller: NVIDIA Corporation GA106 [GeForce RTX 3060]\n"
    )
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=fake_lspci)):
        monitor._poll_linux_gpu(telemetry)
        assert telemetry.gpu_available is True
        assert "GeForce RTX 3060" in telemetry.gpu_name

    # Not found
    telemetry2 = SystemTelemetry()
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="No display devices\n")):
        monitor._poll_linux_gpu(telemetry2)
        assert telemetry2.gpu_available is False

    # Exception
    with patch("subprocess.run", side_effect=Exception("lspci missing")):
        monitor._poll_linux_gpu(telemetry2)
        assert telemetry2.gpu_available is False


def test_poll_macos_gpu(monkeypatch):
    monitor = HardwareMonitor()
    telemetry = SystemTelemetry()

    # Success
    fake_prof = (
        "Graphics/Displays:\n"
        "    Chipset Model: Apple M1 Pro\n"
        "    Type: GPU\n"
    )
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=fake_prof)):
        monitor._poll_macos_gpu(telemetry)
        assert telemetry.gpu_available is True
        assert "Apple M1 Pro" in telemetry.gpu_name

    # Not found
    telemetry2 = SystemTelemetry()
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="No chips\n")):
        monitor._poll_macos_gpu(telemetry2)
        assert telemetry2.gpu_available is False

    # Exception
    with patch("subprocess.run", side_effect=Exception("profiler missing")):
        monitor._poll_macos_gpu(telemetry2)
        assert telemetry2.gpu_available is False


def test_no_psutil_branches(monkeypatch):
    monitor = HardwareMonitor()
    monkeypatch.setattr("media_optimizer.hardware.psutil", None)
    telemetry = monitor.get_telemetry()
    assert telemetry.cpu_count >= 1

    HardwareMonitor.adjust_process_priority(999)  # Should return immediately
