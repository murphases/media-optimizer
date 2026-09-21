"""
Hardware monitoring and system telemetry.
Provides dynamic cross-platform CPU, RAM, and GPU detection,
priority throttling, and resource limit safeguards.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import psutil
except ImportError:
    psutil = None

# Optional NVIDIA NVML
HAS_NVML = False
try:  # pragma: no cover
    import pynvml
    pynvml.nvmlInit()
    HAS_NVML = True
except Exception:  # pragma: no cover
    HAS_NVML = False


def format_bytes(size_bytes: float | int) -> str:
    """Format bytes into human-readable string (KB, MB, GB, TB)."""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def format_time(seconds: float | int) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS."""
    secs = int(max(0, seconds))
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def classify_cpu(cpu_name: str) -> Tuple[str, str]:
    """
    Returns (cpu_arch, cpu_vendor) based on platform and CPU name.
    Supports x86, x64, ARM/ARM64 and Intel, AMD, Apple, Qualcomm, etc.
    """
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "x64"):
        arch = "x64"
    elif machine in ("x86", "i386", "i686"):
        arch = "x86"
    elif "arm" in machine or "aarch64" in machine:
        arch = "arm64" if ("64" in machine or "aarch64" in machine) else "arm"
    else:
        arch = machine or "x64"

    name_upper = cpu_name.upper()
    if "INTEL" in name_upper:
        vendor = "Intel"
    elif any(k in name_upper for k in ("AMD", "RYZEN", "THREADRIPPER", "EPYC", "ATHLON", "RADEON")):
        vendor = "AMD"
    elif any(k in name_upper for k in ("APPLE", "M1", "M2", "M3", "M4")):
        vendor = "Apple"
    elif any(k in name_upper for k in ("SNAPDRAGON", "QUALCOMM")):
        vendor = "Qualcomm"
    else:
        vendor = "Generic CPU"

    return (arch, vendor)


def classify_gpu(gpu_name: str) -> Tuple[str, str, str]:
    """
    Returns (gpu_vendor, gpu_series, recommended_encoder) based on GPU model name.
    Recognizes NVIDIA (RTX, GTX, GT), AMD (Radeon RX, Vega, Pro), Intel (Arc, Iris, UHD),
    and Apple Silicon.
    """
    if not gpu_name or gpu_name in ("N/A", "Unknown GPU"):
        return ("N/A", "N/A", "libx264")

    name_upper = gpu_name.upper()

    # NVIDIA
    if any(k in name_upper for k in ("NVIDIA", "GEFORCE", "QUADRO", "TESLA", "TITAN")):
        vendor = "NVIDIA"
        if "RTX" in name_upper:
            series = "RTX"
            encoder = "h264_nvenc"
        elif "GTX" in name_upper:
            series = "GTX"
            encoder = "h264_nvenc"
        elif "GT" in name_upper:
            # NVIDIA GT models (e.g. GT 710, GT 730, GT 1030) lack NVENC silicon blocks
            series = "GT"
            encoder = "libx264"
        elif "QUADRO" in name_upper:
            series = "Quadro"
            encoder = "h264_nvenc"
        elif "TESLA" in name_upper:
            series = "Tesla"
            encoder = "h264_nvenc"
        else:
            series = "GeForce"
            encoder = "h264_nvenc"
        return (vendor, series, encoder)

    # AMD
    if any(k in name_upper for k in ("AMD", "RADEON", "ATI")):
        vendor = "AMD"
        if "RX" in name_upper:
            series = "Radeon RX"
        elif "VEGA" in name_upper:
            series = "Radeon Vega"
        elif "PRO" in name_upper:
            series = "Radeon Pro"
        else:
            series = "Radeon"
        encoder = "h264_amf" if sys.platform == "win32" else "h264_vaapi"
        return (vendor, series, encoder)

    # Intel
    if any(k in name_upper for k in ("INTEL", "ARC", "IRIS", "UHD", "HD GRAPHICS")):
        vendor = "Intel"
        if "ARC" in name_upper:
            series = "Intel Arc"
        elif "IRIS" in name_upper:
            series = "Intel Iris"
        elif "UHD" in name_upper:
            series = "Intel UHD"
        else:
            series = "Intel HD"
        encoder = "h264_qsv"
        return (vendor, series, encoder)

    # Apple
    if any(k in name_upper for k in ("APPLE", "M1", "M2", "M3", "M4")):
        return ("Apple", "Apple Silicon", "h264_videotoolbox")

    return ("Outro", "Genérico", "libx264")


