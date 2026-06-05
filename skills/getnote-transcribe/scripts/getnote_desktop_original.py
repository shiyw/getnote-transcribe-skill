#!/usr/bin/env python3
"""Export GetNote desktop original text/transcript for an existing note."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_WEB_BASE_URL = "https://get-notes.luojilab.com"
DEFAULT_STORAGE_DIR = Path("~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def jwt_exp(token: str) -> int:
    parts = token.split(".")
    if len(parts) != 3:
        return 0
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return 0
    exp = data.get("exp")
    return int(exp) if isinstance(exp, int) else 0


def unique_tokens(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def extract_jwts_from_bytes(blob: bytes) -> list[str]:
    text = blob.decode("latin1", errors="ignore")
    return unique_tokens(match.group(0) for match in JWT_RE.finditer(text))


def load_desktop_tokens(storage_dir: Path) -> list[str]:
    expanded = storage_dir.expanduser()
    if not expanded.exists():
        raise RuntimeError(f"GetNote desktop local storage directory does not exist: {expanded}")

    tokens: list[str] = []
    for path in sorted(expanded.iterdir()):
        if not path.is_file():
            continue
        try:
            tokens.extend(extract_jwts_from_bytes(path.read_bytes()))
        except OSError as exc:
            raise RuntimeError(f"Failed to read GetNote local storage file {path}: {exc}") from exc
    return sorted(unique_tokens(tokens), key=jwt_exp, reverse=True)


def request_original_note(base_url: str, note_id: str, token: str, timeout: int) -> dict[str, Any]:
    url = f"{base_url.rstrip()}/voicenotes/web/notes/{note_id}/original"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "getnote-desktop-original/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GetNote original API failed: HTTP {exc.code}: {body}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GetNote original API failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"GetNote original API returned non-object JSON: {type(payload).__name__}")
    header = payload.get("h") if isinstance(payload.get("h"), dict) else {}
    if header.get("c") != 0:
        raise RuntimeError(f"GetNote original API returned error: {json.dumps(header, ensure_ascii=False)}")
    return payload


def fetch_original_with_tokens(base_url: str, note_id: str, tokens: list[str], timeout: int) -> dict[str, Any]:
    if not tokens:
        raise RuntimeError("No GetNote desktop tokens found. Open GetNote desktop and sign in, or set GETNOTE_WEB_TOKEN.")

    errors: list[str] = []
    for token in tokens:
        try:
            return request_original_note(base_url, note_id, token, timeout)
        except RuntimeError as exc:
            errors.append(str(exc).splitlines()[0])
    raise RuntimeError("No candidate GetNote desktop token could read the note original. Last error: " + errors[-1])


def parse_original_content(payload: Mapping[str, Any]) -> dict[str, Any]:
    content_root = payload.get("c")
    if not isinstance(content_root, Mapping):
        raise RuntimeError("GetNote original payload missing c object.")
    content = content_root.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("GetNote original payload missing c.content JSON string.")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"GetNote original c.content returned non-object JSON: {type(parsed).__name__}")
    return parsed


def sentence_list_from_original(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    parsed = parse_original_content(payload)
    sentences = parsed.get("sentence_list")
    if not isinstance(sentences, list):
        raise RuntimeError("GetNote original c.content missing sentence_list.")
    return [item for item in sentences if isinstance(item, dict)]


def ms_to_timestamp(milliseconds: Any) -> str:
    try:
        total = max(0, int(milliseconds) // 1000)
    except (TypeError, ValueError):
        total = 0
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def transcript_markdown(payload: Mapping[str, Any]) -> str:
    content_root = payload.get("c")
    if not isinstance(content_root, Mapping):
        raise RuntimeError("GetNote original payload missing c object.")
    sentences = sentence_list_from_original(payload)
    lines = [
        "> [!info] GetNote original transcript",
        f"> ASR version: {content_root.get('asr_version', '')}",
        f"> Optimized ASR: {'yes' if content_root.get('has_optimized_asr') else 'no'}",
        f"> Sentence segments: {len(sentences)}",
        "",
    ]
    for item in sentences:
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            continue
        speaker_id = item.get("speaker_id")
        speaker = item.get("speaker_name") or (
            f"Speaker {int(speaker_id) + 1}" if isinstance(speaker_id, int) else "Speaker"
        )
        lines.append(
            f"- [{ms_to_timestamp(item.get('start_time'))} - {ms_to_timestamp(item.get('end_time'))}] "
            f"**{speaker}**: {text}"
        )
    return "\n".join(lines).rstrip() + "\n"


def load_tokens(args: argparse.Namespace, environ: Mapping[str, str]) -> list[str]:
    env_token = environ.get("GETNOTE_WEB_TOKEN", "").strip()
    if env_token:
        return [env_token]
    return load_desktop_tokens(Path(args.desktop_storage_dir))


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
