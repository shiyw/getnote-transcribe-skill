#!/usr/bin/env python3
"""Export GetNote desktop original text/transcript for an existing note."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Mapping


# Prefer vendored module next to this script (skill-manager installs one skill dir
# at a time; monorepo skills/_shared is not part of the package).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from getnote_common import (  # noqa: E402
    DEFAULT_STORAGE_DIR,
    DEFAULT_WEB_BASE_URL,
    ensure_desktop_access_tokens,
    extract_jwts_from_bytes,
    fetch_original_with_tokens,
    jwt_exp,
    ms_to_timestamp,
    parse_original_content,
    request_original_note,
    sentence_list_from_original,
    transcript_markdown,
    unique_tokens,
)


def load_tokens(args: argparse.Namespace, environ: Mapping[str, str]) -> list[str]:
    """Load a usable PC access JWT; auto-refresh via LocalStorage refresh_token when expired."""
    return ensure_desktop_access_tokens(
        Path(args.desktop_storage_dir),
        environ=environ,
        allow_refresh=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export an existing GetNote desktop note original transcript by note_id."
    )
    parser.add_argument("note_id", help="GetNote note_id. Keep it as a string to avoid 64-bit integer precision loss.")
    parser.add_argument("--output", help="Write Markdown transcript to this path. Defaults to stdout.")
    parser.add_argument("--raw-json", help="Also write the raw /original JSON payload to this path.")
    parser.add_argument("--base-url", default=DEFAULT_WEB_BASE_URL)
    parser.add_argument("--desktop-storage-dir", default=str(DEFAULT_STORAGE_DIR))
    parser.add_argument("--timeout", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        tokens = load_tokens(args, os.environ)
        payload = fetch_original_with_tokens(args.base_url, str(args.note_id), tokens, args.timeout)
        markdown = transcript_markdown(payload)
        if args.raw_json:
            Path(args.raw_json).expanduser().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.output:
            Path(args.output).expanduser().write_text(markdown, encoding="utf-8")
        else:
            sys.stdout.write(markdown)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
