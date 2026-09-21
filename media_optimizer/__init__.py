"""
Media Optimizer - Professional Photo and Video Converter & Optimizer.
High performance, atomic writes, hardware acceleration, zero setup.
"""

__version__ = "1.0.0"
__author__ = "Paulo / murphases"
__license__ = "PolyForm Noncommercial 1.0.0"

from media_optimizer.config import ConfigManager, OptimizerSettings
from media_optimizer.hardware import HardwareMonitor, SystemTelemetry
from media_optimizer.converter import ImageConverter
from media_optimizer.image_optimizer import ImageOptimizer
from media_optimizer.video_optimizer import VideoOptimizer
from media_optimizer.pipeline import PipelineOrchestrator

__all__ = [
    "__version__",
    "ConfigManager",
    "OptimizerSettings",
    "HardwareMonitor",
    "SystemTelemetry",
    "ImageConverter",
    "ImageOptimizer",
    "VideoOptimizer",
    "PipelineOrchestrator",
]
