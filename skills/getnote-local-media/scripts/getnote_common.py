#!/usr/bin/env python3
"""Shared helpers for GetNote skills.

Monorepo source of truth. Scene skills vendor a copy at scripts/getnote_common.py
because skill installers only ship one skill directory (no skills/_shared/).
After editing this file, run: bash scripts/vendor_getnote_common.sh
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import platform
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_WEB_BASE_URL = "https://get-notes.luojilab.com"
DEFAULT_STORAGE_DIR = Path("~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb")
DEFAULT_PC_APP_NAME = "GetNotePCAPP"
DEFAULT_PC_APP_VERSION = "1.4.0"
DEFAULT_PC_OS = "mac"
DEFAULT_PC_SIGNATURE_SECRET = "pDP4w91sJa3tDYQ3Rgv/C/LSQgnRohbsv58Kv0EUXWE="
DEFAULT_REFRESH_URL = "https://notes-api.biji.com/account/v2/web/user/auth/refresh"
DEFAULT_DESKTOP_UA = "iget-biji-desktop/2.1.0 GetNotePCAPP/2.1.0"
# Access JWT is typically ~30 minutes; refresh a bit early.
DEFAULT_TOKEN_MIN_TTL_SECONDS = 60
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


def token_is_fresh(token: str, *, min_ttl_seconds: int = DEFAULT_TOKEN_MIN_TTL_SECONDS) -> bool:
    return jwt_exp(token) > int(time.time()) + int(min_ttl_seconds)


def strip_chromium_localstorage_value(raw: bytes) -> str:
    """Chromium Local Storage string values are prefixed with a 0x01 type byte."""
    if not raw:
        return ""
    body = raw[1:] if raw[:1] == b"\x01" else raw
    return body.decode("utf-8")


def _localstorage_key_name(key: bytes) -> str:
    """Return the DOM key name from a Chromium Local Storage leveldb key.

    Observed shape: ``b'_file://\\x00\\x01refresh_token'`` → ``refresh_token``.
    """
    text = key.decode("latin1", errors="replace")
    if "\x00\x01" in text:
        return text.split("\x00\x01", 1)[1]
    if text.startswith("_file://"):
        return text[len("_file://") :].lstrip("\x00\x01")
    return text


def load_desktop_localstorage_items(storage_dir: Path | None = None) -> dict[str, str]:
    """Read Chromium Local Storage via plyvel from a **temp copy** of the leveldb.

    Important:
    - Do **not** regex-scrape raw ``.ldb`` bytes. LevelDB block compression corrupts
      runs of identical characters (e.g. ``AAAAAAA`` inside refresh_token), so
      reconstructed tokens will fail with ``20124 刷新Token已过期`` even when the
      real refresh_token is still valid.
    - Copy the DB first: 得到大脑 may hold LOCK while running.
    """
    try:
        import plyvel  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Reading desktop Local Storage requires plyvel. "
            "Install with: python3 -m pip install plyvel-ci "
            "(or plyvel if system leveldb headers are available)."
        ) from exc

    import shutil
    import tempfile

    expanded = (storage_dir or DEFAULT_STORAGE_DIR).expanduser()
    if not expanded.exists():
        raise RuntimeError(f"GetNote desktop local storage directory does not exist: {expanded}")

    tmp_root = Path(tempfile.mkdtemp(prefix="getnote-leveldb-"))
    tmp_db = tmp_root / "leveldb"
    try:
        shutil.copytree(expanded, tmp_db)
        (tmp_db / "LOCK").unlink(missing_ok=True)
        db = plyvel.DB(str(tmp_db), create_if_missing=False)
        try:
            items: dict[str, str] = {}
            for key, value in db:
                name = _localstorage_key_name(key)
                if not name:
                    continue
                try:
                    items[name] = strip_chromium_localstorage_value(value)
                except UnicodeDecodeError:
                    continue
            return items
        finally:
            db.close()
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def load_desktop_refresh_token(storage_dir: Path | None = None) -> tuple[str, int | None]:
    """Return ``(refresh_token, expire_at_unix_or_None)`` from desktop Local Storage."""
    items = load_desktop_localstorage_items(storage_dir)
    refresh_token = (items.get("refresh_token") or "").strip()
    if not refresh_token:
        raise RuntimeError(
            "No refresh_token in GetNote desktop Local Storage. "
            "Open 得到大脑 and sign in once, then retry."
        )
    expire_raw = (items.get("refresh_token_expire_at") or "").strip()
    expire_at: int | None
    try:
        expire_at = int(expire_raw) if expire_raw else None
    except ValueError:
        expire_at = None
    return refresh_token, expire_at


def _find_nested_string(obj: Any, key_names: set[str]) -> str | None:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if key in key_names and isinstance(value, str) and value.strip():
                return value.strip()
            found = _find_nested_string(value, key_names)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_nested_string(item, key_names)
            if found:
                return found
    return None


def refresh_desktop_access_token(
    *,
    refresh_token: str | None = None,
    storage_dir: Path | None = None,
    refresh_url: str = DEFAULT_REFRESH_URL,
    timeout: int = 30,
    user_agent: str = DEFAULT_DESKTOP_UA,
) -> dict[str, Any]:
    """Exchange desktop ``refresh_token`` for a new access JWT.

    Returns a dict with:
    - ``access_token``: new JWT (also under legacy-friendly shape used by callers)
    - ``refresh_token``: rotated refresh token if the API returned one, else the input
    - ``exp``: JWT exp unix timestamp when parseable
    - ``uid``: optional uid from response body
    - ``raw_c``: response ``c`` object

    Never logs or prints token values.
    """
    expire_at: int | None = None
    token_value = (refresh_token or "").strip()
    if not token_value:
        token_value, expire_at = load_desktop_refresh_token(storage_dir)
    if expire_at is not None and expire_at <= int(time.time()):
        raise RuntimeError(
            "Desktop refresh_token_expire_at is in the past. "
            "Re-login in 得到大脑, then retry."
        )

    body = json.dumps({"refresh_token": token_value}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        refresh_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": user_agent,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GetNote refresh HTTP {exc.code}: {detail}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GetNote refresh failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"GetNote refresh returned non-object JSON: {type(payload).__name__}")

    header = payload.get("h") if isinstance(payload.get("h"), Mapping) else {}
    code = header.get("c") if header else 0
    if code not in (0, None):
        message = header.get("e") or json.dumps(header, ensure_ascii=False)
        # 20124 = 刷新Token已过期
        raise RuntimeError(f"GetNote refresh API error c={code}: {message}")

    content = payload.get("c")
    if not isinstance(content, Mapping):
        raise RuntimeError("GetNote refresh response missing c object.")

    # Observed success shape: c.token.token (JWT). Prefer that over any other "token" field.
    access_token: str | None = None
    token_obj = content.get("token")
    if isinstance(token_obj, Mapping) and isinstance(token_obj.get("token"), str):
        access_token = token_obj["token"].strip()
    elif isinstance(token_obj, str) and token_obj.startswith("eyJ"):
        access_token = token_obj.strip()
    else:
        candidate = _find_nested_string(content, {"access_token", "token"})
        if candidate and candidate.startswith("eyJ"):
            access_token = candidate
    if not access_token or not access_token.startswith("eyJ"):
        raise RuntimeError("GetNote refresh response did not include c.token.token JWT.")

    new_refresh = _find_nested_string(content, {"refresh_token"}) or token_value
    exp = jwt_exp(access_token)
    uid = content.get("uid")
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "exp": exp,
        "uid": uid,
        "raw_c": content,
    }


def ensure_desktop_access_tokens(
    storage_dir: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    min_ttl_seconds: int = DEFAULT_TOKEN_MIN_TTL_SECONDS,
    allow_refresh: bool = True,
) -> list[str]:
    """Return a usable access JWT list: env → fresh desktop JWT → refresh API.

    Order:
    1. ``GETNOTE_WEB_TOKEN`` if still fresh
    2. JWTs scraped from desktop leveldb files if still fresh
    3. If ``allow_refresh``, exchange LocalStorage ``refresh_token`` via the refresh API
    """
    env_map = environ if environ is not None else {}
    env_token = str(env_map.get("GETNOTE_WEB_TOKEN", "")).strip()
    if env_token and token_is_fresh(env_token, min_ttl_seconds=min_ttl_seconds):
        return [env_token]

    storage = (storage_dir or DEFAULT_STORAGE_DIR).expanduser()
    desktop_tokens: list[str] = []
    try:
        desktop_tokens = load_desktop_tokens(storage)
    except RuntimeError:
        desktop_tokens = []
    fresh = [t for t in desktop_tokens if token_is_fresh(t, min_ttl_seconds=min_ttl_seconds)]
    if fresh:
        return fresh

    if not allow_refresh:
        if env_token:
            return [env_token]
        if desktop_tokens:
            return desktop_tokens
        raise RuntimeError("No GetNote desktop tokens found.")

    try:
        refreshed = refresh_desktop_access_token(storage_dir=storage)
    except RuntimeError as exc:
        if env_token:
            return [env_token]
        if desktop_tokens:
            return desktop_tokens
        raise RuntimeError(
            "No fresh GetNote desktop access token. "
            f"Refresh failed: {exc}. "
            "Open 得到大脑 and sign in, or set a fresh GETNOTE_WEB_TOKEN."
        ) from exc
    return [refreshed["access_token"]]


def bearer_headers(
    token: str,
    *,
    accept: str = "application/json",
    content_type: str | None = "application/json",
    user_agent: str = "getnote-skill/1.0",
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "User-Agent": user_agent,
    }
    if content_type:
        headers["Content-Type"] = content_type
    if extra:
        headers.update(dict(extra))
    return headers


def current_timestamp_ms() -> str:
    return str(int(time.time() * 1000))


def generate_nonce() -> str:
    return str(uuid.uuid4())


def detect_macos_version() -> str:
    return platform.mac_ver()[0] or platform.release()


def generate_pc_signature(method: str, path: str, timestamp: str, nonce: str, raw_body: str = "") -> str:
    path_without_query = path.split("?", 1)[0]
    plain_text = f"{method.upper()}\n{path_without_query}\n{timestamp}{nonce}{raw_body}"
    return hmac.new(
        DEFAULT_PC_SIGNATURE_SECRET.encode("utf-8"),
        plain_text.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def pc_signed_headers(
    token: str,
    *,
    method: str,
    path: str,
    raw_body: str = "",
    accept: str = "application/json",
    content_type: str | None = "application/json",
    user_agent: str = "getnote-pc-skill/1.0",
    timestamp: str | None = None,
    nonce: str | None = None,
    os_release: str | None = None,
) -> dict[str, str]:
    request_timestamp = timestamp or current_timestamp_ms()
    request_nonce = nonce or generate_nonce()
    headers = bearer_headers(token, accept=accept, content_type=content_type, user_agent=user_agent)
    headers.update(
        {
            "X-Av": "1.0.0-desktop",
            "X-Appid": "3",
            "version": "1.0.0-desktop",
            "X-PCAPP-Name": DEFAULT_PC_APP_NAME,
            "X-PCAPP-Version": DEFAULT_PC_APP_VERSION,
            "X-PCAPP-OS": DEFAULT_PC_OS,
            "X-PCAPP-OS-Release": os_release or detect_macos_version(),
            "X-PCAPP-Timestamp": request_timestamp,
            "X-PCAPP-Nonce": request_nonce,
            "X-PCAPP-Signature": generate_pc_signature(method, path, request_timestamp, request_nonce, raw_body),
        }
    )
    return headers


def json_request_body(body: Mapping[str, Any] | None) -> str:
    if body is None:
        return ""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def request_pc_json(
    base_url: str,
    path: str,
    *,
    token: str,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
    timeout: int = 30,
    user_agent: str = "getnote-pc-skill/1.0",
    timestamp: str | None = None,
    nonce: str | None = None,
    os_release: str | None = None,
) -> dict[str, Any]:
    raw_body = json_request_body(body) if method != "GET" else ""
    data = raw_body.encode("utf-8") if raw_body else None
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers=pc_signed_headers(
            token,
            method=method,
            path=path,
            raw_body=raw_body,
            user_agent=user_agent,
            timestamp=timestamp,
            nonce=nonce,
            os_release=os_release,
        ),
    )
    raw_response_bytes = b""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_response_bytes = response.read()
            payload = json.loads(raw_response_bytes.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GetNote PC API failed: HTTP {exc.code}: {body_text}") from exc
    except json.JSONDecodeError as exc:
        body_text = raw_response_bytes.decode("utf-8", errors="replace")
        raise RuntimeError(f"GetNote PC API JSON decode failed: {exc}. Response text: {body_text}") from exc
    except OSError as exc:
        raise RuntimeError(f"GetNote PC API failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"GetNote PC API returned non-object JSON: {type(payload).__name__}")
    validate_getnote_header(payload)
    return payload


def stream_pc_sse_json(
    base_url: str,
    path: str,
    token: str,
    payload: Mapping[str, Any],
    timeout: int,
    *,
    raw_sse_path: Path | None = None,
    user_agent: str = "getnote-pc-skill/1.0",
) -> list[dict[str, Any]]:
    raw_body = json_request_body(payload)
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=raw_body.encode("utf-8"),
        method="POST",
        headers=pc_signed_headers(
            token,
            method="POST",
            path=path,
            raw_body=raw_body,
            accept="text/event-stream",
            user_agent=user_agent,
        ),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GetNote PC SSE API failed: HTTP {exc.code}: {response_body}") from exc
    except OSError as exc:
        raise RuntimeError(f"GetNote PC SSE API failed: {exc}") from exc

    events = parse_sse_json_events(response_body.splitlines())
    if raw_sse_path:
        expanded = raw_sse_path.expanduser()
        expanded.parent.mkdir(parents=True, exist_ok=True)
        expanded.write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
            encoding="utf-8",
        )
    return events


def request_web_json(
    base_url: str,
    path: str,
    *,
    token: str,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
    timeout: int = 30,
    user_agent: str = "getnote-skill/1.0",
) -> dict[str, Any]:
    data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if method != "GET" else None
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers=bearer_headers(token, user_agent=user_agent),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GetNote web API failed: HTTP {exc.code}: {body_text}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GetNote web API failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"GetNote web API returned non-object JSON: {type(payload).__name__}")
    validate_getnote_header(payload)
    return payload


def stream_web_sse_json(
    base_url: str,
    path: str,
    *,
    token: str,
    body: Mapping[str, Any],
    timeout: int,
    user_agent: str = "getnote-skill/1.0",
    raw_sse_path: Path | None = None,
) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=bearer_headers(
            token,
            accept="text/event-stream, application/json",
            user_agent=user_agent,
        ),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GetNote SSE API failed: HTTP {exc.code}: {response_body}") from exc
    except OSError as exc:
        raise RuntimeError(f"GetNote SSE API failed: {exc}") from exc

    events = parse_sse_json_events(response_body.splitlines())
    if not events and response_body.strip():
        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            validate_getnote_header(parsed)
            events.append(parsed)
    if raw_sse_path:
        expanded = raw_sse_path.expanduser()
        expanded.parent.mkdir(parents=True, exist_ok=True)
        expanded.write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
            encoding="utf-8",
        )
    return events


def parse_sse_json_events(lines: Iterable[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_sse_event(data_lines, events)
            data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    flush_sse_event(data_lines, events)
    return events


def flush_sse_event(data_lines: list[str], events: list[dict[str, Any]]) -> None:
    if not data_lines:
        return
    data = "\n".join(data_lines).strip()
    if not data or data == "[DONE]":
        return
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return
    if isinstance(parsed, dict):
        validate_getnote_header(parsed)
        events.append(parsed)


def validate_getnote_header(payload: Mapping[str, Any]) -> None:
    header = payload.get("h") if isinstance(payload.get("h"), Mapping) else {}
    if header and header.get("c") != 0:
        raise RuntimeError(f"GetNote web API returned error: {json.dumps(header, ensure_ascii=False)}")


def request_original_note(base_url: str, note_id: str, token: str, timeout: int) -> dict[str, Any]:
    return request_web_json(
        base_url,
        f"/voicenotes/web/notes/{note_id}/original",
        token=token,
        timeout=timeout,
        user_agent="getnote-desktop-original/1.0",
    )


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
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON decode failed in parse_original_content: {exc}. Content: {content}") from exc
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
