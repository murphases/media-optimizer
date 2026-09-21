#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 1: Conversor de Imagens para JPG (Wrapper Retrocompatível)
Delega o processamento para o motor modular media_optimizer.
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from media_optimizer.cli import main

if __name__ == "__main__":
    args = ["--mode", "convert"] + sys.argv[1:]
    sys.exit(main(args))
