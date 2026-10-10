#!/usr/bin/env python3
"""Punto de entrada operativo del sondeo autónomo del original.

Solo delega en ``probe_harness.cli.main``; no contiene reglas de sondeo.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from probe_harness.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
