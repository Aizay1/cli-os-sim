#!/usr/bin/env python3
"""Launch the OS Simulator GUI without activating a virtual environment.

Works from a fresh clone::

    python3 ossim-ui.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ossim.ui import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
