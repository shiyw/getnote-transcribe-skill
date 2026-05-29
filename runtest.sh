#!/usr/bin/env bash
set -euo pipefail

export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.uv-cache}"

uv run python -m unittest test_getnote_workflow.py
uv run python -m py_compile skills/getnote-transcribe/scripts/getnote_url_workflow.py test_getnote_workflow.py
