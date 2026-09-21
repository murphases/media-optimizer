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
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None

# Optional NVIDIA NVML
HAS_NVML = False
try:
    import pynvml
    pynvml.nvmlInit()
    HAS_NVML = True
except Exception:
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


@dataclass
class SystemTelemetry:
    """Snapshot of system resource usage."""

    cpu_percent: float = 0.0
    cpu_count: int = 1
    cpu_name: str = "Unknown CPU"

    ram_total_bytes: int = 0
    ram_used_bytes: int = 0
    ram_percent: float = 0.0

    gpu_available: bool = False
    gpu_name: str = "N/A"
    gpu_load_percent: float = 0.0
    gpu_mem_total_bytes: int = 0
    gpu_mem_used_bytes: int = 0
    gpu_temp_c: float = 0.0

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

        # Windows-specific registry/wmic lookup for friendly name
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
        return telemetry

    def _poll_gpu(self, telemetry: SystemTelemetry) -> None:
        """Poll NVIDIA or system GPU metrics."""
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

        # Fallback to nvidia-smi if installed
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

    @staticmethod
    def adjust_process_priority(pid: Optional[int] = None) -> None:
        """Sets process priority to below-normal to keep UI and OS responsive."""
        if psutil is None:
            return

        try:
            target_pid = pid or os.getpid()
            proc = psutil.Process(target_pid)
            if sys.platform == "win32":
                proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:
                current_nice = proc.nice()
                if current_nice < 10:
                    proc.nice(10)
        except Exception:
            pass
