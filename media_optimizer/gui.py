"""
Modern, intuitive, and responsive GUI for Media Optimizer using CustomTkinter.
Features live hardware telemetry, modular tabs, customization, and non-blocking background workers.
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

from media_optimizer import __version__
from media_optimizer.config import ConfigManager, OptimizerSettings
from media_optimizer.ffmpeg_tools import FFmpegResolver
from media_optimizer.hardware import HardwareMonitor, SystemTelemetry, format_bytes, format_time
from media_optimizer.pipeline import PipelineOrchestrator, PipelineSummary
from media_optimizer.video_optimizer import VideoOptimizer


class QueueLogger(logging.Handler):
    """Custom logging handler that puts logs into a thread-safe UI queue."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.log_queue.put((record.levelno, msg))


class MediaOptimizerApp:
    """Modern Desktop GUI Application."""

    def __init__(self, root: Optional[ctk.CTk] = None):
        if ctk is None:
            raise RuntimeError("CustomTkinter não está instalado.")

        self.cfg_mgr = ConfigManager()
        self.settings: OptimizerSettings = self.cfg_mgr.load()

        # CustomTkinter theme setup
        ctk.set_appearance_mode(self.settings.theme)
        ctk.set_default_color_theme(self.settings.accent_color)

        self.root = root or ctk.CTk()
        self.root.title(f"Media Optimizer v{__version__} — Otimizador Profissional de Fotos e Vídeos")
        self.root.geometry("1280x780")
        self.root.minsize(1120, 680)

        self.hw_monitor = HardwareMonitor(
            memory_throttle_percent=self.settings.memory_threshold_percent
        )
        self.orchestrator = PipelineOrchestrator(
            settings=self.settings,
            hardware_monitor=self.hw_monitor,
        )

        self.log_queue: queue.Queue = queue.Queue()
        self._setup_logger()

        self.worker_thread: Optional[threading.Thread] = None
        self._build_ui()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after_idle(self.root.attributes, "-topmost", False)
        self.root.focus_force()
        self._start_telemetry_loop()
        self._start_log_consumer_loop()

    def _setup_logger(self) -> None:
        self.logger = logging.getLogger("MediaOptimizerApp")
        self.logger.setLevel(logging.INFO)
        q_handler = QueueLogger(self.log_queue)
        q_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
        self.logger.addHandler(q_handler)
        self.orchestrator.logger = self.logger

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=0)  # Left sidebar (Navigation) fixed width
        self.root.grid_columnconfigure(1, weight=1)  # Center area (Main Content) expands
        self.root.grid_columnconfigure(2, weight=0)  # Right sidebar (Metrics/Telemetry) fixed width
        self.root.grid_rowconfigure(0, weight=1)     # Content row expands
        self.root.grid_rowconfigure(1, weight=0)     # Bottom Console row

        # 1. Left Sidebar (Navigation, column 0, spans rows 0 and 1)
        self.sidebar_frame = ctk.CTkFrame(self.root, width=235, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        self._build_sidebar()

        # 2. Main Center Content Container (column 1, row 0)
        self.content_container = ctk.CTkFrame(self.root, corner_radius=8)
        self.content_container.grid(row=0, column=1, padx=10, pady=(10, 5), sticky="nsew")
        self.content_container.grid_rowconfigure(0, weight=1)
        self.content_container.grid_columnconfigure(0, weight=1)

        # Scrollable functional views inside container
        self.tab_pipeline = ctk.CTkScrollableFrame(self.content_container, corner_radius=8)
        self.tab_convert = ctk.CTkScrollableFrame(self.content_container, corner_radius=8)
        self.tab_opt_images = ctk.CTkScrollableFrame(self.content_container, corner_radius=8)
        self.tab_opt_videos = ctk.CTkScrollableFrame(self.content_container, corner_radius=8)
        self.tab_settings = ctk.CTkScrollableFrame(self.content_container, corner_radius=8)

        for tab_frame in (
            self.tab_pipeline,
            self.tab_convert,
            self.tab_opt_images,
            self.tab_opt_videos,
            self.tab_settings,
        ):
            tab_frame.grid(row=0, column=0, sticky="nsew")

        self._build_tab_pipeline()
        self._build_tab_convert()
        self._build_tab_opt_images()
        self._build_tab_opt_videos()
        self._build_tab_settings()

        # 3. Bottom Console & Progress Bar (column 1, row 1)
        self.bottom_frame = ctk.CTkFrame(self.root, corner_radius=8, height=185)
        self.bottom_frame.grid(row=1, column=1, padx=10, pady=(5, 10), sticky="ew")
        self._build_bottom_console()

        # 4. Right Sidebar (Metrics/Telemetry, column 2, spans rows 0 and 1)
        self.metrics_sidebar = ctk.CTkFrame(self.root, width=265, corner_radius=0)
        self.metrics_sidebar.grid(row=0, column=2, rowspan=2, sticky="nsew")
        self.metrics_sidebar.grid_propagate(False)
        self._build_metrics_sidebar()

        # Activate initial tab
        self._select_tab("pipeline")

    def _build_sidebar(self) -> None:
        self.sidebar_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_frame.grid_rowconfigure(7, weight=1)  # Spacer pushing footer down

        # App Brand Header
        lbl_logo = ctk.CTkLabel(
            self.sidebar_frame,
            text="⚡ Media Optimizer",
            font=ctk.CTkFont(size=17, weight="bold"),
            anchor="w",
        )
        lbl_logo.grid(row=0, column=0, padx=20, pady=(20, 2), sticky="w")

        lbl_subtitle = ctk.CTkLabel(
            self.sidebar_frame,
            text="Fotos & Vídeos • Alta Fidelidade",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray50"),
            anchor="w",
        )
        lbl_subtitle.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="w")

        # Nav Buttons
        nav_items = [
            ("pipeline", "🚀 Pipeline Completo"),
            ("convert", "📷 Conversão de Fotos"),
            ("opt_images", "🪄 Otimização de Fotos"),
            ("opt_videos", "🎬 Otimização de Vídeos"),
            ("settings", "⚙️ Configurações & Temas"),
        ]

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for idx, (key, title) in enumerate(nav_items, start=2):
            btn = ctk.CTkButton(
                self.sidebar_frame,
                text=title,
                height=42,
                corner_radius=8,
                anchor="w",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color="transparent",
                text_color=("gray15", "gray90"),
                hover_color=("gray80", "#2c3e50"),
                command=lambda k=key: self._select_tab(k),
            )
            btn.grid(row=idx, column=0, padx=12, pady=4, sticky="ew")
            self.nav_buttons[key] = btn

        # Bottom Footer in Sidebar: Buy Me a Coffee & Version
        btn_bmc = ctk.CTkButton(
            self.sidebar_frame,
            text="☕ Buy me a coffee",
            height=34,
            corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#FFDD00",
            hover_color="#e6c700",
            text_color="#000000",
            command=self._open_buy_me_a_coffee,
        )
        btn_bmc.grid(row=8, column=0, padx=12, pady=(10, 4), sticky="ew")

        lbl_ver = ctk.CTkLabel(
            self.sidebar_frame,
            text=f"v{__version__} • by murphases",
            font=ctk.CTkFont(size=10),
            text_color=("gray60", "gray50"),
        )
        lbl_ver.grid(row=9, column=0, padx=20, pady=(0, 15), sticky="s")

    def _select_tab(self, tab_key: str) -> None:
        self.active_tab = tab_key
        tab_frames = {
            "pipeline": self.tab_pipeline,
            "convert": self.tab_convert,
            "opt_images": self.tab_opt_images,
            "opt_videos": self.tab_opt_videos,
            "settings": self.tab_settings,
        }

        # Display active tab and hide all other tabs
        for key, frame in tab_frames.items():
            if key == tab_key:
                frame.grid(row=0, column=0, sticky="nsew")
                frame.lift()
            else:
                frame.grid_remove()

        # Hide execution logs area when in Settings tab to maximize workspace
        if tab_key == "settings":
            self.bottom_frame.grid_remove()
            self.content_container.grid(row=0, column=1, rowspan=2, padx=10, pady=10, sticky="nsew")
        else:
            self.content_container.grid(row=0, column=1, rowspan=1, padx=10, pady=(10, 5), sticky="nsew")
            self.bottom_frame.grid(row=1, column=1, padx=10, pady=(5, 10), sticky="ew")

        theme_fg = ctk.ThemeManager.theme["CTkButton"]["fg_color"]
        theme_hover = ctk.ThemeManager.theme["CTkButton"]["hover_color"]

        for key, btn in self.nav_buttons.items():
            if key == tab_key:
                btn.configure(
                    fg_color=theme_fg,
                    text_color="#ffffff",
                    hover_color=theme_hover,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=("gray15", "gray90"),
                    hover_color=("gray80", "#2c3e50"),
                )

    def _build_metrics_sidebar(self) -> None:
        self.metrics_sidebar.grid_columnconfigure(0, weight=1)

        # Header
        lbl_title = ctk.CTkLabel(
            self.metrics_sidebar,
            text="📊 Desempenho",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        )
        lbl_title.grid(row=0, column=0, padx=16, pady=(18, 2), sticky="w")

        lbl_desc = ctk.CTkLabel(
            self.metrics_sidebar,
            text="Telemetria em Tempo Real",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray50"),
            anchor="w",
        )
        lbl_desc.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="w")

        # 1. CPU Card
        card_cpu = ctk.CTkFrame(self.metrics_sidebar, corner_radius=8)
        card_cpu.grid(row=2, column=0, padx=12, pady=5, sticky="ew")
        card_cpu.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card_cpu,
            text="🖥️ Processador (CPU)",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")

        self.lbl_cpu_model = ctk.CTkLabel(
            card_cpu,
            text="Carregando...",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            anchor="w",
        )
        self.lbl_cpu_model.grid(row=1, column=0, padx=12, pady=1, sticky="w")

        self.lbl_cpu_usage = ctk.CTkLabel(
            card_cpu,
            text="0% em uso",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self.lbl_cpu_usage.grid(row=2, column=0, padx=12, pady=(4, 2), sticky="w")

        self.prog_cpu = ctk.CTkProgressBar(card_cpu, height=8)
        self.prog_cpu.set(0.0)
        self.prog_cpu.grid(row=3, column=0, padx=12, pady=(2, 10), sticky="ew")

        # 2. RAM Card
        card_ram = ctk.CTkFrame(self.metrics_sidebar, corner_radius=8)
        card_ram.grid(row=3, column=0, padx=12, pady=5, sticky="ew")
        card_ram.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card_ram,
            text="🧠 Memória RAM",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")

        self.lbl_ram_text = ctk.CTkLabel(
            card_ram,
            text="Carregando...",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            anchor="w",
        )
        self.lbl_ram_text.grid(row=1, column=0, padx=12, pady=1, sticky="w")

        self.lbl_ram_usage = ctk.CTkLabel(
            card_ram,
            text="0% em uso",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self.lbl_ram_usage.grid(row=2, column=0, padx=12, pady=(4, 2), sticky="w")

        self.prog_ram = ctk.CTkProgressBar(card_ram, height=8)
        self.prog_ram.set(0.0)
        self.prog_ram.grid(row=3, column=0, padx=12, pady=(2, 10), sticky="ew")

        # 3. GPU Card
        card_gpu = ctk.CTkFrame(self.metrics_sidebar, corner_radius=8)
        card_gpu.grid(row=4, column=0, padx=12, pady=5, sticky="ew")
        card_gpu.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card_gpu,
            text="🎮 Placa de Vídeo (GPU)",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")

        self.lbl_gpu_model = ctk.CTkLabel(
            card_gpu,
            text="Detectando...",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            anchor="w",
        )
        self.lbl_gpu_model.grid(row=1, column=0, padx=12, pady=1, sticky="w")

        self.lbl_gpu_encoder = ctk.CTkLabel(
            card_gpu,
            text="Codec: Carregando...",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self.lbl_gpu_encoder.grid(row=2, column=0, padx=12, pady=(4, 2), sticky="w")

        self.prog_gpu = ctk.CTkProgressBar(card_gpu, height=8)
        self.prog_gpu.set(0.0)
        self.prog_gpu.grid(row=3, column=0, padx=12, pady=(2, 4), sticky="ew")

        self.lbl_gpu_extra = ctk.CTkLabel(
            card_gpu,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            anchor="w",
        )
        self.lbl_gpu_extra.grid(row=4, column=0, padx=12, pady=(0, 8), sticky="w")

        # 4. Protection & Stability Card
        card_prot = ctk.CTkFrame(self.metrics_sidebar, corner_radius=8)
        card_prot.grid(row=5, column=0, padx=12, pady=5, sticky="ew")
        card_prot.grid_columnconfigure(0, weight=1)

        self.lbl_throttle_badge = ctk.CTkLabel(
            card_prot,
            text="🛡️ Proteção: Normal",
            text_color="#2ecc71",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self.lbl_throttle_badge.grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")

        self.lbl_throttle_desc = ctk.CTkLabel(
            card_prot,
            text="Sistema estável e monitorado.",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            wraplength=210,
            justify="left",
            anchor="w",
        )
        self.lbl_throttle_desc.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")

        # Aliases for backwards compatibility
        self.lbl_cpu = self.lbl_cpu_usage
        self.lbl_ram = self.lbl_ram_usage
        self.lbl_gpu = self.lbl_gpu_encoder
        self.lbl_throttle = self.lbl_throttle_badge

    def _build_tab_pipeline(self) -> None:
        frame = self.tab_pipeline
        frame.grid_columnconfigure(1, weight=1)

        # Folder pickers
        ctk.CTkLabel(frame, text="Pasta de Origem:").grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self.entry_input = ctk.CTkEntry(frame, placeholder_text="Selecione a pasta de origem dos arquivos...")
        if self.settings.input_dir:
            self.entry_input.insert(0, self.settings.input_dir)
        self.entry_input.grid(row=0, column=1, padx=5, pady=8, sticky="ew")
        ctk.CTkButton(
            frame,
            text="Procurar...",
            width=90,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._browse_input,
        ).grid(row=0, column=2, padx=10, pady=8)

        ctk.CTkLabel(frame, text="Saída Fotos Otimizadas:").grid(row=1, column=0, padx=10, pady=8, sticky="w")
        self.entry_out_images = ctk.CTkEntry(frame, placeholder_text="Selecione a pasta de saída para fotos otimizadas...")
        if self.settings.optimized_images_dir:
            self.entry_out_images.insert(0, self.settings.optimized_images_dir)
        self.entry_out_images.grid(row=1, column=1, padx=5, pady=8, sticky="ew")
        ctk.CTkButton(
            frame,
            text="Procurar...",
            width=90,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_out_images),
        ).grid(row=1, column=2, padx=10, pady=8)

        ctk.CTkLabel(frame, text="Saída Vídeos Otimizados:").grid(row=2, column=0, padx=10, pady=8, sticky="w")
        self.entry_out_videos = ctk.CTkEntry(frame, placeholder_text="Selecione a pasta de saída para vídeos otimizados...")
        if self.settings.optimized_videos_dir:
            self.entry_out_videos.insert(0, self.settings.optimized_videos_dir)
        self.entry_out_videos.grid(row=2, column=1, padx=5, pady=8, sticky="ew")
        ctk.CTkButton(
            frame,
            text="Procurar...",
            width=90,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_out_videos),
        ).grid(row=2, column=2, padx=10, pady=8)

        # Switches
        switch_frame = ctk.CTkFrame(frame, fg_color="transparent")
        switch_frame.grid(row=3, column=0, columnspan=3, pady=10, sticky="w")

        self.chk_dry_run = ctk.CTkCheckBox(switch_frame, text="Modo Simulação (Dry-Run)")
        if self.settings.dry_run:
            self.chk_dry_run.select()
        self.chk_dry_run.pack(side="left", padx=10)

        self.chk_skip_existing = ctk.CTkCheckBox(switch_frame, text="Pular Arquivos Já Processados (Resume)")
        if self.settings.skip_existing:
            self.chk_skip_existing.select()
        self.chk_skip_existing.pack(side="left", padx=10)

        # Action Buttons
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.grid(row=4, column=0, columnspan=3, pady=20)

        self.btn_start = ctk.CTkButton(
            btn_frame,
            text="▶️ Iniciar Pipeline Completo",
            fg_color=("#1e8449", "#1e8449"),
            hover_color=("#196f3d", "#196f3d"),
            text_color="#ffffff",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            command=self._start_pipeline,
        )
        self.btn_start.pack(side="left", padx=10)

        self.btn_pause = ctk.CTkButton(
            btn_frame,
            text="⏸️ Pausar",
            fg_color=("#f39c12", "#f39c12"),
            hover_color=("#d68910", "#d68910"),
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40,
            state="disabled",
            command=self._toggle_pause,
        )
        self.btn_pause.pack(side="left", padx=10)

        self.btn_cancel = ctk.CTkButton(
            btn_frame,
            text="⏹️ Cancelar",
            fg_color=("#c0392b", "#c0392b"),
            hover_color=("#962d22", "#962d22"),
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40,
            state="disabled",
            command=self._cancel_pipeline,
        )
        self.btn_cancel.pack(side="left", padx=10)

        # Summary box
        self.lbl_summary = ctk.CTkLabel(
            frame,
            text="Pronto para processar. Selecione a pasta de origem e clique em Iniciar.",
            font=ctk.CTkFont(size=13),
        )
        self.lbl_summary.grid(row=5, column=0, columnspan=3, pady=10)

    def _format_crf_label(self, crf: int) -> str:
        if crf < 20:
            return f"{crf} (Fidelidade)"
        elif crf <= 24:
            return f"{crf} (Equilibrado)"
        else:
            return f"{crf} (Compactação)"

    def _build_tab_convert(self) -> None:
        frame = self.tab_convert
        frame.grid_columnconfigure(1, weight=1)

        # Folder pickers for conversion
        ctk.CTkLabel(frame, text="Pasta de Origem (Fotos):").grid(row=0, column=0, padx=10, pady=6, sticky="w")
        self.entry_conv_input = ctk.CTkEntry(frame, placeholder_text="Selecione a pasta com fotos para converter (HEIC, RAW, AVIF, PNG)...")
        if self.settings.input_dir:
            self.entry_conv_input.insert(0, self.settings.input_dir)
        self.entry_conv_input.grid(row=0, column=1, padx=5, pady=6, sticky="ew")
        ctk.CTkButton(
            frame,
            text="Procurar...",
            width=90,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_conv_input),
        ).grid(row=0, column=2, padx=10, pady=6)

        ctk.CTkLabel(frame, text="Pasta de Saída (JPG Convertidos):").grid(row=1, column=0, padx=10, pady=6, sticky="w")
        self.entry_conv_output = ctk.CTkEntry(frame, placeholder_text="Selecione a pasta de saída para fotos convertidas...")
        if self.settings.converted_dir:
            self.entry_conv_output.insert(0, self.settings.converted_dir)
        self.entry_conv_output.grid(row=1, column=1, padx=5, pady=6, sticky="ew")
        ctk.CTkButton(
            frame,
            text="Procurar...",
            width=90,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_conv_output),
        ).grid(row=1, column=2, padx=10, pady=6)

        ctk.CTkLabel(frame, text="Qualidade Inicial do JPG:").grid(row=2, column=0, padx=10, pady=8, sticky="w")
        self.slider_conv_qual = ctk.CTkSlider(
            frame,
            from_=50,
            to=100,
            number_of_steps=50,
            command=lambda v: self.lbl_conv_qual_val.configure(text=f"{int(v)}%"),
        )
        self.slider_conv_qual.set(self.settings.convert_quality)
        self.slider_conv_qual.grid(row=2, column=1, padx=5, pady=8, sticky="ew")
        self.lbl_conv_qual_val = ctk.CTkLabel(
            frame,
            text=f"{self.settings.convert_quality}%",
            width=60,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_conv_qual_val.grid(row=2, column=2, padx=10, pady=8)

        ctk.CTkLabel(frame, text="Processos Paralelos (Workers):").grid(row=3, column=0, padx=10, pady=8, sticky="w")
        self.slider_conv_workers = ctk.CTkSlider(
            frame,
            from_=1,
            to=32,
            number_of_steps=31,
            command=lambda v: self.lbl_conv_workers_val.configure(text=f"{int(v)} threads"),
        )
        self.slider_conv_workers.set(self.settings.convert_workers)
        self.slider_conv_workers.grid(row=3, column=1, padx=5, pady=8, sticky="ew")
        self.lbl_conv_workers_val = ctk.CTkLabel(
            frame,
            text=f"{self.settings.convert_workers} threads",
            width=80,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_conv_workers_val.grid(row=3, column=2, padx=10, pady=8)

        ctk.CTkButton(
            frame,
            text="▶️ Executar Apenas Conversão",
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=("#1f6aa5", "#1f6aa5"),
            hover_color=("#144f7c", "#144f7c"),
            text_color="#ffffff",
            command=lambda: self._start_single_stage(1),
        ).grid(row=4, column=0, columnspan=3, pady=20)

    def _build_tab_opt_images(self) -> None:
        frame = self.tab_opt_images
        frame.grid_columnconfigure(1, weight=1)

        # Folder pickers for image optimization
        ctk.CTkLabel(frame, text="Pasta de Origem (Fotos):").grid(row=0, column=0, padx=10, pady=6, sticky="w")
        self.entry_opt_img_input = ctk.CTkEntry(frame, placeholder_text="Selecione a pasta com fotos para otimizar...")
        initial_img_input = self.settings.converted_dir or self.settings.input_dir
        if initial_img_input:
            self.entry_opt_img_input.insert(0, initial_img_input)
        self.entry_opt_img_input.grid(row=0, column=1, padx=5, pady=6, sticky="ew")
        ctk.CTkButton(
            frame,
            text="Procurar...",
            width=90,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_opt_img_input),
        ).grid(row=0, column=2, padx=10, pady=6)

        ctk.CTkLabel(frame, text="Pasta de Saída (Fotos Otimizadas):").grid(row=1, column=0, padx=10, pady=6, sticky="w")
        self.entry_opt_img_output = ctk.CTkEntry(frame, placeholder_text="Selecione a pasta de saída para fotos otimizadas...")
        if self.settings.optimized_images_dir:
            self.entry_opt_img_output.insert(0, self.settings.optimized_images_dir)
        self.entry_opt_img_output.grid(row=1, column=1, padx=5, pady=6, sticky="ew")
        ctk.CTkButton(
            frame,
            text="Procurar...",
            width=90,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_opt_img_output),
        ).grid(row=1, column=2, padx=10, pady=6)

        ctk.CTkLabel(frame, text="Dimensão Máxima (px):").grid(row=2, column=0, padx=10, pady=8, sticky="w")
        self.slider_opt_dim = ctk.CTkSlider(
            frame,
            from_=800,
            to=3840,
            number_of_steps=38,
            command=lambda v: self.lbl_opt_dim_val.configure(text=f"{int(v)} px"),
        )
        self.slider_opt_dim.set(self.settings.opt_image_max_dim)
        self.slider_opt_dim.grid(row=2, column=1, padx=5, pady=8, sticky="ew")
        self.lbl_opt_dim_val = ctk.CTkLabel(
            frame,
            text=f"{self.settings.opt_image_max_dim} px",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_opt_dim_val.grid(row=2, column=2, padx=10, pady=8)

        ctk.CTkLabel(frame, text="Qualidade de Compressão (%):").grid(row=3, column=0, padx=10, pady=8, sticky="w")
        self.slider_opt_qual = ctk.CTkSlider(
            frame,
            from_=50,
            to=95,
            number_of_steps=45,
            command=lambda v: self.lbl_opt_qual_val.configure(text=f"{int(v)}%"),
        )
        self.slider_opt_qual.set(self.settings.opt_image_quality)
        self.slider_opt_qual.grid(row=3, column=1, padx=5, pady=8, sticky="ew")
        self.lbl_opt_qual_val = ctk.CTkLabel(
            frame,
            text=f"{self.settings.opt_image_quality}%",
            width=60,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_opt_qual_val.grid(row=3, column=2, padx=10, pady=8)

        ctk.CTkButton(
            frame,
            text="▶️ Executar Apenas Otimização de Fotos",
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=("#1f6aa5", "#1f6aa5"),
            hover_color=("#144f7c", "#144f7c"),
            text_color="#ffffff",
            command=lambda: self._start_single_stage(2),
        ).grid(row=4, column=0, columnspan=3, pady=20)

    def _build_tab_opt_videos(self) -> None:
        frame = self.tab_opt_videos
        frame.grid_columnconfigure(1, weight=1)

        # Folder pickers for videos
        ctk.CTkLabel(frame, text="Pasta de Origem (Vídeos):").grid(row=0, column=0, padx=10, pady=6, sticky="w")
        self.entry_vid_input = ctk.CTkEntry(frame, placeholder_text="Selecione a pasta com vídeos para otimizar...")
        if self.settings.input_dir:
            self.entry_vid_input.insert(0, self.settings.input_dir)
        self.entry_vid_input.grid(row=0, column=1, padx=5, pady=6, sticky="ew")
        ctk.CTkButton(
            frame,
            text="Procurar...",
            width=90,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_vid_input),
        ).grid(row=0, column=2, padx=10, pady=6)

        ctk.CTkLabel(frame, text="Pasta de Saída (Vídeos):").grid(row=1, column=0, padx=10, pady=6, sticky="w")
        self.entry_vid_output = ctk.CTkEntry(frame, placeholder_text="Selecione a pasta de saída para vídeos otimizados...")
        if self.settings.optimized_videos_dir:
            self.entry_vid_output.insert(0, self.settings.optimized_videos_dir)
        self.entry_vid_output.grid(row=1, column=1, padx=5, pady=6, sticky="ew")
        ctk.CTkButton(
            frame,
            text="Procurar...",
            width=90,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_vid_output),
        ).grid(row=1, column=2, padx=10, pady=6)

        # Dimension
        ctk.CTkLabel(frame, text="Resolução Máxima Lado Maior (px):").grid(row=2, column=0, padx=10, pady=6, sticky="w")
        self.slider_vid_dim = ctk.CTkSlider(
            frame,
            from_=720,
            to=3840,
            number_of_steps=31,
            command=lambda v: self.lbl_vid_dim_val.configure(text=f"{int(v)} px"),
        )
        self.slider_vid_dim.set(self.settings.opt_video_max_dim)
        self.slider_vid_dim.grid(row=2, column=1, padx=5, pady=6, sticky="ew")
        self.lbl_vid_dim_val = ctk.CTkLabel(
            frame,
            text=f"{self.settings.opt_video_max_dim} px",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_vid_dim_val.grid(row=2, column=2, padx=10, pady=6)

        # FPS
        ctk.CTkLabel(frame, text="Limite de FPS (mantém se menor):").grid(row=3, column=0, padx=10, pady=6, sticky="w")
        self.slider_vid_fps = ctk.CTkSlider(
            frame,
            from_=24,
            to=60,
            number_of_steps=36,
            command=lambda v: self.lbl_vid_fps_val.configure(text=f"{int(v)} fps"),
        )
        self.slider_vid_fps.set(self.settings.opt_video_max_fps)
        self.slider_vid_fps.grid(row=3, column=1, padx=5, pady=6, sticky="ew")
        self.lbl_vid_fps_val = ctk.CTkLabel(
            frame,
            text=f"{self.settings.opt_video_max_fps} fps",
            width=60,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_vid_fps_val.grid(row=3, column=2, padx=10, pady=6)

        # Format & Codec
        opt_row_frame = ctk.CTkFrame(frame, fg_color="transparent")
        opt_row_frame.grid(row=4, column=0, columnspan=3, pady=6, sticky="w")

        ctk.CTkLabel(opt_row_frame, text="Formato:").pack(side="left", padx=(10, 5))
        self.opt_vid_format = ctk.CTkOptionMenu(opt_row_frame, values=["mov", "mp4", "mkv"], width=100)
        self.opt_vid_format.set(self.settings.opt_video_format)
        self.opt_vid_format.pack(side="left", padx=5)

        ctk.CTkLabel(opt_row_frame, text="Codec:").pack(side="left", padx=(20, 5))
        self.opt_vid_codec = ctk.CTkOptionMenu(
            opt_row_frame,
            values=["auto", "h264_nvenc", "h264_qsv", "h264_amf", "libx264"],
            width=130
        )
        self.opt_vid_codec.set(self.settings.opt_video_codec)
        self.opt_vid_codec.pack(side="left", padx=5)

        # CRF (Quality)
        ctk.CTkLabel(frame, text="Qualidade / CRF (18 máx - 32 mín):").grid(row=5, column=0, padx=10, pady=6, sticky="w")
        self.slider_vid_crf = ctk.CTkSlider(
            frame,
            from_=18,
            to=32,
            number_of_steps=14,
            command=lambda v: self.lbl_vid_crf_val.configure(text=self._format_crf_label(int(v))),
        )
        self.slider_vid_crf.set(self.settings.opt_video_crf)
        self.slider_vid_crf.grid(row=5, column=1, padx=5, pady=6, sticky="ew")
        self.lbl_vid_crf_val = ctk.CTkLabel(
            frame,
            text=self._format_crf_label(self.settings.opt_video_crf),
            width=130,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_vid_crf_val.grid(row=5, column=2, padx=10, pady=6)

        # Parallel Workers
        ctk.CTkLabel(frame, text="Processos Paralelos (Workers):").grid(row=6, column=0, padx=10, pady=6, sticky="w")
        self.slider_vid_workers = ctk.CTkSlider(
            frame,
            from_=1,
            to=8,
            number_of_steps=7,
            command=lambda v: self.lbl_vid_workers_val.configure(text=f"{int(v)} threads"),
        )
        self.slider_vid_workers.set(self.settings.opt_video_workers)
        self.slider_vid_workers.grid(row=6, column=1, padx=5, pady=6, sticky="ew")
        self.lbl_vid_workers_val = ctk.CTkLabel(
            frame,
            text=f"{self.settings.opt_video_workers} threads",
            width=80,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_vid_workers_val.grid(row=6, column=2, padx=10, pady=6)

        ctk.CTkButton(
            frame,
            text="▶️ Executar Apenas Otimização de Vídeos",
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=("#1f6aa5", "#1f6aa5"),
            hover_color=("#144f7c", "#144f7c"),
            text_color="#ffffff",
            command=lambda: self._start_single_stage(3),
        ).grid(row=7, column=0, columnspan=3, pady=15)

    def _build_tab_settings(self) -> None:
        frame = self.tab_settings
        frame.grid_columnconfigure(0, weight=1)

        # Header Title
        lbl_head = ctk.CTkLabel(
            frame,
            text="⚙️  Configurações & Preferências do Sistema",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        )
        lbl_head.grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")

        lbl_sub = ctk.CTkLabel(
            frame,
            text="Defina os parâmetros padrão de desempenho, limites do hardware, conversão de fotos e codificação de vídeos.",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray70"),
            anchor="w",
        )
        lbl_sub.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")

        # -----------------------------------------------------------------
        # CARD 1: Aparência e Interface
        # -----------------------------------------------------------------
        c_ui = ctk.CTkFrame(frame, corner_radius=8)
        c_ui.grid(row=2, column=0, padx=10, pady=6, sticky="ew")
        c_ui.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            c_ui,
            text="🎨  Interface & Aparência",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 8), sticky="w")

        ctk.CTkLabel(c_ui, text="Tema da Interface:").grid(row=1, column=0, padx=12, pady=6, sticky="w")
        self.opt_theme = ctk.CTkOptionMenu(
            c_ui,
            values=["Dark", "Light", "System"],
            command=self._change_theme,
            width=170,
        )
        self.opt_theme.set(self.settings.theme)
        self.opt_theme.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(c_ui, text="Cor de Destaque:").grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.opt_accent = ctk.CTkOptionMenu(
            c_ui,
            values=["blue", "dark-blue", "green"],
            width=170,
        )
        self.opt_accent.set(self.settings.accent_color)
        self.opt_accent.grid(row=2, column=1, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(c_ui, text="Idioma do App:").grid(row=3, column=0, padx=12, pady=(6, 10), sticky="w")
        self.opt_lang = ctk.CTkOptionMenu(
            c_ui,
            values=["Português (Brasil)", "English (US)"],
            width=170,
        )
        self.opt_lang.set("Português (Brasil)")
        self.opt_lang.grid(row=3, column=1, padx=6, pady=(6, 10), sticky="w")

        # -----------------------------------------------------------------
        # CARD 2: Segurança, Integridade & Proteção do Hardware
        # -----------------------------------------------------------------
        c_sec = ctk.CTkFrame(frame, corner_radius=8)
        c_sec.grid(row=3, column=0, padx=10, pady=6, sticky="ew")
        c_sec.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            c_sec,
            text="🛡️  Segurança, Integridade & Hardware",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 8), sticky="w")

        ctk.CTkLabel(c_sec, text="Limite RAM p/ Auto-Throttling:").grid(row=1, column=0, padx=12, pady=6, sticky="w")
        self.slider_mem_limit = ctk.CTkSlider(
            c_sec,
            from_=50,
            to=95,
            number_of_steps=45,
            command=lambda v: self.lbl_mem_limit_val.configure(text=f"{int(v)}%"),
        )
        self.slider_mem_limit.set(self.settings.memory_threshold_percent)
        self.slider_mem_limit.grid(row=1, column=1, padx=6, pady=6, sticky="ew")
        self.lbl_mem_limit_val = ctk.CTkLabel(
            c_sec,
            text=f"{int(self.settings.memory_threshold_percent)}%",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_mem_limit_val.grid(row=1, column=2, padx=12, pady=6)

        ctk.CTkLabel(c_sec, text="Pular Arquivos Já Existentes:").grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.sw_cfg_skip_existing = ctk.CTkSwitch(
            c_sec,
            text="Evitar reprocessar mídias que já existem no destino (Resume)",
        )
        if self.settings.skip_existing:
            self.sw_cfg_skip_existing.select()
        else:
            self.sw_cfg_skip_existing.deselect()
        self.sw_cfg_skip_existing.grid(row=2, column=1, columnspan=2, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(c_sec, text="Modo de Simulação (Dry-Run):").grid(row=3, column=0, padx=12, pady=6, sticky="w")
        self.sw_cfg_dry_run = ctk.CTkSwitch(
            c_sec,
            text="Simular operações sem gravar ou modificar arquivos no disco",
        )
        if self.settings.dry_run:
            self.sw_cfg_dry_run.select()
        else:
            self.sw_cfg_dry_run.deselect()
        self.sw_cfg_dry_run.grid(row=3, column=1, columnspan=2, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(c_sec, text="Garantia de Integridade:").grid(row=4, column=0, padx=12, pady=(6, 10), sticky="w")
        lbl_sec_badge = ctk.CTkLabel(
            c_sec,
            text="🔒 Origem Somente-Leitura • Escrita Atômica (.tmp) • EXIF/XMP e Timestamps Preservados",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#2ecc71",
        )
        lbl_sec_badge.grid(row=4, column=1, columnspan=2, padx=6, pady=(6, 10), sticky="w")

        # -----------------------------------------------------------------
        # CARD 3: Padrões de Fotos (Conversão & Otimização)
        # -----------------------------------------------------------------
        c_photo = ctk.CTkFrame(frame, corner_radius=8)
        c_photo.grid(row=4, column=0, padx=10, pady=6, sticky="ew")
        c_photo.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            c_photo,
            text="🖼️  Padrões Globais de Fotos",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 8), sticky="w")

        ctk.CTkLabel(c_photo, text="Formato Alvo de Conversão:").grid(row=1, column=0, padx=12, pady=6, sticky="w")
        self.opt_cfg_conv_format = ctk.CTkOptionMenu(
            c_photo,
            values=["JPG", "WEBP", "PNG"],
            width=170,
        )
        self.opt_cfg_conv_format.set(self.settings.convert_target_format)
        self.opt_cfg_conv_format.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(c_photo, text="Qualidade de Conversão:").grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.slider_cfg_conv_qual = ctk.CTkSlider(
            c_photo,
            from_=70,
            to=100,
            number_of_steps=30,
            command=lambda v: self.lbl_cfg_conv_qual_val.configure(text=f"{int(v)}%"),
        )
        self.slider_cfg_conv_qual.set(self.settings.convert_quality)
        self.slider_cfg_conv_qual.grid(row=2, column=1, padx=6, pady=6, sticky="ew")
        self.lbl_cfg_conv_qual_val = ctk.CTkLabel(
            c_photo,
            text=f"{self.settings.convert_quality}%",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_cfg_conv_qual_val.grid(row=2, column=2, padx=12, pady=6)

        ctk.CTkLabel(c_photo, text="Suporte a Câmeras RAW:").grid(row=3, column=0, padx=12, pady=6, sticky="w")
        self.sw_cfg_raw = ctk.CTkSwitch(
            c_photo,
            text="Converter formatos profissionais (.CR2, .NEF, .ARW, .DNG, .ORF)",
        )
        if self.settings.convert_raw_enabled:
            self.sw_cfg_raw.select()
        else:
            self.sw_cfg_raw.deselect()
        self.sw_cfg_raw.grid(row=3, column=1, columnspan=2, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(c_photo, text="Dimensão Máxima Padrão:").grid(row=4, column=0, padx=12, pady=6, sticky="w")
        self.slider_cfg_opt_dim = ctk.CTkSlider(
            c_photo,
            from_=1080,
            to=3840,
            number_of_steps=276,
            command=lambda v: self.lbl_cfg_opt_dim_val.configure(text=f"{int(v)} px"),
        )
        self.slider_cfg_opt_dim.set(self.settings.opt_image_max_dim)
        self.slider_cfg_opt_dim.grid(row=4, column=1, padx=6, pady=6, sticky="ew")
        self.lbl_cfg_opt_dim_val = ctk.CTkLabel(
            c_photo,
            text=f"{self.settings.opt_image_max_dim} px",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_cfg_opt_dim_val.grid(row=4, column=2, padx=12, pady=6)

        ctk.CTkLabel(c_photo, text="Qualidade Otimização JPEG:").grid(row=5, column=0, padx=12, pady=6, sticky="w")
        self.slider_cfg_opt_qual = ctk.CTkSlider(
            c_photo,
            from_=50,
            to=95,
            number_of_steps=45,
            command=lambda v: self.lbl_cfg_opt_qual_val.configure(text=f"{int(v)}%"),
        )
        self.slider_cfg_opt_qual.set(self.settings.opt_image_quality)
        self.slider_cfg_opt_qual.grid(row=5, column=1, padx=6, pady=6, sticky="ew")
        self.lbl_cfg_opt_qual_val = ctk.CTkLabel(
            c_photo,
            text=f"{self.settings.opt_image_quality}%",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_cfg_opt_qual_val.grid(row=5, column=2, padx=12, pady=6)

        ctk.CTkLabel(c_photo, text="Compressão Avançada:").grid(row=6, column=0, padx=12, pady=6, sticky="w")
        sw_row = ctk.CTkFrame(c_photo, fg_color="transparent")
        sw_row.grid(row=6, column=1, columnspan=2, padx=6, pady=6, sticky="w")
        self.sw_cfg_opt_tables = ctk.CTkSwitch(sw_row, text="Otimizar Tabelas Huffman")
        if self.settings.opt_image_optimize_tables:
            self.sw_cfg_opt_tables.select()
        else:
            self.sw_cfg_opt_tables.deselect()
        self.sw_cfg_opt_tables.pack(side="left", padx=(0, 15))

        self.sw_cfg_opt_prog = ctk.CTkSwitch(sw_row, text="JPEG Progressivo")
        if self.settings.opt_image_progressive:
            self.sw_cfg_opt_prog.select()
        else:
            self.sw_cfg_opt_prog.deselect()
        self.sw_cfg_opt_prog.pack(side="left")

        ctk.CTkLabel(c_photo, text="Threads Simultâneas (Fotos):").grid(row=7, column=0, padx=12, pady=(6, 10), sticky="w")
        self.slider_cfg_img_workers = ctk.CTkSlider(
            c_photo,
            from_=1,
            to=16,
            number_of_steps=15,
            command=lambda v: self.lbl_cfg_img_workers_val.configure(text=f"{int(v)} threads"),
        )
        self.slider_cfg_img_workers.set(self.settings.opt_image_workers)
        self.slider_cfg_img_workers.grid(row=7, column=1, padx=6, pady=(6, 10), sticky="ew")
        self.lbl_cfg_img_workers_val = ctk.CTkLabel(
            c_photo,
            text=f"{self.settings.opt_image_workers} threads",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_cfg_img_workers_val.grid(row=7, column=2, padx=12, pady=(6, 10))

        # -----------------------------------------------------------------
        # CARD 4: Padrões de Vídeos
        # -----------------------------------------------------------------
        c_vid = ctk.CTkFrame(frame, corner_radius=8)
        c_vid.grid(row=5, column=0, padx=10, pady=6, sticky="ew")
        c_vid.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            c_vid,
            text="🎬  Padrões Globais de Vídeos",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 8), sticky="w")

        ctk.CTkLabel(c_vid, text="Contêiner / Formato:").grid(row=1, column=0, padx=12, pady=6, sticky="w")
        self.opt_cfg_vid_format = ctk.CTkOptionMenu(
            c_vid,
            values=["mov", "mp4", "mkv"],
            width=170,
        )
        self.opt_cfg_vid_format.set(self.settings.opt_video_format)
        self.opt_cfg_vid_format.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(c_vid, text="Codec / Acelerador:").grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.opt_cfg_vid_codec = ctk.CTkOptionMenu(
            c_vid,
            values=["auto", "h264_nvenc", "h264_qsv", "h264_amf", "libx264"],
            width=170,
        )
        self.opt_cfg_vid_codec.set(self.settings.opt_video_codec)
        self.opt_cfg_vid_codec.grid(row=2, column=1, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(c_vid, text="Resolução Máxima:").grid(row=3, column=0, padx=12, pady=6, sticky="w")
        self.slider_cfg_vid_dim = ctk.CTkSlider(
            c_vid,
            from_=720,
            to=3840,
            number_of_steps=312,
            command=lambda v: self.lbl_cfg_vid_dim_val.configure(text=f"{int(v)} px"),
        )
        self.slider_cfg_vid_dim.set(self.settings.opt_video_max_dim)
        self.slider_cfg_vid_dim.grid(row=3, column=1, padx=6, pady=6, sticky="ew")
        self.lbl_cfg_vid_dim_val = ctk.CTkLabel(
            c_vid,
            text=f"{self.settings.opt_video_max_dim} px",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_cfg_vid_dim_val.grid(row=3, column=2, padx=12, pady=6)

        ctk.CTkLabel(c_vid, text="Taxa Máxima de FPS:").grid(row=4, column=0, padx=12, pady=6, sticky="w")
        self.slider_cfg_vid_fps = ctk.CTkSlider(
            c_vid,
            from_=24,
            to=60,
            number_of_steps=36,
            command=lambda v: self.lbl_cfg_vid_fps_val.configure(text=f"{int(v)} fps"),
        )
        self.slider_cfg_vid_fps.set(self.settings.opt_video_max_fps)
        self.slider_cfg_vid_fps.grid(row=4, column=1, padx=6, pady=6, sticky="ew")
        self.lbl_cfg_vid_fps_val = ctk.CTkLabel(
            c_vid,
            text=f"{self.settings.opt_video_max_fps} fps",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_cfg_vid_fps_val.grid(row=4, column=2, padx=12, pady=6)

        ctk.CTkLabel(c_vid, text="Qualidade / CRF:").grid(row=5, column=0, padx=12, pady=6, sticky="w")
        self.slider_cfg_vid_crf = ctk.CTkSlider(
            c_vid,
            from_=18,
            to=32,
            number_of_steps=14,
            command=lambda v: self.lbl_cfg_vid_crf_val.configure(text=self._format_crf_label(int(v))),
        )
        self.slider_cfg_vid_crf.set(self.settings.opt_video_crf)
        self.slider_cfg_vid_crf.grid(row=5, column=1, padx=6, pady=6, sticky="ew")
        self.lbl_cfg_vid_crf_val = ctk.CTkLabel(
            c_vid,
            text=self._format_crf_label(self.settings.opt_video_crf),
            width=130,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_cfg_vid_crf_val.grid(row=5, column=2, padx=12, pady=6)

        ctk.CTkLabel(c_vid, text="Bitrate do Áudio:").grid(row=6, column=0, padx=12, pady=6, sticky="w")
        self.opt_cfg_vid_audio = ctk.CTkOptionMenu(
            c_vid,
            values=["96k", "128k", "192k", "256k", "320k"],
            width=170,
        )
        self.opt_cfg_vid_audio.set(self.settings.opt_video_audio_bitrate)
        self.opt_cfg_vid_audio.grid(row=6, column=1, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(c_vid, text="Workers Paralelos (Vídeos):").grid(row=7, column=0, padx=12, pady=(6, 10), sticky="w")
        self.slider_cfg_vid_workers = ctk.CTkSlider(
            c_vid,
            from_=1,
            to=8,
            number_of_steps=7,
            command=lambda v: self.lbl_cfg_vid_workers_val.configure(text=f"{int(v)} threads"),
        )
        self.slider_cfg_vid_workers.set(self.settings.opt_video_workers)
        self.slider_cfg_vid_workers.grid(row=7, column=1, padx=6, pady=(6, 10), sticky="ew")
        self.lbl_cfg_vid_workers_val = ctk.CTkLabel(
            c_vid,
            text=f"{self.settings.opt_video_workers} threads",
            width=70,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_cfg_vid_workers_val.grid(row=7, column=2, padx=12, pady=(6, 10))

        # -----------------------------------------------------------------
        # CARD 5: Pastas Padrão do Workspace
        # -----------------------------------------------------------------
        c_dirs = ctk.CTkFrame(frame, corner_radius=8)
        c_dirs.grid(row=6, column=0, padx=10, pady=6, sticky="ew")
        c_dirs.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            c_dirs,
            text="📁  Pastas Padrão do Workspace",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 8), sticky="w")

        ctk.CTkLabel(c_dirs, text="Origem Padrão:").grid(row=1, column=0, padx=12, pady=5, sticky="w")
        self.entry_cfg_input = ctk.CTkEntry(c_dirs, placeholder_text="Pasta de origem padrão (opcional)...")
        if self.settings.input_dir:
            self.entry_cfg_input.insert(0, self.settings.input_dir)
        self.entry_cfg_input.grid(row=1, column=1, padx=6, pady=5, sticky="ew")
        ctk.CTkButton(
            c_dirs,
            text="Procurar...",
            width=80,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_cfg_input),
        ).grid(row=1, column=2, padx=12, pady=5)

        ctk.CTkLabel(c_dirs, text="Fotos Convertidas:").grid(row=2, column=0, padx=12, pady=5, sticky="w")
        self.entry_cfg_conv = ctk.CTkEntry(c_dirs, placeholder_text="Pasta padrão para fotos convertidas (opcional)...")
        if self.settings.converted_dir:
            self.entry_cfg_conv.insert(0, self.settings.converted_dir)
        self.entry_cfg_conv.grid(row=2, column=1, padx=6, pady=5, sticky="ew")
        ctk.CTkButton(
            c_dirs,
            text="Procurar...",
            width=80,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_cfg_conv),
        ).grid(row=2, column=2, padx=12, pady=5)

        ctk.CTkLabel(c_dirs, text="Fotos Otimizadas:").grid(row=3, column=0, padx=12, pady=5, sticky="w")
        self.entry_cfg_opt_img = ctk.CTkEntry(c_dirs, placeholder_text="Pasta padrão para fotos otimizadas (opcional)...")
        if self.settings.optimized_images_dir:
            self.entry_cfg_opt_img.insert(0, self.settings.optimized_images_dir)
        self.entry_cfg_opt_img.grid(row=3, column=1, padx=6, pady=5, sticky="ew")
        ctk.CTkButton(
            c_dirs,
            text="Procurar...",
            width=80,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_cfg_opt_img),
        ).grid(row=3, column=2, padx=12, pady=5)

        ctk.CTkLabel(c_dirs, text="Vídeos Otimizados:").grid(row=4, column=0, padx=12, pady=5, sticky="w")
        self.entry_cfg_opt_vid = ctk.CTkEntry(c_dirs, placeholder_text="Pasta padrão para vídeos otimizados (opcional)...")
        if self.settings.optimized_videos_dir:
            self.entry_cfg_opt_vid.insert(0, self.settings.optimized_videos_dir)
        self.entry_cfg_opt_vid.grid(row=4, column=1, padx=6, pady=5, sticky="ew")
        ctk.CTkButton(
            c_dirs,
            text="Procurar...",
            width=80,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_cfg_opt_vid),
        ).grid(row=4, column=2, padx=12, pady=5)

        ctk.CTkLabel(c_dirs, text="Pasta de Logs:").grid(row=5, column=0, padx=12, pady=(5, 10), sticky="w")
        self.entry_cfg_logs = ctk.CTkEntry(c_dirs, placeholder_text="Pasta padrão para logs (opcional)...")
        if self.settings.logs_dir:
            self.entry_cfg_logs.insert(0, self.settings.logs_dir)
        self.entry_cfg_logs.grid(row=5, column=1, padx=6, pady=(5, 10), sticky="ew")
        ctk.CTkButton(
            c_dirs,
            text="Procurar...",
            width=80,
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._browse_dir(self.entry_cfg_logs),
        ).grid(row=5, column=2, padx=12, pady=(5, 10))

        # -----------------------------------------------------------------
        # CARD 6: Ações e Persistência
        # -----------------------------------------------------------------
        c_actions = ctk.CTkFrame(frame, corner_radius=8)
        c_actions.grid(row=7, column=0, padx=10, pady=(6, 18), sticky="ew")
        c_actions.grid_columnconfigure((0, 1, 2), weight=1)

        btn_save = ctk.CTkButton(
            c_actions,
            text="💾  Salvar Todas as Configurações",
            height=38,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("#1e8449", "#1e8449"),
            hover_color=("#196f3d", "#196f3d"),
            text_color="#ffffff",
            command=self._save_all_settings,
        )
        btn_save.grid(row=0, column=0, padx=10, pady=12, sticky="ew")

        btn_reset = ctk.CTkButton(
            c_actions,
            text="🔄  Restaurar Padrões de Fábrica",
            height=38,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("#c0392b", "#c0392b"),
            hover_color=("#962d22", "#962d22"),
            text_color="#ffffff",
            command=self._reset_defaults,
        )
        btn_reset.grid(row=0, column=1, padx=10, pady=12, sticky="ew")

        btn_folder = ctk.CTkButton(
            c_actions,
            text="📂  Abrir Pasta de Configurações",
            height=38,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            command=self._open_config_folder,
        )
        btn_folder.grid(row=0, column=2, padx=10, pady=12, sticky="ew")

        # -----------------------------------------------------------------
        # CARD 7: Sobre o Aplicativo & Apoie o Projeto (Buy Me a Coffee)
        # -----------------------------------------------------------------
        c_about = ctk.CTkFrame(frame, corner_radius=8)
        c_about.grid(row=8, column=0, padx=10, pady=(6, 20), sticky="ew")
        c_about.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            c_about,
            text="☕  Sobre & Apoio ao Desenvolvedor",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        lbl_about_info = ctk.CTkLabel(
            c_about,
            text=f"Media Optimizer v{__version__} • Desenvolvido por Paulo (murphases)\n"
                 "Licença: PolyForm Noncommercial 1.0.0 • Processamento 100% local, autônomo e seguro.\n"
                 "Se este software otimizou seu fluxo de trabalho e recuperou espaço em disco, considere pagar um café para apoiar o projeto!",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray70"),
            justify="left",
            anchor="w",
        )
        lbl_about_info.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")

        btn_bmc_settings = ctk.CTkButton(
            c_about,
            text="☕  Buy me a coffee",
            height=36,
            width=210,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#FFDD00",
            hover_color="#e6c700",
            text_color="#000000",
            command=self._open_buy_me_a_coffee,
        )
        btn_bmc_settings.grid(row=2, column=0, padx=12, pady=(0, 14), sticky="w")

    def _build_bottom_console(self) -> None:
        self.bottom_frame.grid_columnconfigure(0, weight=1)

        # Header with title, live status, and clean action button
        header_frame = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header_frame,
            text="📋 Logs de Execução da Tarefa",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.lbl_progress = ctk.CTkLabel(
            header_frame,
            text="Aguardando início...",
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray75"),
            anchor="e",
        )
        self.lbl_progress.grid(row=0, column=1, padx=(10, 10), sticky="e")

        btn_clear = ctk.CTkButton(
            header_frame,
            text="Limpar Logs",
            width=80,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray80", "#2c3e50"),
            hover_color=("gray70", "#3b536b"),
            text_color=("gray10", "#ffffff"),
            command=self._clear_logs,
        )
        btn_clear.grid(row=0, column=2, sticky="e")

        # Progress bar
        self.prog_bar = ctk.CTkProgressBar(self.bottom_frame, height=9)
        self.prog_bar.set(0.0)
        self.prog_bar.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")

        # Monospace Text Console
        self.console_text = ctk.CTkTextbox(
            self.bottom_frame,
            height=110,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
        )
        self.console_text.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="nsew")

    def _clear_logs(self) -> None:
        self.console_text.delete("1.0", "end")

    def _browse_input(self) -> None:
        path = filedialog.askdirectory(title="Selecione a Pasta de Origem")
        if path:
            self.entry_input.delete(0, "end")
            self.entry_input.insert(0, path)
            if hasattr(self, "entry_conv_input"):
                self.entry_conv_input.delete(0, "end")
                self.entry_conv_input.insert(0, path)
            if hasattr(self, "entry_opt_img_input") and not self.entry_opt_img_input.get().strip():
                self.entry_opt_img_input.delete(0, "end")
                self.entry_opt_img_input.insert(0, path)
            if hasattr(self, "entry_vid_input"):
                self.entry_vid_input.delete(0, "end")
                self.entry_vid_input.insert(0, path)

    def _browse_dir(self, entry: ctk.CTkEntry) -> None:
        path = filedialog.askdirectory(title="Selecione o Diretório")
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)
            if hasattr(self, "entry_vid_output") and entry == self.entry_vid_output:
                if hasattr(self, "entry_out_videos"):
                    self.entry_out_videos.delete(0, "end")
                    self.entry_out_videos.insert(0, path)
            elif hasattr(self, "entry_out_videos") and entry == self.entry_out_videos:
                if hasattr(self, "entry_vid_output"):
                    self.entry_vid_output.delete(0, "end")
                    self.entry_vid_output.insert(0, path)
            elif hasattr(self, "entry_vid_input") and entry == self.entry_vid_input:
                if hasattr(self, "entry_input"):
                    self.entry_input.delete(0, "end")
                    self.entry_input.insert(0, path)
            elif hasattr(self, "entry_conv_input") and entry == self.entry_conv_input:
                if hasattr(self, "entry_input") and not self.entry_input.get().strip():
                    self.entry_input.delete(0, "end")
                    self.entry_input.insert(0, path)
            elif hasattr(self, "entry_conv_output") and entry == self.entry_conv_output:
                if hasattr(self, "entry_opt_img_input") and not self.entry_opt_img_input.get().strip():
                    self.entry_opt_img_input.delete(0, "end")
                    self.entry_opt_img_input.insert(0, path)
            elif hasattr(self, "entry_opt_img_output") and entry == self.entry_opt_img_output:
                if hasattr(self, "entry_out_images"):
                    self.entry_out_images.delete(0, "end")
                    self.entry_out_images.insert(0, path)
            elif hasattr(self, "entry_out_images") and entry == self.entry_out_images:
                if hasattr(self, "entry_opt_img_output"):
                    self.entry_opt_img_output.delete(0, "end")
                    self.entry_opt_img_output.insert(0, path)

    def _change_theme(self, new_theme: str) -> None:
        ctk.set_appearance_mode(new_theme)
        self.settings.theme = new_theme
        self.cfg_mgr.save(self.settings)
        if hasattr(self, "active_tab"):
            self._select_tab(self.active_tab)

    def _open_config_folder(self) -> None:
        cfg_dir = self.cfg_mgr.config_file.parent
        cfg_dir.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(cfg_dir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(cfg_dir)])
            else:
                subprocess.Popen(["xdg-open", str(cfg_dir)])
        except Exception as exc:
            self.logger.warning(f"Não foi possível abrir pasta de configurações: {exc}")

    def _open_buy_me_a_coffee(self) -> None:
        url = "https://buymeacoffee.com/murphases"
        self.logger.info(f"☕ Abrindo Buy Me a Coffee: {url}")
        try:
            webbrowser.open(url)
        except Exception as exc:
            self.logger.warning(f"Não foi possível abrir o navegador: {exc}")

    def _save_all_settings(self) -> None:
        try:
            # 1. Appearance
            if hasattr(self, "opt_theme"):
                self.settings.theme = self.opt_theme.get()
            if hasattr(self, "opt_accent"):
                self.settings.accent_color = self.opt_accent.get()
            self.settings.language = "pt_BR"

            # 2. Safety & Telemetry
            if hasattr(self, "slider_mem_limit"):
                self.settings.memory_threshold_percent = float(self.slider_mem_limit.get())
            if hasattr(self, "sw_cfg_skip_existing"):
                self.settings.skip_existing = bool(self.sw_cfg_skip_existing.get())
            if hasattr(self, "sw_cfg_dry_run"):
                self.settings.dry_run = bool(self.sw_cfg_dry_run.get())

            # 3. Photos
            if hasattr(self, "opt_cfg_conv_format"):
                self.settings.convert_target_format = self.opt_cfg_conv_format.get()
            if hasattr(self, "slider_cfg_conv_qual"):
                self.settings.convert_quality = int(self.slider_cfg_conv_qual.get())
            if hasattr(self, "sw_cfg_raw"):
                self.settings.convert_raw_enabled = bool(self.sw_cfg_raw.get())
            if hasattr(self, "slider_cfg_opt_dim"):
                self.settings.opt_image_max_dim = int(self.slider_cfg_opt_dim.get())
            if hasattr(self, "slider_cfg_opt_qual"):
                self.settings.opt_image_quality = int(self.slider_cfg_opt_qual.get())
            if hasattr(self, "sw_cfg_opt_tables"):
                self.settings.opt_image_optimize_tables = bool(self.sw_cfg_opt_tables.get())
            if hasattr(self, "sw_cfg_opt_prog"):
                self.settings.opt_image_progressive = bool(self.sw_cfg_opt_prog.get())
            if hasattr(self, "slider_cfg_img_workers"):
                self.settings.opt_image_workers = int(self.slider_cfg_img_workers.get())
                self.settings.convert_workers = self.settings.opt_image_workers

            # 4. Videos
            if hasattr(self, "opt_cfg_vid_format"):
                self.settings.opt_video_format = self.opt_cfg_vid_format.get().lower()
            if hasattr(self, "opt_cfg_vid_codec"):
                self.settings.opt_video_codec = self.opt_cfg_vid_codec.get()
            if hasattr(self, "slider_cfg_vid_dim"):
                self.settings.opt_video_max_dim = int(self.slider_cfg_vid_dim.get())
            if hasattr(self, "slider_cfg_vid_fps"):
                self.settings.opt_video_max_fps = int(self.slider_cfg_vid_fps.get())
            if hasattr(self, "slider_cfg_vid_crf"):
                self.settings.opt_video_crf = int(self.slider_cfg_vid_crf.get())
            if hasattr(self, "opt_cfg_vid_audio"):
                self.settings.opt_video_audio_bitrate = self.opt_cfg_vid_audio.get()
            if hasattr(self, "slider_cfg_vid_workers"):
                self.settings.opt_video_workers = int(self.slider_cfg_vid_workers.get())

            # 5. Directories
            if hasattr(self, "entry_cfg_input") and self.entry_cfg_input.get().strip():
                self.settings.input_dir = self.entry_cfg_input.get().strip()
            if hasattr(self, "entry_cfg_conv") and self.entry_cfg_conv.get().strip():
                self.settings.converted_dir = self.entry_cfg_conv.get().strip()
            if hasattr(self, "entry_cfg_opt_img") and self.entry_cfg_opt_img.get().strip():
                self.settings.optimized_images_dir = self.entry_cfg_opt_img.get().strip()
            if hasattr(self, "entry_cfg_opt_vid") and self.entry_cfg_opt_vid.get().strip():
                self.settings.optimized_videos_dir = self.entry_cfg_opt_vid.get().strip()
            if hasattr(self, "entry_cfg_logs") and self.entry_cfg_logs.get().strip():
                self.settings.logs_dir = self.entry_cfg_logs.get().strip()

            # Save to disk
            self.cfg_mgr.save(self.settings)
            self.orchestrator.settings = self.settings

            # Sync across all UI components
            self._update_all_ui_from_settings()

            messagebox.showinfo(
                "Configurações Salvas",
                "Todas as preferências foram salvas com sucesso no arquivo de configuração!"
            )
            self.logger.info("💾 Configurações salvas e aplicadas em todas as abas.")
        except Exception as exc:
            messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar as configurações:\n{exc}")

    def _reset_defaults(self) -> None:
        if messagebox.askyesno("Restaurar Padrões", "Deseja realmente restaurar todas as configurações para os padrões de fábrica?"):
            self.settings = self.cfg_mgr.reset_defaults()
            self._update_all_ui_from_settings()
            messagebox.showinfo("Sucesso", "Todas as configurações foram restauradas com sucesso.")
            self.logger.info("🔄 Configurações restauradas para os padrões originais.")

    def _update_all_ui_from_settings(self) -> None:
        """Updates all UI components and slider badges from current self.settings."""
        if hasattr(self, "entry_input"):
            self.entry_input.delete(0, "end")
            if self.settings.input_dir:
                self.entry_input.insert(0, self.settings.input_dir)
        if hasattr(self, "entry_conv_input"):
            self.entry_conv_input.delete(0, "end")
            if self.settings.input_dir:
                self.entry_conv_input.insert(0, self.settings.input_dir)
        if hasattr(self, "entry_conv_output"):
            self.entry_conv_output.delete(0, "end")
            if self.settings.converted_dir:
                self.entry_conv_output.insert(0, self.settings.converted_dir)
        if hasattr(self, "entry_opt_img_input"):
            self.entry_opt_img_input.delete(0, "end")
            opt_in = self.settings.converted_dir or self.settings.input_dir
            if opt_in:
                self.entry_opt_img_input.insert(0, opt_in)
        if hasattr(self, "entry_opt_img_output"):
            self.entry_opt_img_output.delete(0, "end")
            if self.settings.optimized_images_dir:
                self.entry_opt_img_output.insert(0, self.settings.optimized_images_dir)
        if hasattr(self, "entry_vid_input"):
            self.entry_vid_input.delete(0, "end")
            if self.settings.input_dir:
                self.entry_vid_input.insert(0, self.settings.input_dir)
        if hasattr(self, "entry_out_images"):
            self.entry_out_images.delete(0, "end")
            if self.settings.optimized_images_dir:
                self.entry_out_images.insert(0, self.settings.optimized_images_dir)
        if hasattr(self, "entry_out_videos"):
            self.entry_out_videos.delete(0, "end")
            if self.settings.optimized_videos_dir:
                self.entry_out_videos.insert(0, self.settings.optimized_videos_dir)
        if hasattr(self, "entry_vid_output"):
            self.entry_vid_output.delete(0, "end")
            if self.settings.optimized_videos_dir:
                self.entry_vid_output.insert(0, self.settings.optimized_videos_dir)

        if hasattr(self, "chk_dry_run"):
            if self.settings.dry_run:
                self.chk_dry_run.select()
            else:
                self.chk_dry_run.deselect()

        if hasattr(self, "chk_skip_existing"):
            if self.settings.skip_existing:
                self.chk_skip_existing.select()
            else:
                self.chk_skip_existing.deselect()

        if hasattr(self, "slider_conv_qual"):
            self.slider_conv_qual.set(self.settings.convert_quality)
        if hasattr(self, "lbl_conv_qual_val"):
            self.lbl_conv_qual_val.configure(text=f"{self.settings.convert_quality}%")

        if hasattr(self, "slider_conv_workers"):
            self.slider_conv_workers.set(self.settings.convert_workers)
        if hasattr(self, "lbl_conv_workers_val"):
            self.lbl_conv_workers_val.configure(text=f"{self.settings.convert_workers} threads")

        if hasattr(self, "slider_opt_dim"):
            self.slider_opt_dim.set(self.settings.opt_image_max_dim)
        if hasattr(self, "lbl_opt_dim_val"):
            self.lbl_opt_dim_val.configure(text=f"{self.settings.opt_image_max_dim} px")

        if hasattr(self, "slider_opt_qual"):
            self.slider_opt_qual.set(self.settings.opt_image_quality)
        if hasattr(self, "lbl_opt_qual_val"):
            self.lbl_opt_qual_val.configure(text=f"{self.settings.opt_image_quality}%")

        if hasattr(self, "slider_vid_dim"):
            self.slider_vid_dim.set(self.settings.opt_video_max_dim)
        if hasattr(self, "lbl_vid_dim_val"):
            self.lbl_vid_dim_val.configure(text=f"{self.settings.opt_video_max_dim} px")

        if hasattr(self, "slider_vid_fps"):
            self.slider_vid_fps.set(self.settings.opt_video_max_fps)
        if hasattr(self, "lbl_vid_fps_val"):
            self.lbl_vid_fps_val.configure(text=f"{self.settings.opt_video_max_fps} fps")

        if hasattr(self, "opt_vid_format"):
            self.opt_vid_format.set(self.settings.opt_video_format)

        if hasattr(self, "opt_vid_codec"):
            self.opt_vid_codec.set(self.settings.opt_video_codec)

        if hasattr(self, "slider_vid_crf"):
            self.slider_vid_crf.set(self.settings.opt_video_crf)
        if hasattr(self, "lbl_vid_crf_val"):
            self.lbl_vid_crf_val.configure(text=self._format_crf_label(self.settings.opt_video_crf))

        if hasattr(self, "slider_vid_workers"):
            self.slider_vid_workers.set(self.settings.opt_video_workers)
        if hasattr(self, "lbl_vid_workers_val"):
            self.lbl_vid_workers_val.configure(text=f"{self.settings.opt_video_workers} threads")

        # Sync tab_settings specific widgets
        if hasattr(self, "opt_theme"):
            self.opt_theme.set(self.settings.theme)
        if hasattr(self, "opt_accent"):
            self.opt_accent.set(self.settings.accent_color)
        if hasattr(self, "slider_mem_limit"):
            self.slider_mem_limit.set(self.settings.memory_threshold_percent)
        if hasattr(self, "lbl_mem_limit_val"):
            self.lbl_mem_limit_val.configure(text=f"{int(self.settings.memory_threshold_percent)}%")
        if hasattr(self, "sw_cfg_skip_existing"):
            if self.settings.skip_existing:
                self.sw_cfg_skip_existing.select()
            else:
                self.sw_cfg_skip_existing.deselect()
        if hasattr(self, "sw_cfg_dry_run"):
            if self.settings.dry_run:
                self.sw_cfg_dry_run.select()
            else:
                self.sw_cfg_dry_run.deselect()

        if hasattr(self, "opt_cfg_conv_format"):
            self.opt_cfg_conv_format.set(self.settings.convert_target_format)
        if hasattr(self, "slider_cfg_conv_qual"):
            self.slider_cfg_conv_qual.set(self.settings.convert_quality)
        if hasattr(self, "lbl_cfg_conv_qual_val"):
            self.lbl_cfg_conv_qual_val.configure(text=f"{self.settings.convert_quality}%")
        if hasattr(self, "sw_cfg_raw"):
            if self.settings.convert_raw_enabled:
                self.sw_cfg_raw.select()
            else:
                self.sw_cfg_raw.deselect()
        if hasattr(self, "slider_cfg_opt_dim"):
            self.slider_cfg_opt_dim.set(self.settings.opt_image_max_dim)
        if hasattr(self, "lbl_cfg_opt_dim_val"):
            self.lbl_cfg_opt_dim_val.configure(text=f"{self.settings.opt_image_max_dim} px")
        if hasattr(self, "slider_cfg_opt_qual"):
            self.slider_cfg_opt_qual.set(self.settings.opt_image_quality)
        if hasattr(self, "lbl_cfg_opt_qual_val"):
            self.lbl_cfg_opt_qual_val.configure(text=f"{self.settings.opt_image_quality}%")
        if hasattr(self, "sw_cfg_opt_tables"):
            if self.settings.opt_image_optimize_tables:
                self.sw_cfg_opt_tables.select()
            else:
                self.sw_cfg_opt_tables.deselect()
        if hasattr(self, "sw_cfg_opt_prog"):
            if self.settings.opt_image_progressive:
                self.sw_cfg_opt_prog.select()
            else:
                self.sw_cfg_opt_prog.deselect()
        if hasattr(self, "slider_cfg_img_workers"):
            self.slider_cfg_img_workers.set(self.settings.opt_image_workers)
        if hasattr(self, "lbl_cfg_img_workers_val"):
            self.lbl_cfg_img_workers_val.configure(text=f"{self.settings.opt_image_workers} threads")

        if hasattr(self, "opt_cfg_vid_format"):
            self.opt_cfg_vid_format.set(self.settings.opt_video_format)
        if hasattr(self, "opt_cfg_vid_codec"):
            self.opt_cfg_vid_codec.set(self.settings.opt_video_codec)
        if hasattr(self, "slider_cfg_vid_dim"):
            self.slider_cfg_vid_dim.set(self.settings.opt_video_max_dim)
        if hasattr(self, "lbl_cfg_vid_dim_val"):
            self.lbl_cfg_vid_dim_val.configure(text=f"{self.settings.opt_video_max_dim} px")
        if hasattr(self, "slider_cfg_vid_fps"):
            self.slider_cfg_vid_fps.set(self.settings.opt_video_max_fps)
        if hasattr(self, "lbl_cfg_vid_fps_val"):
            self.lbl_cfg_vid_fps_val.configure(text=f"{self.settings.opt_video_max_fps} fps")
        if hasattr(self, "slider_cfg_vid_crf"):
            self.slider_cfg_vid_crf.set(self.settings.opt_video_crf)
        if hasattr(self, "lbl_cfg_vid_crf_val"):
            self.lbl_cfg_vid_crf_val.configure(text=self._format_crf_label(self.settings.opt_video_crf))
        if hasattr(self, "opt_cfg_vid_audio"):
            self.opt_cfg_vid_audio.set(self.settings.opt_video_audio_bitrate)
        if hasattr(self, "slider_cfg_vid_workers"):
            self.slider_cfg_vid_workers.set(self.settings.opt_video_workers)
        if hasattr(self, "lbl_cfg_vid_workers_val"):
            self.lbl_cfg_vid_workers_val.configure(text=f"{self.settings.opt_video_workers} threads")

        if hasattr(self, "entry_cfg_input"):
            self.entry_cfg_input.delete(0, "end")
            if self.settings.input_dir:
                self.entry_cfg_input.insert(0, self.settings.input_dir)
        if hasattr(self, "entry_cfg_conv"):
            self.entry_cfg_conv.delete(0, "end")
            if self.settings.converted_dir:
                self.entry_cfg_conv.insert(0, self.settings.converted_dir)
        if hasattr(self, "entry_cfg_opt_img"):
            self.entry_cfg_opt_img.delete(0, "end")
            if self.settings.optimized_images_dir:
                self.entry_cfg_opt_img.insert(0, self.settings.optimized_images_dir)
        if hasattr(self, "entry_cfg_opt_vid"):
            self.entry_cfg_opt_vid.delete(0, "end")
            if self.settings.optimized_videos_dir:
                self.entry_cfg_opt_vid.insert(0, self.settings.optimized_videos_dir)
        if hasattr(self, "entry_cfg_logs"):
            self.entry_cfg_logs.delete(0, "end")
            if self.settings.logs_dir:
                self.entry_cfg_logs.insert(0, self.settings.logs_dir)

        self.orchestrator.settings = self.settings

    def _sync_settings_from_ui(self) -> None:
        self.settings.input_dir = self.entry_input.get().strip()
        if hasattr(self, "entry_conv_input") and self.entry_conv_input.get().strip():
            self.settings.input_dir = self.entry_conv_input.get().strip()
            self.entry_input.delete(0, "end")
            self.entry_input.insert(0, self.settings.input_dir)
        if hasattr(self, "entry_conv_output") and self.entry_conv_output.get().strip():
            self.settings.converted_dir = self.entry_conv_output.get().strip()

        if hasattr(self, "entry_opt_img_output") and self.entry_opt_img_output.get().strip():
            self.settings.optimized_images_dir = self.entry_opt_img_output.get().strip()
            self.entry_out_images.delete(0, "end")
            self.entry_out_images.insert(0, self.settings.optimized_images_dir)

        if hasattr(self, "entry_vid_input") and self.entry_vid_input.get().strip():
            self.settings.input_dir = self.entry_vid_input.get().strip()
            self.entry_input.delete(0, "end")
            self.entry_input.insert(0, self.settings.input_dir)

        self.settings.optimized_images_dir = self.entry_out_images.get().strip()
        self.settings.optimized_videos_dir = self.entry_out_videos.get().strip()
        if hasattr(self, "entry_vid_output") and self.entry_vid_output.get().strip():
            self.settings.optimized_videos_dir = self.entry_vid_output.get().strip()
            self.entry_out_videos.delete(0, "end")
            self.entry_out_videos.insert(0, self.settings.optimized_videos_dir)

        self.settings.dry_run = bool(self.chk_dry_run.get())
        self.settings.skip_existing = bool(self.chk_skip_existing.get())
        self.settings.convert_quality = int(self.slider_conv_qual.get())
        self.settings.convert_workers = int(self.slider_conv_workers.get())
        self.settings.opt_image_max_dim = int(self.slider_opt_dim.get())
        self.settings.opt_image_quality = int(self.slider_opt_qual.get())
        self.settings.opt_video_max_dim = int(self.slider_vid_dim.get())
        self.settings.opt_video_max_fps = int(self.slider_vid_fps.get())
        if hasattr(self, "opt_vid_format"):
            self.settings.opt_video_format = self.opt_vid_format.get().lower()
        if hasattr(self, "opt_vid_codec"):
            self.settings.opt_video_codec = self.opt_vid_codec.get()
        if hasattr(self, "slider_vid_crf"):
            self.settings.opt_video_crf = int(self.slider_vid_crf.get())
        if hasattr(self, "slider_vid_workers"):
            self.settings.opt_video_workers = int(self.slider_vid_workers.get())

        if hasattr(self, "slider_mem_limit"):
            self.settings.memory_threshold_percent = float(self.slider_mem_limit.get())
        self.cfg_mgr.save(self.settings)
        self.orchestrator.settings = self.settings

    def _start_pipeline(self) -> None:
        self._sync_settings_from_ui()
        if not Path(self.settings.input_dir).exists():
            messagebox.showerror("Erro", f"Pasta de origem inexistente:\n{self.settings.input_dir}")
            return

        if not FFmpegResolver.get_ffmpeg():
            self.logger.info("⚙️ FFmpeg não encontrado. Tentando baixar automaticamente para otimização de vídeos...")
            FFmpegResolver.ensure_binaries()

        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="⏸️ Pausar")
        self.btn_cancel.configure(state="normal")
        self.prog_bar.set(0.0)

        def run():
            self.logger.info("🚀 Iniciando Pipeline Completo...")
            summary = self.orchestrator.run_full_pipeline(
                on_stage_start=lambda s: self.logger.info(f"▶️ Etapa: {s}"),
                progress_cb=self._on_progress,
            )
            self._on_pipeline_done(summary)

        self.worker_thread = threading.Thread(target=run, daemon=True)
        self.worker_thread.start()

    def _start_single_stage(self, stage_idx: int) -> None:
        self._sync_settings_from_ui()

        stage_in_dir = self.settings.input_dir
        stage_out_dir = ""

        if stage_idx == 1:
            stage_in_dir = self.entry_conv_input.get().strip() if hasattr(self, "entry_conv_input") and self.entry_conv_input.get().strip() else self.settings.input_dir
            stage_out_dir = self.entry_conv_output.get().strip() if hasattr(self, "entry_conv_output") and self.entry_conv_output.get().strip() else self.settings.converted_dir
            if not stage_in_dir or not Path(stage_in_dir).exists():
                messagebox.showerror("Erro", f"Pasta de origem inexistente:\n{stage_in_dir}")
                return
            if not stage_out_dir:
                messagebox.showerror("Erro", "Por favor, selecione a pasta de saída para as fotos convertidas.")
                return
            self.settings.input_dir = stage_in_dir
            self.settings.converted_dir = stage_out_dir
        elif stage_idx == 2:
            stage_in_dir = self.entry_opt_img_input.get().strip() if hasattr(self, "entry_opt_img_input") and self.entry_opt_img_input.get().strip() else (self.settings.converted_dir or self.settings.input_dir)
            stage_out_dir = self.entry_opt_img_output.get().strip() if hasattr(self, "entry_opt_img_output") and self.entry_opt_img_output.get().strip() else self.settings.optimized_images_dir
            if not stage_in_dir or not Path(stage_in_dir).exists():
                messagebox.showerror("Erro", f"Pasta de origem inexistente:\n{stage_in_dir}")
                return
            if not stage_out_dir:
                messagebox.showerror("Erro", "Por favor, selecione a pasta de saída para as fotos otimizadas.")
                return
            self.settings.optimized_images_dir = stage_out_dir
        elif stage_idx == 3:
            stage_in_dir = self.entry_vid_input.get().strip() if hasattr(self, "entry_vid_input") and self.entry_vid_input.get().strip() else self.settings.input_dir
            stage_out_dir = self.entry_vid_output.get().strip() if hasattr(self, "entry_vid_output") and self.entry_vid_output.get().strip() else self.settings.optimized_videos_dir
            if not stage_in_dir or not Path(stage_in_dir).exists():
                messagebox.showerror("Erro", f"Pasta de origem inexistente:\n{stage_in_dir}")
                return
            if not stage_out_dir:
                messagebox.showerror("Erro", "Por favor, selecione a pasta de saída para os vídeos otimizados.")
                return
            self.settings.input_dir = stage_in_dir
            self.settings.optimized_videos_dir = stage_out_dir

            if not FFmpegResolver.get_ffmpeg():
                self.logger.info("⚙️ FFmpeg não encontrado. Baixando e configurando automaticamente...")
                if not FFmpegResolver.ensure_binaries():
                    messagebox.showerror(
                        "Erro FFmpeg",
                        "FFmpeg não foi encontrado e não pôde ser baixado automaticamente.\n"
                        "Verifique sua conexão ou instale o FFmpeg.",
                    )
                    return

            test_optimizer = VideoOptimizer(dry_run=True)
            videos = test_optimizer.find_videos(Path(stage_in_dir))
            if not videos:
                messagebox.showwarning(
                    "Nenhum Vídeo Encontrado",
                    f"Nenhum arquivo de vídeo suportado foi encontrado em:\n{stage_in_dir}",
                )
                return

        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="⏸️ Pausar")
        self.btn_cancel.configure(state="normal")

        def run():
            if stage_idx == 1:
                res = self.orchestrator.run_stage_1(
                    progress_cb=lambda c, t, n: self._on_progress("Conversão", c, t, n),
                    input_dir=Path(stage_in_dir),
                    output_dir=Path(stage_out_dir),
                )
                self.logger.info(f"Conversão finalizada: {res.converted} arquivos processados.")
            elif stage_idx == 2:
                res = self.orchestrator.run_stage_2(
                    progress_cb=lambda c, t, n: self._on_progress("Otimização Fotos", c, t, n),
                    input_dir=Path(stage_in_dir),
                    output_dir=Path(stage_out_dir),
                )
                self.logger.info(f"Otimização finalizada: economizou {format_bytes(res.saved_bytes)} ({res.savings_percent}%).")
            elif stage_idx == 3:
                res = self.orchestrator.run_stage_3(
                    progress_cb=lambda c, t, n: self._on_progress("Otimização Vídeos", c, t, n),
                    input_dir=Path(stage_in_dir),
                    output_dir=Path(stage_out_dir),
                )
                self.logger.info(f"Vídeos finalizados: economizou {format_bytes(res.saved_bytes)} ({res.savings_percent}%).")
                if res.errors > 0:
                    self.logger.warning(f"⚠️ {res.errors} vídeo(s) apresentaram falha:")
                    for err in res.error_details[:5]:
                        self.logger.warning(f"  • {Path(err['file']).name}: {err['error']}")
            self._reset_action_buttons()

        threading.Thread(target=run, daemon=True).start()

    def _toggle_pause(self) -> None:
        if self.orchestrator._is_paused.is_set():
            self.orchestrator.pause()
            self.btn_pause.configure(text="▶️ Retomar")
            self.logger.info("⏸️ Processamento pausado pelo usuário.")
        else:
            self.orchestrator.resume()
            self.btn_pause.configure(text="⏸️ Pausar")
            self.logger.info("▶️ Processamento retomado.")

    def _cancel_pipeline(self) -> None:
        if messagebox.askyesno("Cancelar", "Deseja realmente cancelar o processamento?"):
            self.orchestrator.cancel()
            self.logger.warning("⏹️ Cancelamento solicitado pelo usuário...")

    def _on_progress(self, stage: str, current: int, total: int, filename: str) -> None:
        pct = (current / total) if total > 0 else 0.0
        self.root.after(0, lambda: self._update_progress_ui(stage, current, total, pct, filename))

    def _update_progress_ui(self, stage: str, current: int, total: int, pct: float, filename: str) -> None:
        self.prog_bar.set(pct)
        self.lbl_progress.configure(
            text=f"[{stage}] {current}/{total} ({pct*100:.1f}%) — {filename[:40]}"
        )

    def _on_pipeline_done(self, summary: PipelineSummary) -> None:
        def finish():
            self._reset_action_buttons()
            if summary.cancelled:
                self.lbl_summary.configure(text="Processamento cancelado.")
                self.logger.warning("Processamento interrompido.")
            else:
                msg = (
                    f"Concluído em {format_time(summary.total_elapsed_seconds)}! "
                    f"Economia total: {format_bytes(summary.total_saved_bytes)} ({summary.total_savings_percent}%)."
                )
                self.lbl_summary.configure(text=msg)
                self.logger.info(f"🎉 {msg}")
                messagebox.showinfo("Sucesso", msg)

        self.root.after(0, finish)

    def _reset_action_buttons(self) -> None:
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled", text="⏸️ Pausar")
        self.btn_cancel.configure(state="disabled")

    def _start_telemetry_loop(self) -> None:
        def update():
            telemetry = self.hw_monitor.get_telemetry()

            # CPU
            cpu_pct = max(0.0, min(100.0, telemetry.cpu_percent))
            self.lbl_cpu_model.configure(text=f"{telemetry.cpu_vendor} ({telemetry.cpu_count} threads)")
            self.lbl_cpu_usage.configure(text=f"{cpu_pct:.0f}% em uso")
            self.prog_cpu.set(cpu_pct / 100.0)

            # RAM
            ram_pct = max(0.0, min(100.0, telemetry.ram_percent))
            self.lbl_ram_text.configure(
                text=f"{format_bytes(telemetry.ram_used_bytes)} / {format_bytes(telemetry.ram_total_bytes)}"
            )
            self.lbl_ram_usage.configure(text=f"{ram_pct:.0f}% em uso")
            self.prog_ram.set(ram_pct / 100.0)

            # GPU
            if telemetry.gpu_available:
                gpu_load = max(0.0, min(100.0, telemetry.gpu_load_percent))
                gpu_name_clean = telemetry.gpu_name.replace("NVIDIA GeForce ", "").replace(" Laptop GPU", "")
                self.lbl_gpu_model.configure(text=gpu_name_clean)
                self.lbl_gpu_encoder.configure(
                    text=f"Codec: {telemetry.recommended_encoder} ({gpu_load:.0f}%)"
                )
                self.prog_gpu.set(gpu_load / 100.0)
                if telemetry.gpu_temp_c > 0:
                    self.lbl_gpu_extra.configure(text=f"Temp: {telemetry.gpu_temp_c:.0f}°C")
                else:
                    self.lbl_gpu_extra.configure(text="")
            else:
                self.lbl_gpu_model.configure(text="Integrada / CPU")
                self.lbl_gpu_encoder.configure(text="Codec: libx264")
                self.prog_gpu.set(0.0)
                self.lbl_gpu_extra.configure(text="")

            # Protection / Throttling
            if telemetry.is_throttling:
                self.lbl_throttle_badge.configure(
                    text="⚠️ Throttling Ativo!",
                    text_color="#e74c3c",
                )
                self.lbl_throttle_desc.configure(
                    text="Uso de RAM alto. Reduzindo carga para proteger o sistema."
                )
            else:
                self.lbl_throttle_badge.configure(
                    text="🛡️ Proteção: Normal",
                    text_color="#2ecc71",
                )
                self.lbl_throttle_desc.configure(
                    text="Sistema estável e monitorado."
                )

            self.root.after(1500, update)

        self.root.after(1000, update)

    def _start_log_consumer_loop(self) -> None:
        def drain():
            while not self.log_queue.empty():
                try:
                    _, text = self.log_queue.get_nowait()
                    self.console_text.insert("end", text + "\n")
                    self.console_text.see("end")
                except queue.Empty:
                    break
            self.root.after(250, drain)

        self.root.after(250, drain)

    def run(self) -> None:
        """Starts main application event loop."""
        self.root.mainloop()


def launch_gui() -> None:
    """Entry point for GUI launch."""
    app = MediaOptimizerApp()
    app.run()


if __name__ == "__main__":
    launch_gui()
