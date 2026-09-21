#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Painel Inteligente de Conversão e Otimização de Mídia - Google Fotos Takeout
Ponto de entrada retrocompatível para iniciar a interface moderna.
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if __name__ == "__main__":
    from media_optimizer.gui import launch_gui
    launch_gui()
