#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Menu Principal e Orquestrador dos Scripts de Mídia (Google Fotos Takeout)
Wrapper retrocompatível que aciona o CLI ou a GUI do media_optimizer.
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from media_optimizer.cli import main

if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main(sys.argv[1:]))
    else:
        # Default behavior: run full pipeline CLI
        sys.exit(main(["--mode", "all"]))
