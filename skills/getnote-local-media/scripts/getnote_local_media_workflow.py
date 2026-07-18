#!/usr/bin/env python3
"""Import local audio/video into GetNote and export the PC audio ASR transcript."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


# Prefer vendored module next to this script (skill-manager installs one skill dir
# at a time; monorepo skills/_shared is not part of the package).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from getnote_common import (  # noqa: E402
    DEFAULT_STORAGE_DIR,
    DEFAULT_WEB_BASE_URL,
    current_timestamp_ms,
    detect_macos_version,
    ensure_desktop_access_tokens,
    fetch_original_with_tokens,
    generate_nonce,
    generate_pc_signature,
    request_pc_json,
    stream_pc_sse_json,
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
OUTPUT_CONTENT_TYPE = "audio/mp3"
PC_AUDIO_UPLOAD_TOKEN_PATH = "/voicenotes/pc/v1/audio/upload_audio_token"
PC_ASR_FILE_PATH = "/voicenotes/pc/v1/asr/file"
PC_AUDIO_NOTE_STREAM_PATH = "/voicenotes/pc/v1/notes/polish/stream"


@dataclass(frozen=True)
class UploadInstructions:
    put_url: str
    callback: str
    audio_url: str
    file_id: str
    content_type: str = OUTPUT_CONTENT_TYPE


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


def build_pc_audio_note_payload(
    *,
    title: str,
    audio_url: str,
    duration_ms: int,
    asr_content: str,
    action_time: int | None = None,
    client_note_id: str | None = None,
) -> dict[str, Any]:
    return {
        "note_id": "0",
        "content": asr_content,
        "entry_type": "ai",
        "note_type": "audio",
        "source": "app",
        "attachments": [
            {
                "action_time": action_time or int(current_timestamp_ms()),
                "size": 0,
                "type": "audio",
                "title": title,
                "url": audio_url,
                "duration": int(duration_ms),
            }
        ],
        "client_note_id": client_note_id or f"123{current_timestamp_ms()}_voice_note",
    }


def request_pc_audio_upload_token(
    base_url: str,
    *,
    token: str,
    content_md5: str,
    timeout: int,
) -> dict[str, Any]:
    query = urllib.parse.urlencode({"content_md5": content_md5})
    path = f"{PC_AUDIO_UPLOAD_TOKEN_PATH}?{query}"
    return request_pc_json(
        base_url,
        path,
        token=token,
        method="GET",
        timeout=timeout,
        user_agent="getnote-local-media/1.0",
        timestamp=current_timestamp_ms(),
        nonce=generate_nonce(),
        os_release=detect_macos_version(),
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
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("Missing required executable: curl")
    
    command = [
        curl,
        "-X", "PUT",
        "-H", f"Content-Type: {content_type}",
        "-H", f"X-Oss-Callback: {callback}",
        "-H", "Expect:",
        "-H", "User-Agent: getnote-local-media/1.0",
        "--data-binary", "@-",
        "--max-time", str(timeout),
        "-s", "-S",
        "-i",
        upload_url
    ]
    try:
        result = subprocess.run(
            command,
            input=data,
            capture_output=True,
            check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl failed: {result.stderr.decode('utf-8', errors='replace')}")
        
        output = result.stdout.decode("utf-8", errors="replace")
        status_code = 0
        for line in output.splitlines():
            if line.startswith("HTTP/"):
                parts = line.split(" ", 2)
                if len(parts) >= 2:
                    try:
                        code = int(parts[1])
                        if code != 100:
                            status_code = code
                    except ValueError:
                        pass
        if status_code < 200 or status_code >= 300:
            raise RuntimeError(f"OSS upload HTTP {status_code}: {output}")
    except Exception as exc:
        raise RuntimeError(f"OSS upload failed: {exc}") from exc


def request_pc_asr_result(
    base_url: str,
    *,
    token: str,
    audio_url: str,
    timeout: int,
) -> dict[str, Any]:
    return request_pc_json(
        base_url,
        token=token,
        path=PC_ASR_FILE_PATH,
        method="POST",
        body={"path": audio_url},
        timeout=timeout,
        user_agent="getnote-local-media/1.0",
    )


def request_pc_audio_note(
    base_url: str,
    *,
    token: str,
    payload: Mapping[str, Any],
    timeout: int,
    raw_sse_path: Path | None,
) -> list[dict[str, Any]]:
    events = stream_pc_sse_json(
        base_url,
        PC_AUDIO_NOTE_STREAM_PATH,
        token,
        payload,
        timeout,
        raw_sse_path=None,
    )
    if raw_sse_path:
        write_redacted_pc_sse_events(events, raw_sse_path)
    return events


def load_tokens(args: argparse.Namespace, environ: Mapping[str, str]) -> list[str]:
    """Load a usable PC access JWT; auto-refresh via LocalStorage refresh_token when expired."""
    return ensure_desktop_access_tokens(
        Path(args.desktop_storage_dir),
        environ=environ,
        allow_refresh=True,
    )


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
    callback = find_string_value(payload, ("put_callback", "callback", "x_oss_callback", "oss_callback", "callback_body"))
    audio_url = find_string_value(payload, ("get_url", "audio_url", "file_url", "object_url", "resource_url", "url"))
    file_id = find_string_value(payload, ("file_id", "fid", "id"))
    content_type = find_string_value(payload, ("put_content_type", "content_type", "mime_type")) or OUTPUT_CONTENT_TYPE

    if not put_url:
        raise RuntimeError("GetNote upload-token response missing OSS upload URL.")
    if not callback:
        raise RuntimeError("GetNote upload-token response missing OSS callback.")
    if not audio_url:
        audio_url = put_url.split("?", 1)[0]
    return UploadInstructions(
        put_url=put_url,
        callback=callback,
        audio_url=audio_url,
        file_id=file_id,
        content_type=content_type,
    )


def request_upload_instructions_with_tokens(
    base_url: str,
    *,
    tokens: list[str],
    content_md5: str,
    timeout: int,
) -> tuple[str, dict[str, Any], UploadInstructions]:
    errors: list[str] = []
    for token in tokens:
        try:
            response = request_pc_audio_upload_token(
                base_url,
                token=token,
                content_md5=content_md5,
                timeout=timeout,
            )
            return token, response, extract_upload_instructions(response)
        except RuntimeError as exc:
            errors.append(str(exc).splitlines()[0])
    last_error = errors[-1] if errors else "no tokens supplied"
    raise RuntimeError("No candidate GetNote desktop token could request PC audio upload token. Last error: " + last_error)


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


def extract_pc_asr_content(payload: Mapping[str, Any]) -> str:
    content_root = payload.get("c")
    if not isinstance(content_root, Mapping):
        raise RuntimeError("GetNote PC ASR payload missing c object.")
    content = content_root.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("GetNote PC ASR payload missing c.content text.")
    return content.strip()


def extract_pc_final_note(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("msg_type") != -2:
            continue
        data = event.get("data")
        if not isinstance(data, Mapping):
            continue
        message = data.get("msg")
        if not isinstance(message, str) or not message.strip():
            continue
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"JSON decode failed in extract_pc_final_note: {exc}. Message: {message}") from exc
        if isinstance(parsed, dict):
            return parsed
    return {}


def redact_signed_url(url: str) -> tuple[str, bool]:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url, False
    redacted = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.fragment))
    return redacted, True


def redact_signed_media_urls(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(dict(payload))
    attachments = redacted.get("attachments")
    if isinstance(attachments, list):
        for item in attachments:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if isinstance(url, str):
                item["url"], was_redacted = redact_signed_url(url)
                if was_redacted:
                    item["url_query_redacted"] = True
    return redacted


def redact_pc_sse_event(event: Mapping[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(dict(event))
    data = redacted.get("data")
    if not isinstance(data, dict):
        return redacted
    message = data.get("msg")
    if not isinstance(message, str) or not message.strip():
        return redacted
    try:
        parsed = json.loads(message)
    except json.JSONDecodeError:
        return redacted
    if isinstance(parsed, Mapping):
        data["msg"] = json.dumps(redact_signed_media_urls(parsed), ensure_ascii=False, separators=(",", ":"))
    return redacted


def write_redacted_pc_sse_events(events: list[dict[str, Any]], raw_sse_path: Path) -> None:
    expanded = raw_sse_path.expanduser()
    expanded.parent.mkdir(parents=True, exist_ok=True)
    expanded.write_text(
        "".join(json.dumps(redact_pc_sse_event(event), ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def pc_asr_markdown(asr_content: str, *, note_id: str = "", original_error: str = "") -> str:
    lines = [
        "> [!info] GetNote PC audio ASR transcript",
    ]
    if note_id:
        lines.append(f"> Note ID: {note_id}")
    if original_error:
        lines.append(f"> `/original` export unavailable: {original_error}")
    lines.extend(["", asr_content.strip(), ""])
    return "\n".join(lines)


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
            "asr": False,
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
        token, upload_response, instructions = request_upload_instructions_with_tokens(
            args.base_url,
            tokens=tokens,
            content_md5=upload_payload["md5"],
            timeout=args.timeout,
        )
        media_bytes = converted_path.read_bytes()
        put_media_to_oss(
            instructions.put_url,
            data=media_bytes,
            content_type=instructions.content_type or mimetypes.guess_type(converted_path.name)[0] or OUTPUT_CONTENT_TYPE,
            content_md5=upload_payload["md5"],
            callback=instructions.callback,
            timeout=args.timeout,
        )
        asr_payload = request_pc_asr_result(
            args.base_url,
            token=token,
            audio_url=instructions.audio_url,
            timeout=args.timeout,
        )
        asr_content = extract_pc_asr_content(asr_payload)
        note_payload = build_pc_audio_note_payload(
            title=title,
            audio_url=instructions.audio_url,
            duration_ms=duration_ms,
            asr_content=asr_content,
        )
        events = request_pc_audio_note(
            args.base_url,
            token=token,
            payload=note_payload,
            timeout=args.timeout,
            raw_sse_path=raw_sse_path,
        )

    final_note = extract_pc_final_note(events)
    note_id = str(final_note.get("note_id") or final_note.get("id") or extract_note_id_from_events(events))
    if not note_id:
        raise RuntimeError("GetNote PC audio create response did not include note_id.")

    original_payload: dict[str, Any] | None = None
    original_error = ""
    try:
        original_payload = fetch_original_with_tokens(args.base_url, note_id, tokens, args.timeout)
        markdown = transcript_markdown(original_payload)
        transcript_source = "original"
    except RuntimeError as exc:
        original_error = str(exc).splitlines()[0]
        markdown = pc_asr_markdown(asr_content, note_id=note_id, original_error=original_error)
        transcript_source = "pc_asr"

    if args.raw_asr_json:
        Path(args.raw_asr_json).expanduser().write_text(
            json.dumps(asr_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.raw_note_json and final_note:
        Path(args.raw_note_json).expanduser().write_text(
            json.dumps(redact_signed_media_urls(final_note), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.raw_original_json and original_payload:
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
        "transcript_source": transcript_source,
        "output": args.output or "",
        "raw_asr_json": args.raw_asr_json or "",
        "raw_note_json": args.raw_note_json or "",
        "raw_original_json": args.raw_original_json or "",
        "raw_sse_jsonl": args.raw_sse_jsonl or "",
        "events": len(events),
        "original_error": original_error,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media_path", help="Local audio/video file to import into GetNote.")
    parser.add_argument("--output", help="Write Markdown transcript to this path. Defaults to stdout after import.")
    parser.add_argument("--raw-asr-json", help="Write the raw PC ASR JSON payload to this path.")
    parser.add_argument("--raw-note-json", help="Write the final GetNote note object with signed media URLs redacted.")
    parser.add_argument("--raw-original-json", help="Write the raw /original JSON payload to this path.")
    parser.add_argument("--raw-sse-jsonl", help="Write parsed PC audio-note SSE events as JSONL.")
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
