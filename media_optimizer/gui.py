"""
Modern, intuitive, and responsive GUI for Media Optimizer using CustomTkinter.
Features live hardware telemetry, modular tabs, customization, and non-blocking background workers.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

from media_optimizer.config import ConfigManager, OptimizerSettings
from media_optimizer.hardware import HardwareMonitor, SystemTelemetry, format_bytes, format_time
from media_optimizer.pipeline import PipelineOrchestrator, PipelineSummary


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
        self.root.title("Media Optimizer — Otimizador Profissional de Fotos e Vídeos")
        self.root.geometry("1100x750")
        self.root.minsize(950, 650)

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
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        # 1. Top Telemetry Bar
        self.telemetry_frame = ctk.CTkFrame(self.root, corner_radius=8, height=60)
        self.telemetry_frame.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="ew")
        self._build_telemetry_bar()

        # 2. Main Tab View
        self.tabview = ctk.CTkTabview(self.root, corner_radius=8)
        self.tabview.grid(row=1, column=0, padx=15, pady=5, sticky="nsew")

        self.tab_pipeline = self.tabview.add("🚀 Pipeline Completo")
        self.tab_convert = self.tabview.add("🖼️ Conversão de Fotos")
        self.tab_opt_images = self.tabview.add("🪄 Otimização de Fotos")
        self.tab_opt_videos = self.tabview.add("🎬 Otimização de Vídeos")
        self.tab_settings = self.tabview.add("⚙️ Configurações & Temas")

        self._build_tab_pipeline()
        self._build_tab_convert()
        self._build_tab_opt_images()
        self._build_tab_opt_videos()
        self._build_tab_settings()

        # 3. Bottom Console & Progress Bar
        self.bottom_frame = ctk.CTkFrame(self.root, corner_radius=8, height=180)
        self.bottom_frame.grid(row=2, column=0, padx=15, pady=(5, 10), sticky="ew")
        self._build_bottom_console()

    def _build_telemetry_bar(self) -> None:
        self.telemetry_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.lbl_cpu = ctk.CTkLabel(
            self.telemetry_frame,
            text="CPU: Carregando...",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_cpu.grid(row=0, column=0, padx=10, pady=8)

        self.lbl_ram = ctk.CTkLabel(
            self.telemetry_frame,
            text="RAM: Carregando...",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_ram.grid(row=0, column=1, padx=10, pady=8)

        self.lbl_gpu = ctk.CTkLabel(
            self.telemetry_frame,
            text="GPU: Carregando...",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_gpu.grid(row=0, column=2, padx=10, pady=8)

        self.lbl_throttle = ctk.CTkLabel(
            self.telemetry_frame,
            text="🛡️ Proteção: Normal",
            text_color="#2ecc71",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_throttle.grid(row=0, column=3, padx=10, pady=8)

    def _build_tab_pipeline(self) -> None:
        frame = self.tab_pipeline
        frame.grid_columnconfigure(1, weight=1)

        # Folder pickers
        ctk.CTkLabel(frame, text="Pasta de Origem:").grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self.entry_input = ctk.CTkEntry(frame)
        self.entry_input.insert(0, self.settings.input_dir)
        self.entry_input.grid(row=0, column=1, padx=5, pady=8, sticky="ew")
        ctk.CTkButton(frame, text="Procurar...", width=90, command=self._browse_input).grid(row=0, column=2, padx=10, pady=8)

        ctk.CTkLabel(frame, text="Saída Fotos Otimizadas:").grid(row=1, column=0, padx=10, pady=8, sticky="w")
        self.entry_out_images = ctk.CTkEntry(frame)
        self.entry_out_images.insert(0, self.settings.optimized_images_dir)
        self.entry_out_images.grid(row=1, column=1, padx=5, pady=8, sticky="ew")
        ctk.CTkButton(frame, text="Procurar...", width=90, command=lambda: self._browse_dir(self.entry_out_images)).grid(row=1, column=2, padx=10, pady=8)

        ctk.CTkLabel(frame, text="Saída Vídeos Otimizados:").grid(row=2, column=0, padx=10, pady=8, sticky="w")
        self.entry_out_videos = ctk.CTkEntry(frame)
        self.entry_out_videos.insert(0, self.settings.optimized_videos_dir)
        self.entry_out_videos.grid(row=2, column=1, padx=5, pady=8, sticky="ew")
        ctk.CTkButton(frame, text="Procurar...", width=90, command=lambda: self._browse_dir(self.entry_out_videos)).grid(row=2, column=2, padx=10, pady=8)

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
            fg_color="#2ecc71",
            hover_color="#27ae60",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_pipeline,
        )
        self.btn_start.pack(side="left", padx=10)

        self.btn_pause = ctk.CTkButton(
            btn_frame,
            text="⏸️ Pausar",
            fg_color="#f39c12",
            hover_color="#d68910",
            state="disabled",
            command=self._toggle_pause,
        )
        self.btn_pause.pack(side="left", padx=10)

        self.btn_cancel = ctk.CTkButton(
            btn_frame,
            text="⏹️ Cancelar",
            fg_color="#e74c3c",
            hover_color="#c0392b",
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

    def _build_tab_convert(self) -> None:
        frame = self.tab_convert
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="Qualidade Inicial do JPG:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.slider_conv_qual = ctk.CTkSlider(frame, from_=50, to=100, number_of_steps=50)
        self.slider_conv_qual.set(self.settings.convert_quality)
        self.slider_conv_qual.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(frame, text="Processos Paralelos (Workers):").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.slider_conv_workers = ctk.CTkSlider(frame, from_=1, to=32, number_of_steps=31)
        self.slider_conv_workers.set(self.settings.convert_workers)
        self.slider_conv_workers.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkButton(
            frame,
            text="▶️ Executar Apenas Conversão",
            command=lambda: self._start_single_stage(1),
        ).grid(row=2, column=0, columnspan=2, pady=20)

    def _build_tab_opt_images(self) -> None:
        frame = self.tab_opt_images
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="Dimensão Máxima (px):").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.slider_opt_dim = ctk.CTkSlider(frame, from_=800, to=3840, number_of_steps=38)
        self.slider_opt_dim.set(self.settings.opt_image_max_dim)
        self.slider_opt_dim.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(frame, text="Qualidade de Compressão (%):").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.slider_opt_qual = ctk.CTkSlider(frame, from_=50, to=95, number_of_steps=45)
        self.slider_opt_qual.set(self.settings.opt_image_quality)
        self.slider_opt_qual.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkButton(
            frame,
            text="▶️ Executar Apenas Otimização de Fotos",
            command=lambda: self._start_single_stage(2),
        ).grid(row=2, column=0, columnspan=2, pady=20)

    def _build_tab_opt_videos(self) -> None:
        frame = self.tab_opt_videos
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="Resolução Máxima Lado Maior (px):").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.slider_vid_dim = ctk.CTkSlider(frame, from_=720, to=3840, number_of_steps=31)
        self.slider_vid_dim.set(self.settings.opt_video_max_dim)
        self.slider_vid_dim.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(frame, text="Limite de FPS (mantém se menor):").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.slider_vid_fps = ctk.CTkSlider(frame, from_=24, to=60, number_of_steps=36)
        self.slider_vid_fps.set(self.settings.opt_video_max_fps)
        self.slider_vid_fps.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkButton(
            frame,
            text="▶️ Executar Apenas Otimização de Vídeos",
            command=lambda: self._start_single_stage(3),
        ).grid(row=2, column=0, columnspan=2, pady=20)

    def _build_tab_settings(self) -> None:
        frame = self.tab_settings
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="Aparência / Tema:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.opt_theme = ctk.CTkOptionMenu(
            frame,
            values=["Dark", "Light", "System"],
            command=self._change_theme,
        )
        self.opt_theme.set(self.settings.theme)
        self.opt_theme.grid(row=0, column=1, padx=10, pady=10, sticky="w")

        ctk.CTkLabel(frame, text="Limite de RAM p/ Auto-Throttling (%):").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.slider_mem_limit = ctk.CTkSlider(frame, from_=50, to=95, number_of_steps=45)
        self.slider_mem_limit.set(self.settings.memory_threshold_percent)
        self.slider_mem_limit.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkButton(
            frame,
            text="🔄 Restaurar Configurações Padrão",
            command=self._reset_defaults,
        ).grid(row=2, column=0, columnspan=2, pady=20)

    def _build_bottom_console(self) -> None:
        self.bottom_frame.grid_columnconfigure(0, weight=1)

        # Progress bar
        self.prog_bar = ctk.CTkProgressBar(self.bottom_frame)
        self.prog_bar.set(0.0)
        self.prog_bar.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="ew")

        self.lbl_progress = ctk.CTkLabel(
            self.bottom_frame,
            text="Aguardando início...",
            font=ctk.CTkFont(size=12),
        )
        self.lbl_progress.grid(row=1, column=0, padx=10, pady=(0, 4), sticky="w")

        # Text Console
        self.console_text = ctk.CTkTextbox(self.bottom_frame, height=95)
        self.console_text.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="nsew")

    def _browse_input(self) -> None:
        path = filedialog.askdirectory(title="Selecione a Pasta de Origem")
        if path:
            self.entry_input.delete(0, "end")
            self.entry_input.insert(0, path)

    def _browse_dir(self, entry: ctk.CTkEntry) -> None:
        path = filedialog.askdirectory(title="Selecione o Diretório")
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _change_theme(self, new_theme: str) -> None:
        ctk.set_appearance_mode(new_theme)
        self.settings.theme = new_theme
        self.cfg_mgr.save(self.settings)

    def _reset_defaults(self) -> None:
        if messagebox.askyesno("Restaurar", "Deseja restaurar as configurações padrão?"):
            self.settings = self.cfg_mgr.reset_defaults()
            messagebox.showinfo("Sucesso", "Configurações restauradas com sucesso.")

    def _sync_settings_from_ui(self) -> None:
        self.settings.input_dir = self.entry_input.get().strip()
        self.settings.optimized_images_dir = self.entry_out_images.get().strip()
        self.settings.optimized_videos_dir = self.entry_out_videos.get().strip()
        self.settings.dry_run = bool(self.chk_dry_run.get())
        self.settings.skip_existing = bool(self.chk_skip_existing.get())
        self.settings.convert_quality = int(self.slider_conv_qual.get())
        self.settings.convert_workers = int(self.slider_conv_workers.get())
        self.settings.opt_image_max_dim = int(self.slider_opt_dim.get())
        self.settings.opt_image_quality = int(self.slider_opt_qual.get())
        self.settings.opt_video_max_dim = int(self.slider_vid_dim.get())
        self.settings.opt_video_max_fps = int(self.slider_vid_fps.get())
        self.settings.memory_threshold_percent = float(self.slider_mem_limit.get())
        self.cfg_mgr.save(self.settings)
        self.orchestrator.settings = self.settings

    def _start_pipeline(self) -> None:
        self._sync_settings_from_ui()
        if not Path(self.settings.input_dir).exists():
            messagebox.showerror("Erro", "Pasta de origem inexistente.")
            return

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
        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="⏸️ Pausar")
        self.btn_cancel.configure(state="normal")

        def run():
            if stage_idx == 1:
                res = self.orchestrator.run_stage_1(
                    progress_cb=lambda c, t, n: self._on_progress("Conversão", c, t, n)
                )
                self.logger.info(f"Conversão finalizada: {res.converted} arquivos processados.")
            elif stage_idx == 2:
                res = self.orchestrator.run_stage_2(
                    progress_cb=lambda c, t, n: self._on_progress("Otimização Fotos", c, t, n)
                )
                self.logger.info(f"Otimização finalizada: economizou {format_bytes(res.saved_bytes)} ({res.savings_percent}%).")
            elif stage_idx == 3:
                res = self.orchestrator.run_stage_3(
                    progress_cb=lambda c, t, n: self._on_progress("Otimização Vídeos", c, t, n)
                )
                self.logger.info(f"Vídeos finalizados: economizou {format_bytes(res.saved_bytes)} ({res.savings_percent}%).")
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
            self.lbl_cpu.configure(text=f"CPU: {telemetry.cpu_percent:.1f}% ({telemetry.cpu_count}T)")
            self.lbl_ram.configure(
                text=f"RAM: {format_bytes(telemetry.ram_used_bytes)} / {format_bytes(telemetry.ram_total_bytes)} ({telemetry.ram_percent:.0f}%)"
            )
            if telemetry.gpu_available:
                self.lbl_gpu.configure(
                    text=f"GPU: {telemetry.gpu_load_percent:.0f}% | {telemetry.gpu_temp_c:.0f}°C | {format_bytes(telemetry.gpu_mem_used_bytes)}"
                )
            else:
                self.lbl_gpu.configure(text="GPU: N/A (CPU)")

            if telemetry.is_throttling:
                self.lbl_throttle.configure(text="⚠️ Throttling Ativo!", text_color="#e74c3c")
            else:
                self.lbl_throttle.configure(text="🛡️ Normal", text_color="#2ecc71")

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
