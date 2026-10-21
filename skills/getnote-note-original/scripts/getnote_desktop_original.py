#!/usr/bin/env python3
"""Export GetNote original text/transcript for an existing note via OpenAPI."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_API_BASE_URL = "https://openapi.biji.com"


@dataclass(frozen=True)
class ApiCredentials:
    api_key: str
    client_id: str


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


def load_getnote_credentials(
    env_file: Path | str = Path(".env"),
    environ: Mapping[str, str] | None = None,
) -> ApiCredentials:
    env = dict(environ if environ is not None else os.environ)
    dotenv = load_env_file(Path(env_file))
    api_key = env.get("GETNOTE_API_KEY") or dotenv.get("GETNOTE_API_KEY") or ""
    client_id = env.get("GETNOTE_CLIENT_ID") or dotenv.get("GETNOTE_CLIENT_ID") or ""
    return ApiCredentials(api_key=api_key, client_id=client_id)


class GetNoteAPI:
    def __init__(self, credentials: ApiCredentials, base_url: str = DEFAULT_API_BASE_URL, timeout: int = 30) -> None:
        if not credentials.api_key:
            raise RuntimeError("Missing GETNOTE_API_KEY.")
        if not credentials.client_id:
            raise RuntimeError("Missing GETNOTE_CLIENT_ID.")
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, query: Mapping[str, str] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": self.credentials.api_key,
                "X-Client-ID": self.credentials.client_id,
                "Accept": "application/json",
                "User-Agent": "getnote-note-original/2.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GetNote API failed: HTTP {exc.code}: {body}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GetNote API failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"GetNote API returned non-object JSON: {type(payload).__name__}")
        if payload.get("success") is False:
            raise RuntimeError(
                f"GetNote API returned error: {json.dumps(payload.get('error') or payload, ensure_ascii=False)}"
            )
        return payload


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
    if "data" in payload and isinstance(payload["data"], Mapping) and "note" in payload["data"]:
        note = payload["data"]["note"]
    elif "note" in payload and isinstance(payload["note"], Mapping):
        note = payload["note"]
    elif "c" in payload and isinstance(payload["c"], Mapping):
        c = payload["c"]
        content_raw = c.get("content")
        sentences: list[dict[str, Any]] = []
        if isinstance(content_raw, str):
            try:
                parsed = json.loads(content_raw)
                if isinstance(parsed, dict) and isinstance(parsed.get("sentence_list"), list):
                    sentences = parsed["sentence_list"]
            except Exception:
                pass
        note = {
            "title": c.get("title", ""),
            "audio": {
                "sentences": sentences,
                "original": content_raw if not sentences and isinstance(content_raw, str) else "",
            },
            "asr_version": c.get("asr_version"),
            "has_optimized_asr": c.get("has_optimized_asr"),
        }
    else:
        note = payload

    note_id = str(note.get("note_id") or note.get("id") or "")
    title = str(note.get("title") or "")
    note_type = str(note.get("note_type") or "")
    audio = note.get("audio") if isinstance(note.get("audio"), Mapping) else {}
    sentences = audio.get("sentences") if isinstance(audio.get("sentences"), list) else []
    audio_original = str(audio.get("original") or "").strip()
    web_page = note.get("web_page") if isinstance(note.get("web_page"), Mapping) else {}
    web_page_content = str(web_page.get("content") or "").strip()
    content = str(note.get("content") or "").strip()

    lines = [
        "> [!info] GetNote original transcript",
    ]
    if note_id:
        lines.append(f"> Note ID: {note_id}")
    if title:
        lines.append(f"> Title: {title}")
    if note_type:
        lines.append(f"> Note type: {note_type}")

    if sentences:
        lines.append(f"> Sentence segments: {len(sentences)}")
        lines.append("")
        for item in sentences:
            if not isinstance(item, Mapping):
                continue
            text = " ".join(str(item.get("text") or "").split())
            if not text:
                continue
            speaker_id = item.get("speaker_id")
            speaker_name = item.get("speaker_name")
            speaker = speaker_name or (
                f"Speaker {int(speaker_id) + 1}" if isinstance(speaker_id, int) else "Speaker"
            )
            start_val = item.get("start_ms") if item.get("start_ms") is not None else item.get("start_time")
            end_val = item.get("end_ms") if item.get("end_ms") is not None else item.get("end_time")
            lines.append(f"- [{ms_to_timestamp(start_val)} - {ms_to_timestamp(end_val)}] **{speaker}**: {text}")
    elif audio_original:
        lines.append("")
        lines.append(audio_original)
    elif web_page_content:
        lines.append("")
        lines.append(web_page_content)
    elif content:
        lines.append("> Source: AI summary fallback")
        lines.append("")
        lines.append(content)
    else:
        lines.append("")
        lines.append("*(No transcript or content available)*")

    return "\n".join(lines).rstrip() + "\n"


def fetch_note_detail(api: GetNoteAPI, note_id: str) -> dict[str, Any]:
    return api.get("/open/api/v1/resource/note/detail", {"id": str(note_id)})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export an existing GetNote note original transcript by note_id via OpenAPI."
    )
    parser.add_argument("note_id", help="GetNote note_id. Keep it as a string to avoid 64-bit integer precision loss.")
    parser.add_argument("--output", help="Write Markdown transcript to this path. Defaults to stdout.")
    parser.add_argument("--raw-json", help="Also write the raw OpenAPI JSON payload to this path.")
    parser.add_argument("--env-file", default=".env", help="Path to .env file for GETNOTE_API_KEY and GETNOTE_CLIENT_ID.")
    parser.add_argument("--base-url", default=DEFAULT_API_BASE_URL, help="OpenAPI base URL.")
    parser.add_argument("--timeout", type=int, default=30, help="API request timeout in seconds.")
    # Kept for backward compatibility with legacy invocations
    parser.add_argument("--desktop-storage-dir", default=None, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        credentials = load_getnote_credentials(env_file=Path(args.env_file), environ=os.environ)
        api = GetNoteAPI(credentials, base_url=args.base_url, timeout=args.timeout)
        payload = fetch_note_detail(api, str(args.note_id))
        markdown = transcript_markdown(payload)
        if args.raw_json:
            Path(args.raw_json).expanduser().write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if args.output:
            Path(args.output).expanduser().write_text(markdown, encoding="utf-8")
        else:
            try:
                sys.stdout.write(markdown)
                sys.stdout.flush()
            except BrokenPipeError:
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, sys.stdout.fileno())
                return 0
    except BrokenPipeError:
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
