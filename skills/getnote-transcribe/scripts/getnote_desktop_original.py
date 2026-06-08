#!/usr/bin/env python3
"""Compatibility wrapper for getnote-note-original."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


TARGET = Path(__file__).resolve().parents[2] / "getnote-note-original" / "scripts" / "getnote_desktop_original.py"


def _load_target():
    spec = importlib.util.spec_from_file_location("getnote_note_original_impl", TARGET)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load getnote-note-original script at {TARGET}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_TARGET = _load_target()
for _name in dir(_TARGET):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_TARGET, _name)


if __name__ == "__main__":
    raise SystemExit(_TARGET.main())
