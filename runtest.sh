#!/usr/bin/env bash
set -euo pipefail

export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.uv-cache}"

uv run python -m unittest test_getnote_workflow.py
uv run python -m py_compile \
  skills/_shared/getnote_common.py \
  skills/getnote-url-import/scripts/getnote_url_workflow.py \
  skills/getnote-note-original/scripts/getnote_desktop_original.py \
  skills/getnote-local-media/scripts/getnote_local_media_workflow.py \
  skills/getnote-transcribe/scripts/getnote_url_workflow.py \
  skills/getnote-transcribe/scripts/getnote_desktop_original.py \
  test_getnote_workflow.py
