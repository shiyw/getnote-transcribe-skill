#!/usr/bin/env python3
"""Refresh GetNote desktop PC access JWT from LocalStorage refresh_token.

Does not print token secrets by default. Use --export-env to write GETNOTE_WEB_TOKEN
for subsequent local-media / note-original workflow processes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Prefer vendored module next to this script (skill-manager installs one skill dir
# at a time; monorepo skills/_shared is not part of the package).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from getnote_common import (  # noqa: E402
    DEFAULT_STORAGE_DIR,
    ensure_desktop_access_tokens,
    jwt_exp,
    load_desktop_refresh_token,
    refresh_desktop_access_token,
    token_is_fresh,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh GetNote desktop access JWT using LocalStorage refresh_token."
    )
    parser.add_argument(
        "--desktop-storage-dir",
        default=str(DEFAULT_STORAGE_DIR),
        help="Path to iget-biji-desktop Local Storage/leveldb",
    )
    parser.add_argument(
        "--export-env",
        default="",
        help="Write `export GETNOTE_WEB_TOKEN=...` to this path (mode 0600).",
    )
    parser.add_argument(
        "--export-refresh",
        default="",
        help="If API rotates refresh_token, write the new value to this path (mode 0600).",
    )
    parser.add_argument(
        "--min-ttl-seconds",
        type=int,
        default=60,
        help="Skip refresh if an existing desktop/env access JWT still has this many seconds left.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Always call refresh API even if a fresh access JWT already exists.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable status JSON (no token values).",
    )
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Print the access JWT to stdout (dangerous; default off).",
    )
    return parser


def write_secret_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    storage = Path(args.desktop_storage_dir)

    if not args.force:
        try:
            existing = ensure_desktop_access_tokens(
                storage,
                environ=os.environ,
                min_ttl_seconds=args.min_ttl_seconds,
                allow_refresh=False,
            )
        except RuntimeError:
            existing = []
        if existing and token_is_fresh(existing[0], min_ttl_seconds=args.min_ttl_seconds):
            exp = jwt_exp(existing[0])
            left_min = round((exp - time.time()) / 60, 1) if exp else None
            status: dict[str, Any] = {
                "success": True,
                "refreshed": False,
                "source": "desktop_access_jwt",
                "exp": exp or None,
                "left_min": left_min,
            }
            if args.export_env:
                write_secret_file(Path(args.export_env), f"export GETNOTE_WEB_TOKEN={existing[0]}\n")
                status["export_env"] = str(Path(args.export_env))
            if args.json:
                print(json.dumps(status, ensure_ascii=False))
            else:
                print(f"ok refreshed=false left_min={left_min}")
            if args.print_token:
                print(existing[0])
            return 0

    # Always verify refresh_token is readable before calling API (clearer errors).
    _refresh_token, expire_at = load_desktop_refresh_token(storage)
    result = refresh_desktop_access_token(storage_dir=storage)
    access = result["access_token"]
    exp = int(result.get("exp") or jwt_exp(access) or 0)
    left_min = round((exp - time.time()) / 60, 1) if exp else None

    status = {
        "success": True,
        "refreshed": True,
        "source": "refresh_api",
        "exp": exp or None,
        "left_min": left_min,
        "refresh_token_expire_at": expire_at,
        "uid": result.get("uid"),
    }

    if args.export_env:
        write_secret_file(Path(args.export_env), f"export GETNOTE_WEB_TOKEN={access}\n")
        status["export_env"] = str(Path(args.export_env))
    if args.export_refresh and result.get("refresh_token"):
        write_secret_file(Path(args.export_refresh), str(result["refresh_token"]))
        status["export_refresh"] = str(Path(args.export_refresh))

    if args.json:
        print(json.dumps(status, ensure_ascii=False))
    else:
        print(f"ok refreshed=true left_min={left_min}")
    if args.print_token:
        print(access)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI surface
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