@dataclass
class SystemTelemetry:
    """Snapshot of system resource usage."""

    cpu_percent: float = 0.0
    cpu_count: int = 1
    cpu_name: str = "Unknown CPU"
    cpu_arch: str = "x64"
    cpu_vendor: str = "Generic CPU"

    ram_total_bytes: int = 0
    ram_used_bytes: int = 0
    ram_percent: float = 0.0

    gpu_available: bool = False
    gpu_name: str = "N/A"
    gpu_vendor: str = "N/A"
    gpu_series: str = "N/A"
    gpu_load_percent: float = 0.0
    gpu_mem_total_bytes: int = 0
    gpu_mem_used_bytes: int = 0
    gpu_temp_c: float = 0.0
    recommended_encoder: str = "libx264"

    is_throttling: bool = False


class HardwareMonitor:
    """Monitors system resources and enforces stability limits."""

    def __init__(self, memory_throttle_percent: float = 88.0):
        self.memory_throttle_percent = memory_throttle_percent
        self._cpu_name: Optional[str] = None
        self._cached_gpu_info: Optional[dict] = None

    def get_cpu_name(self) -> str:
        """Dynamically detect processor name across Windows, Linux, macOS."""
        if self._cpu_name:
            return self._cpu_name

        name = platform.processor()
        if not name:
            name = platform.machine() or "Generic Processor"

        # Windows-specific registry lookup for friendly name
        if sys.platform == "win32":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                )
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if val and str(val).strip():
                    name = str(val).strip()
            except Exception:
                pass
        elif sys.platform == "darwin":
            try:
                res = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if res.returncode == 0 and res.stdout.strip():
                    name = res.stdout.strip()
            except Exception:
                pass
        elif sys.platform.startswith("linux"):
            try:
                with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                    for line in f:
                        if "model name" in line:
                            name = line.split(":", 1)[1].strip()
                            break
            except Exception:
                pass

        self._cpu_name = name
        return self._cpu_name

    def get_telemetry(self) -> SystemTelemetry:
        """Poll and return current resource snapshot."""
        telemetry = SystemTelemetry()
        telemetry.cpu_name = self.get_cpu_name()
        telemetry.cpu_arch, telemetry.cpu_vendor = classify_cpu(telemetry.cpu_name)

        if psutil is not None:
            try:
                telemetry.cpu_percent = psutil.cpu_percent(interval=None)
                telemetry.cpu_count = psutil.cpu_count(logical=True) or 1

                vm = psutil.virtual_memory()
                telemetry.ram_total_bytes = vm.total
                telemetry.ram_used_bytes = vm.used
                telemetry.ram_percent = vm.percent

                if telemetry.ram_percent >= self.memory_throttle_percent:
                    telemetry.is_throttling = True
            except Exception:
                pass
        else:
            telemetry.cpu_count = os.cpu_count() or 1

        self._poll_gpu(telemetry)
        if telemetry.gpu_available:
            telemetry.gpu_vendor, telemetry.gpu_series, telemetry.recommended_encoder = classify_gpu(
                telemetry.gpu_name
            )
        else:
            telemetry.recommended_encoder = "libx264"

        return telemetry

    def _poll_gpu(self, telemetry: SystemTelemetry) -> None:
        """Poll NVIDIA, AMD, Intel or system GPU metrics across platforms."""
        # 1. NVIDIA NVML
        if HAS_NVML:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                telemetry.gpu_available = True
                raw_name = pynvml.nvmlDeviceGetName(handle)
                telemetry.gpu_name = (
                    raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)
                )

                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                telemetry.gpu_mem_total_bytes = mem.total
                telemetry.gpu_mem_used_bytes = mem.used

                rates = pynvml.nvmlDeviceGetUtilizationRates(handle)
                telemetry.gpu_load_percent = float(rates.gpu)

                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                telemetry.gpu_temp_c = float(temp)
                return
            except Exception:
                pass

        # 2. NVIDIA SMI
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.total,memory.used,temperature.gpu",
                "--format=csv,noheader,nounits",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                parts = [p.strip() for p in res.stdout.strip().split(",")]
                if len(parts) >= 5:
                    telemetry.gpu_available = True
                    telemetry.gpu_name = parts[0]
                    telemetry.gpu_load_percent = float(parts[1]) if parts[1].replace(".", "", 1).isdigit() else 0.0
                    total_mb = float(parts[2]) if parts[2].replace(".", "", 1).isdigit() else 0.0
                    used_mb = float(parts[3]) if parts[3].replace(".", "", 1).isdigit() else 0.0
                    telemetry.gpu_mem_total_bytes = int(total_mb * 1024 * 1024)
                    telemetry.gpu_mem_used_bytes = int(used_mb * 1024 * 1024)
                    telemetry.gpu_temp_c = float(parts[4]) if parts[4].replace(".", "", 1).isdigit() else 0.0
                    return
        except Exception:
            pass

        # 3. Cross-vendor OS queries (Windows Registry, Linux lspci, macOS system_profiler)
        if sys.platform == "win32":
            self._poll_windows_gpu(telemetry)
        elif sys.platform.startswith("linux"):
            self._poll_linux_gpu(telemetry)
        elif sys.platform == "darwin":
            self._poll_macos_gpu(telemetry)

    def _poll_windows_gpu(self, telemetry: SystemTelemetry) -> None:
        """Enumerate display adapters via Windows Registry for Intel, AMD, NVIDIA."""
        try:
            import winreg
            base_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path)
            candidates = []
            idx = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, idx)
                    idx += 1
                    if not subkey_name.isdigit():
                        continue
                    subkey = winreg.OpenKey(key, subkey_name)
                    try:
                        desc, _ = winreg.QueryValueEx(subkey, "DriverDesc")
                        desc_str = str(desc).strip()
                        # Ignore basic virtual or mirror drivers
                        if not desc_str or any(
                            b in desc_str.lower()
                            for b in ("basic", "virtual", "remote desktop", "rdp")
                        ):
                            continue

                        # Extract memory if present
                        mem_bytes = 0
                        for m_key in (
                            "HardwareInformation.qwMemorySize",
                            "HardwareInformation.MemorySize",
                        ):
                            try:
                                val, _ = winreg.QueryValueEx(subkey, m_key)
                                if isinstance(val, int) and val > 0:
                                    mem_bytes = val
                                    break
                                elif isinstance(val, bytes):
                                    mem_bytes = int.from_bytes(val, "little")
                                    break
                            except Exception:
                                pass

                        # Score dedicated GPUs higher (RTX/GTX/Arc/Radeon RX)
                        upper = desc_str.upper()
                        score = 1
                        if any(k in upper for k in ("RTX", "GTX", "RADEON RX", "ARC", "QUADRO")):
                            score = 3
                        elif any(k in upper for k in ("GEFORCE", "RADEON", "IRIS")):
                            score = 2

                        candidates.append((score, mem_bytes, desc_str))
                    except Exception:
                        pass
                except OSError:
                    break

            if candidates:
                candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
                _, mem_bytes, best_name = candidates[0]
                telemetry.gpu_available = True
                telemetry.gpu_name = best_name
                telemetry.gpu_mem_total_bytes = mem_bytes
        except Exception:
            pass

    def _poll_linux_gpu(self, telemetry: SystemTelemetry) -> None:
        """Query GPU via lspci on Linux."""
        try:
            res = subprocess.run(
                ["lspci"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    lower = line.lower()
                    if "vga compatible controller" in lower or "3d controller" in lower:
                        gpu_name = line.split(":", 2)[-1].strip()
                        telemetry.gpu_available = True
                        telemetry.gpu_name = gpu_name
                        return
        except Exception:
            pass

    def _poll_macos_gpu(self, telemetry: SystemTelemetry) -> None:
        """Query GPU on macOS via system_profiler."""
        try:
            res = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "Chipset Model:" in line:
                        telemetry.gpu_available = True
                        telemetry.gpu_name = line.split(":", 1)[1].strip()
                        return
        except Exception:
            pass

    @staticmethod
    def adjust_process_priority(pid: Optional[int] = None) -> None:
        """Sets process priority to below-normal to keep UI and OS responsive."""
        if psutil is None:
            return

        try:
            target_pid = pid or os.getpid()
            proc = psutil.Process(target_pid)
            if sys.platform == "win32" and hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
                proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:
                current_nice = proc.nice()
                if current_nice < 10:
                    proc.nice(10)
        except Exception:
            pass
