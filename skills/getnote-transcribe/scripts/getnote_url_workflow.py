#!/usr/bin/env python3
"""Compatibility wrapper for getnote-url-import."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


TARGET = Path(__file__).resolve().parents[2] / "getnote-url-import" / "scripts" / "getnote_url_workflow.py"


def _load_target():
    spec = importlib.util.spec_from_file_location("getnote_url_import_impl", TARGET)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load getnote-url-import script at {TARGET}")
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
