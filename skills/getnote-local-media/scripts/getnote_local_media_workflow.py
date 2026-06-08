#!/usr/bin/env python3
"""Import local audio/video into GetNote and export the private original transcript."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SHARED_DIR = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(SHARED_DIR))

from getnote_common import (  # noqa: E402
    DEFAULT_STORAGE_DIR,
    DEFAULT_WEB_BASE_URL,
    fetch_original_with_tokens,
    load_desktop_tokens,
    request_web_json,
    stream_web_sse_json,
    transcript_markdown,
)


SUPPORTED_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}
OUTPUT_MEDIA_TYPE = "mp3"
OUTPUT_CONTENT_TYPE = "audio/mpeg"
UPLOAD_TOKEN_PATH = "/voicenotes/web/notes/local_audio/token"
CREATE_LOCAL_AUDIO_PATH = "/voicenotes/web/topics/notes/stream_on_local_audio"


@dataclass(frozen=True)
class UploadInstructions:
    put_url: str
    callback: str
    audio_url: str
    file_id: str


def content_md5_base64(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


def build_upload_token_payload(
    media_path: Path,
    *,
    duration_ms: int,
    media_type: str = OUTPUT_MEDIA_TYPE,
    local_name: str | None = None,
) -> dict[str, Any]:
    data = media_path.read_bytes()
    return {
        "duration_ms": int(duration_ms),
        "local_name": local_name or media_path.name,
        "md5": content_md5_base64(data),
        "size_byte": len(data),
        "type": media_type,
    }


def build_local_audio_payload(
    *,
    title: str,
    audio_url: str,
    file_id: str,
    duration_ms: int,
    local_name: str,
    size_byte: int,
    media_type: str,
) -> dict[str, Any]:
    audio = {
        "url": audio_url,
        "audio_url": audio_url,
        "file_id": file_id,
        "duration_ms": int(duration_ms),
        "local_name": local_name,
        "size_byte": int(size_byte),
        "type": media_type,
    }
    return {
        "note_type": "local_audio",
        "source": "web",
        "entry_type": "local_audio",
        "title": title,
        "audio": audio,
        "audio_url": audio_url,
        "file_id": file_id,
        "duration_ms": int(duration_ms),
        "local_name": local_name,
        "size_byte": int(size_byte),
        "type": media_type,
    }


def request_media_upload_token(
    base_url: str,
    *,
    token: str,
    payload: Mapping[str, Any],
    timeout: int,
) -> dict[str, Any]:
    return request_web_json(
        base_url,
        UPLOAD_TOKEN_PATH,
        token=token,
        method="POST",
        body=payload,
        timeout=timeout,
        user_agent="getnote-local-media/1.0",
    )


def put_media_to_oss(
    upload_url: str,
    *,
    data: bytes,
    content_type: str,
    content_md5: str,
    callback: str,
    timeout: int,
) -> None:
    request = urllib.request.Request(
        upload_url,
        data=data,
        method="PUT",
        headers={
            "Content-Type": content_type,
            "Content-MD5": content_md5,
            "X-Oss-Callback": callback,
            "User-Agent": "getnote-local-media/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OSS upload failed: HTTP {exc.code}: {body}") from exc
    except OSError as exc:
        raise RuntimeError(f"OSS upload failed: {exc}") from exc


def stream_sse_json(
    base_url: str,
    path: str,
    token: str,
    payload: Mapping[str, Any],
    timeout: int,
    *,
    raw_sse_path: Path | None = None,
) -> list[dict[str, Any]]:
    return stream_web_sse_json(
        base_url,
        path,
        token=token,
        body=payload,
        timeout=timeout,
        user_agent="getnote-local-media/1.0",
        raw_sse_path=raw_sse_path,
    )


def request_local_audio_note(
    base_url: str,
    *,
    token: str,
    payload: Mapping[str, Any],
    timeout: int,
    raw_sse_path: Path | None,
) -> list[dict[str, Any]]:
    return stream_sse_json(
        base_url,
        CREATE_LOCAL_AUDIO_PATH,
        token,
        payload,
        timeout,
        raw_sse_path=raw_sse_path,
    )


def load_tokens(args: argparse.Namespace, environ: Mapping[str, str]) -> list[str]:
    env_token = environ.get("GETNOTE_WEB_TOKEN", "").strip()
    if env_token:
        return [env_token]
    return load_desktop_tokens(Path(args.desktop_storage_dir))


def validate_media_path(media_path: Path) -> Path:
    expanded = media_path.expanduser()
    if not expanded.exists():
        raise RuntimeError(f"Media file does not exist: {expanded}")
    if not expanded.is_file():
        raise RuntimeError(f"Media path is not a file: {expanded}")
    if expanded.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise RuntimeError(f"Unsupported media extension: {expanded.suffix}")
    return expanded


def make_transcode_plan(media_path: Path) -> dict[str, Any]:
    output_name = media_path.with_suffix(".mp3").name
    return {
        "input": str(media_path),
        "output_name": output_name,
        "output_type": OUTPUT_MEDIA_TYPE,
        "output_content_type": OUTPUT_CONTENT_TYPE,
        "ffmpeg_found": bool(shutil.which("ffmpeg")),
        "ffprobe_found": bool(shutil.which("ffprobe")),
        "supported_extension": media_path.suffix.lower() in SUPPORTED_EXTENSIONS,
    }


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Missing required executable: {name}")
    return path


def probe_duration_ms(media_path: Path, timeout: int) -> int:
    ffprobe = require_tool("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(media_path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
        seconds = float(payload.get("format", {}).get("duration", 0))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ffprobe returned invalid duration: {exc}") from exc
    return max(0, int(seconds * 1000))


def transcode_to_mp3(input_path: Path, output_path: Path, timeout: int) -> None:
    ffmpeg = require_tool("ffmpeg")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-b:a",
        "64k",
        "-c:a",
        "libmp3lame",
        str(output_path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg transcode failed: {result.stderr.strip()}")


def extract_upload_instructions(payload: Mapping[str, Any]) -> UploadInstructions:
    put_url = find_string_value(payload, ("put_sign_url", "put_url", "upload_url", "signed_url"))
    callback = find_string_value(payload, ("callback", "x_oss_callback", "oss_callback", "callback_body"))
    audio_url = find_string_value(payload, ("audio_url", "file_url", "object_url", "resource_url", "url"))
    file_id = find_string_value(payload, ("file_id", "fid", "id"))

    if not put_url:
        raise RuntimeError("GetNote upload-token response missing OSS upload URL.")
    if not callback:
        raise RuntimeError("GetNote upload-token response missing OSS callback.")
    if not audio_url:
        audio_url = put_url.split("?", 1)[0]
    return UploadInstructions(put_url=put_url, callback=callback, audio_url=audio_url, file_id=file_id)


def find_string_value(value: Any, keys: tuple[str, ...]) -> str:
    if isinstance(value, Mapping):
        for key in keys:
            item = value.get(key)
            if isinstance(item, str) and item:
                return item
        for item in value.values():
            found = find_string_value(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_string_value(item, keys)
            if found:
                return found
    return ""


def extract_note_id_from_events(events: list[dict[str, Any]]) -> str:
    for event in events:
        note_id = find_string_value(event, ("note_id", "noteId"))
        if note_id:
            return note_id
        numeric_id = find_number_value(event, ("note_id", "noteId", "id"))
        if numeric_id:
            return str(numeric_id)
    return ""


def find_number_value(value: Any, keys: tuple[str, ...]) -> int:
    if isinstance(value, Mapping):
        for key in keys:
            item = value.get(key)
            if isinstance(item, int):
                return item
        for item in value.values():
            found = find_number_value(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_number_value(item, keys)
            if found:
                return found
    return 0


def run_dry_run(args: argparse.Namespace, media_path: Path, tokens: list[str]) -> dict[str, Any]:
    return {
        "success": True,
        "dry_run": True,
        "media_path": str(media_path),
        "title": args.title or media_path.stem,
        "token_available": bool(tokens),
        "token_count": len(tokens),
        "transcode_plan": make_transcode_plan(media_path),
        "remote_writes": {
            "upload_token": False,
            "oss_put": False,
            "create_note": False,
        },
    }


def run_import(args: argparse.Namespace) -> dict[str, Any]:
    media_path = validate_media_path(Path(args.media_path))
    tokens = load_tokens(args, os.environ)
    if not tokens:
        raise RuntimeError("No GetNote desktop tokens found.")
    if args.dry_run:
        return run_dry_run(args, media_path, tokens)

    title = args.title or media_path.stem
    output_name = media_path.with_suffix(".mp3").name
    raw_sse_path = Path(args.raw_sse_jsonl).expanduser() if args.raw_sse_jsonl else None

    with tempfile.TemporaryDirectory() as tmp:
        converted_path = Path(tmp) / output_name
        transcode_to_mp3(media_path, converted_path, timeout=args.timeout)
        duration_ms = probe_duration_ms(converted_path, timeout=args.timeout)
        upload_payload = build_upload_token_payload(
            converted_path,
            duration_ms=duration_ms,
            media_type=OUTPUT_MEDIA_TYPE,
            local_name=output_name,
        )
        token = tokens[0]
        upload_response = request_media_upload_token(
            args.base_url,
            token=token,
            payload=upload_payload,
            timeout=args.timeout,
        )
        instructions = extract_upload_instructions(upload_response)
        media_bytes = converted_path.read_bytes()
        put_media_to_oss(
            instructions.put_url,
            data=media_bytes,
            content_type=mimetypes.guess_type(converted_path.name)[0] or OUTPUT_CONTENT_TYPE,
            content_md5=upload_payload["md5"],
            callback=instructions.callback,
            timeout=args.timeout,
        )
        note_payload = build_local_audio_payload(
            title=title,
            audio_url=instructions.audio_url,
            file_id=instructions.file_id,
            duration_ms=duration_ms,
            local_name=output_name,
            size_byte=upload_payload["size_byte"],
            media_type=OUTPUT_MEDIA_TYPE,
        )
        events = request_local_audio_note(
            args.base_url,
            token=token,
            payload=note_payload,
            timeout=args.timeout,
            raw_sse_path=raw_sse_path,
        )

    note_id = extract_note_id_from_events(events)
    if not note_id:
        raise RuntimeError("GetNote local_audio create response did not include note_id.")

    original_payload = fetch_original_with_tokens(args.base_url, note_id, tokens, args.timeout)
    markdown = transcript_markdown(original_payload)
    if args.raw_original_json:
        Path(args.raw_original_json).expanduser().write_text(
            json.dumps(original_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.output:
        Path(args.output).expanduser().write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)

    return {
        "success": True,
        "note_id": note_id,
        "output": args.output or "",
        "raw_original_json": args.raw_original_json or "",
        "raw_sse_jsonl": args.raw_sse_jsonl or "",
        "events": len(events),
    }



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media_path", help="Local audio/video file to import into GetNote.")
    parser.add_argument("--output", help="Write Markdown transcript to this path. Defaults to stdout after import.")
    parser.add_argument("--raw-original-json", help="Write the raw /original JSON payload to this path.")
    parser.add_argument("--raw-sse-jsonl", help="Write parsed local_audio SSE events as JSONL.")
    parser.add_argument("--title", default="", help="Optional GetNote note title.")
    parser.add_argument("--base-url", default=DEFAULT_WEB_BASE_URL)
    parser.add_argument("--desktop-storage-dir", default=str(DEFAULT_STORAGE_DIR))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", help="Check local plan and token availability without remote writes.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_import(args)
        if args.dry_run:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
