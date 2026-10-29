#!/usr/bin/env python3
"""Backwards-compatible entry point for the CLI OS Simulator.

Historically this file contained the whole simulator. It now simply forwards
to the :mod:`ossim` package so that existing commands keep working::

    python3 ps-runner.py program.txt

New features (algorithm flags, JSON export, comparison mode, ...) are
available through the same command; run ``python3 ps-runner.py --help``.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ossim.cli import main  # noqa: E402  (import after sys.path tweak)

if __name__ == "__main__":
    raise SystemExit(main())
