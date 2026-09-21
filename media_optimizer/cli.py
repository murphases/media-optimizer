"""
Command Line Interface (CLI) for Media Optimizer.
Provides terminal execution for servers, headless environments, and script automation.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from media_optimizer.config import ConfigManager, OptimizerSettings
from media_optimizer.hardware import HardwareMonitor, format_bytes, format_time
from media_optimizer.pipeline import PipelineOrchestrator


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="media-optimizer",
        description="Otimizador Profissional de Fotos e Vídeos (Zero Setup, Alta Performance)",
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        help="Diretório contendo os arquivos originais (fotos/vídeos).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Diretório raiz de saída.",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["all", "convert", "opt-images", "opt-videos"],
        default="all",
        help="Modo de execução: all (pipeline completo), convert (apenas conversão), opt-images (apenas otimizar imagens), opt-videos (apenas otimizar vídeos).",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=None,
        help="Número de threads/processos simultâneos.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula a execução sem gravar arquivos em disco.",
    )
    parser.add_argument(
        "--telemetry",
        action="store_true",
        help="Exibe dados de hardware e telemetria do sistema e sai.",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version="Media Optimizer v1.0.0",
    )
    return parser


def print_telemetry() -> None:
    """Prints system hardware telemetry to console."""
    monitor = HardwareMonitor()
    telemetry = monitor.get_telemetry()
    print("=" * 60)
    print(" 🛠️ TELEMETRIA DE HARDWARE DO SISTEMA")
    print("=" * 60)
    print(f" CPU:         {telemetry.cpu_name} ({telemetry.cpu_count} núcleos/threads)")
    print(f" Carga CPU:   {telemetry.cpu_percent:.1f}%")
    print(f" Memória RAM: {format_bytes(telemetry.ram_used_bytes)} / {format_bytes(telemetry.ram_total_bytes)} ({telemetry.ram_percent:.1f}%)")
    if telemetry.gpu_available:
        print(f" GPU:         {telemetry.gpu_name}")
        print(f" VRAM:        {format_bytes(telemetry.gpu_mem_used_bytes)} / {format_bytes(telemetry.gpu_mem_total_bytes)}")
        print(f" Temp GPU:    {telemetry.gpu_temp_c:.1f}°C")
    else:
        print(" GPU:         Nenhuma GPU dedicada detectada (Codificação via CPU).")
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.telemetry:
        print_telemetry()
        return 0

    cfg_mgr = ConfigManager()
    settings = cfg_mgr.load()

    if args.input:
        settings.input_dir = str(Path(args.input).resolve())
    if args.output:
        out_base = Path(args.output).resolve()
        settings.converted_dir = str(out_base / "Convertidos" / "JPG")
        settings.optimized_images_dir = str(out_base / "Otimizadas" / "JPG")
        settings.optimized_videos_dir = str(out_base / "Otimizadas" / "MOV")
        settings.logs_dir = str(out_base / "logs")

    if args.workers:
        settings.convert_workers = args.workers
        settings.opt_image_workers = args.workers
        settings.opt_video_workers = max(1, args.workers // 2)

    if args.dry_run:
        settings.dry_run = True

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("MediaOptimizerCLI")

    orchestrator = PipelineOrchestrator(settings=settings, logger=logger)

    def progress_printer(stage: str, curr: int, tot: int, name: str):
        pct = (curr / tot * 100) if tot > 0 else 0
        print(f"\r[{stage}] {curr}/{tot} ({pct:.1f}%) - {name[:30]}", end="", flush=True)

    print("=" * 60)
    print(" 🚀 INICIANDO MEDIA OPTIMIZER CLI")
    print(f" Origem:  {settings.input_dir}")
    print(f" Modo:    {args.mode}")
    print(f" Dry-Run: {settings.dry_run}")
    print("=" * 60)

    if args.mode == "convert":
        res = orchestrator.run_stage_1(
            progress_cb=lambda c, t, n: progress_printer("Conversão", c, t, n)
        )
        print(f"\n✅ Conversão concluída: {res.converted} convertidos, {res.skipped} ignorados, {res.errors} erros em {format_time(res.elapsed_seconds)}.")
    elif args.mode == "opt-images":
        res = orchestrator.run_stage_2(
            progress_cb=lambda c, t, n: progress_printer("Otimização Fotos", c, t, n)
        )
        print(f"\n✅ Otimização de imagens concluída: {res.optimized} otimizados, economizou {format_bytes(res.saved_bytes)} ({res.savings_percent}%).")
    elif args.mode == "opt-videos":
        res = orchestrator.run_stage_3(
            progress_cb=lambda c, t, n: progress_printer("Otimização Vídeos", c, t, n)
        )
        print(f"\n✅ Otimização de vídeos concluída: {res.optimized} otimizados, economizou {format_bytes(res.saved_bytes)} ({res.savings_percent}%).")
    else:  # all
        summary = orchestrator.run_full_pipeline(
            on_stage_start=lambda stage: print(f"\n▶️ Entrando na etapa: {stage}"),
            progress_cb=progress_printer,
        )
        print("\n" + "=" * 60)
        print(" 🎉 PIPELINE CONCLUÍDO COM SUCESSO!")
        print(f" Duração total:     {format_time(summary.total_elapsed_seconds)}")
        print(f" Espaço economizado: {format_bytes(summary.total_saved_bytes)} ({summary.total_savings_percent}%)")
        print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
