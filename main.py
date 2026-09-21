#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for Media Optimizer.
Launches GUI if no arguments are passed, or CLI if arguments are provided.
"""

import sys
from pathlib import Path

# Add current directory to path if needed
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        from media_optimizer.cli import main
        sys.exit(main())
    else:
        from media_optimizer.gui import launch_gui
        launch_gui()
