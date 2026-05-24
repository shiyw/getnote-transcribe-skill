#!/usr/bin/env python3
"""Run an API-only GetNote URL save/read/export workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_API_BASE_URL = "https://openapi.biji.com"
DEFAULT_OUTPUT_DIR = Path("getnote_exports")
DEFAULT_MANIFEST = Path("getnote_manifest.jsonl")
DEFAULT_BATCH_TAG = "GetNote转译"


@dataclass(frozen=True)
class ApiCredentials:
    api_key: str
    client_id: str


class GetNoteAPI:
    def __init__(self, credentials: ApiCredentials, base_url: str, timeout: int) -> None:
        if not credentials.api_key:
            raise RuntimeError("Missing GETNOTE_API_KEY.")
        if not credentials.client_id:
            raise RuntimeError("Missing GETNOTE_CLIENT_ID.")
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, query: Mapping[str, str] | None = None) -> dict[str, Any]:
        url = self._url(path, query)
        request = urllib.request.Request(url, method="GET", headers=self._headers())
        return self._open_json(request)

    def post(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._url(path),
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=self._headers(content_type="application/json"),
        )
        return self._open_json(request)

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": self.credentials.api_key,
            "X-Client-ID": self.credentials.client_id,
            "Accept": "application/json",
            "User-Agent": "getnote-url-workflow/2.0",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _url(self, path: str, query: Mapping[str, str] | None = None) -> str:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    def _open_json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GetNote API failed: HTTP {exc.code}: {body}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GetNote API failed: {exc}") from exc

        if isinstance(payload, dict) and payload.get("success") is False:
            raise RuntimeError(f"GetNote API returned error: {json.dumps(payload.get('error') or payload, ensure_ascii=False)}")
        return payload


def load_getnote_credentials(
    env_file: Path | str = Path(".env"),
    environ: Mapping[str, str] | None = None,
) -> ApiCredentials:
    env = dict(environ if environ is not None else os.environ)
    dotenv = load_env_file(Path(env_file))
    api_key = env.get("GETNOTE_API_KEY") or dotenv.get("GETNOTE_API_KEY") or ""
    client_id = env.get("GETNOTE_CLIENT_ID") or dotenv.get("GETNOTE_CLIENT_ID") or ""
    return ApiCredentials(api_key=api_key, client_id=client_id)


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


def parse_url_list(path: Path) -> list[str]:
    urls: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if " #" in value:
            value = value.split(" #", 1)[0].strip()
        if not is_http_url(value):
            raise ValueError(f"Invalid URL at {path}:{line_no}: {value}")
        urls.append(value)
    return urls


def build_save_link_payload(url: str, title: str = "", tags: list[str] | None = None) -> dict[str, Any]:
    if not is_http_url(url):
        raise ValueError(f"Only http/https URLs are supported: {url}")

    payload: dict[str, Any] = {
        "note_type": "link",
        "link_url": url,
    }
    if title:
        payload["title"] = title
    return payload


def save_link(api: GetNoteAPI, url: str, title: str, tags: list[str]) -> dict[str, Any]:
    return api.post("/open/api/v1/resource/note/save", build_save_link_payload(url, title=title, tags=tags))


def wait_for_task(
    api: GetNoteAPI,
    task_id: str,
    interval: float,
    timeout: int,
    emit_events: bool = True,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_status = ""
    last_payload: dict[str, Any] = {}

    while time.monotonic() < deadline:
        payload = api.post("/open/api/v1/resource/note/task/progress", {"task_id": task_id})
        last_payload = payload
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        status = str(data.get("status") or "")
        if emit_events and status and status != last_status:
            print(json.dumps({"event": "task_status", "task_id": task_id, "status": status}, ensure_ascii=False))
            last_status = status
        if status == "success":
            return payload
        if status == "failed":
            raise RuntimeError(str(data.get("error_msg") or payload))
        time.sleep(interval)

    raise TimeoutError(f"Timed out waiting for GetNote task {task_id}")


def get_note_detail(api: GetNoteAPI, note_id: str) -> dict[str, Any]:
    return api.get("/open/api/v1/resource/note/detail", {"id": note_id})


def add_tags_to_note(api: GetNoteAPI, note_id: str, tags: list[str]) -> dict[str, Any]:
    if not tags:
        return {"success": True, "data": {"tags": []}}
    return api.post("/open/api/v1/resource/note/tags/add", {"note_id": note_id, "tags": tags})


def extract_task_id(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        task_id = data.get("task_id")
        if task_id:
            return str(task_id)
        tasks = data.get("tasks")
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict) and task.get("task_id"):
                    return str(task["task_id"])
    return ""


def extract_note(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("note"), dict):
        return data["note"]
    if isinstance(payload.get("note"), dict):
        return payload["note"]
    return {}


def extract_note_id(payload: dict[str, Any]) -> str:
    note = extract_note(payload)
    sources = [note, payload]
    data = payload.get("data")
    if isinstance(data, dict):
        sources.append(data)
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("note_id", "id"):
            value = source.get(key)
            if value:
                return str(value)
    return ""


def summarize_note_payload(payload: dict[str, Any]) -> dict[str, Any]:
    note = extract_note(payload)
    web_page = note.get("web_page") if isinstance(note.get("web_page"), dict) else {}
    audio = note.get("audio") if isinstance(note.get("audio"), dict) else {}
    tags = note.get("tags") if isinstance(note.get("tags"), list) else []
    tag_names = [str(tag.get("name")) for tag in tags if isinstance(tag, dict) and tag.get("name")]

    ai_summary = str(note.get("content") or "")
    web_content = str(note.get("web_content") or web_page.get("content") or audio.get("original") or "")
    source_url = str(web_page.get("url") or "")

    return {
        "note_id": str(note.get("note_id") or note.get("id") or extract_note_id(payload)),
        "title": note.get("title"),
        "note_type": note.get("note_type"),
        "source": note.get("source"),
        "url": source_url,
        "tag_names": tag_names,
        "ai_summary": ai_summary,
        "web_content": web_content,
        "content_chars": len(ai_summary),
        "web_content_chars": len(web_content),
        "content_preview": ai_summary[:500],
        "web_content_preview": web_content[:500],
    }


def run_single_workflow(
    api: GetNoteAPI,
    url: str,
    title: str,
    tags: list[str],
    task_interval: float,
    task_timeout: int,
    emit_events: bool = True,
    input_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "input": input_meta or {"input": "url", "url": url},
        "save_url": url,
        "save": {},
        "task": {},
        "tags": {},
        "note": {},
    }

    save_payload = save_link(api, url, title=title, tags=tags)
    result["save"] = save_payload

    task_id = extract_task_id(save_payload)
    if task_id:
        task_payload = wait_for_task(api, task_id, task_interval, task_timeout, emit_events=emit_events)
        result["task"] = task_payload
        note_id = extract_note_id(task_payload)
    else:
        note_id = extract_note_id(save_payload)

    if not note_id:
        raise RuntimeError("No note_id found after saving or polling.")

    result["tags"] = add_tags_to_note(api, note_id, tags)
    note_payload = get_note_detail(api, note_id)
    result["note"] = {
        "raw": note_payload,
        "summary": summarize_note_payload(note_payload),
    }
    return result


def run_url_list(args: argparse.Namespace, api: GetNoteAPI, tags: list[str]) -> int:
    urls = parse_url_list(Path(args.url_list).expanduser())
    if args.limit:
        urls = urls[: args.limit]

    output_dir = Path(args.output_dir).expanduser()
    manifest_path = Path(args.manifest).expanduser()
    completed = load_completed_urls(manifest_path) if args.resume else set()
    selected = [url for url in urls if url not in completed]

    print(
        json.dumps(
            {
                "event": "batch_start",
                "found": len(urls),
                "completed": len(completed),
                "selected": len(selected),
                "manifest": str(manifest_path),
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        )
    )

    failures = 0
    for index, url in enumerate(selected, start=1):
        print(json.dumps({"event": "item_start", "index": index, "total": len(selected), "url": url}, ensure_ascii=False))
        try:
            result = run_single_workflow(
                api,
                url,
                title="",
                tags=tags,
                task_interval=args.task_interval,
                task_timeout=args.task_timeout,
                emit_events=not args.json,
                input_meta={"input": "url_list", "url": url, "url_list": args.url_list},
            )
            record = write_url_outputs(index, url, result, output_dir, status="success")
        except Exception as exc:  # noqa: BLE001 - batch mode records failures and continues.
            failures += 1
            record = {"url": url, "status": "failed", "error": str(exc)}
        append_manifest_record(manifest_path, record)
        print(json.dumps({"event": "item_done", **record}, ensure_ascii=False))
    return 1 if failures else 0


def write_url_outputs(index: int, url: str, result: dict[str, Any], output_dir: Path, status: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_dir = output_dir / "json"
    markdown_dir = output_dir / "markdown"
    json_dir.mkdir(exist_ok=True)
    markdown_dir.mkdir(exist_ok=True)

    summary = result.get("note", {}).get("summary", {}) if isinstance(result.get("note"), dict) else {}
    title = str(summary.get("title") or url)
    note_id = str(summary.get("note_id") or "")
    tags = summary.get("tag_names") if isinstance(summary.get("tag_names"), list) else []
    ai_summary = str(summary.get("ai_summary") or "")
    web_content = str(summary.get("web_content") or "")
    stem = make_output_stem(index, url)

    json_path = json_dir / f"{stem}.json"
    markdown_path = markdown_dir / f"{stem}.md"
    raw = {"url": url, "status": status, "result": result}
    json_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    markdown = "\n".join(
        [
            f"# {title}",
            "",
            f"- source_url: {url}",
            f"- getnote_note_id: {note_id}",
            f"- note_type: {summary.get('note_type') or ''}",
            f"- source: {summary.get('source') or ''}",
            f"- tags: {', '.join(tags)}",
            "",
            "## AI 总结",
            "",
            ai_summary,
            "",
            "## 正文 / 转写全文",
            "",
            web_content,
            "",
        ]
    )
    markdown_path.write_text(markdown, encoding="utf-8")

    return {
        "url": url,
        "status": status,
        "note_id": note_id,
        "title": title,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "ai_summary_chars": len(ai_summary),
        "web_content_chars": len(web_content),
    }


def load_completed_urls(manifest_path: Path) -> set[str]:
    completed: set[str] = set()
    if not manifest_path.exists():
        return completed
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return completed
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("status") == "success" and record.get("url"):
            completed.add(str(record["url"]))
    return completed


def append_manifest_record(manifest_path: Path, record: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def make_output_stem(index: int, url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "url").lower()
    host = "".join(char if char.isalnum() else "-" for char in host).strip("-") or "url"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{index:04d}-{host}-{digest}"


def normalize_tags(tags: list[str], default_if_empty: bool) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        tag = tag.strip()
        if tag and tag not in seen:
            cleaned.append(tag)
            seen.add(tag)
    if not cleaned and default_if_empty:
        cleaned.append(DEFAULT_BATCH_TAG)
    return cleaned


def is_http_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="Single http/https URL to save.")
    input_group.add_argument("--url-list", help="Plain text file with one http/https URL per line.")
    parser.add_argument("--title", default="", help="Optional title for --url mode.")
    parser.add_argument("--tag", action="append", default=[], help="Tag to apply; repeatable.")
    parser.add_argument("--env-file", default=".env", help="File containing GETNOTE_API_KEY and GETNOTE_CLIENT_ID.")
    parser.add_argument("--api-base-url", default=os.environ.get("GETNOTE_API_URL", DEFAULT_API_BASE_URL))
    parser.add_argument("--request-timeout", type=int, default=60)
    parser.add_argument("--task-timeout", type=int, default=300)
    parser.add_argument("--task-interval", type=float, default=5)
    parser.add_argument("--limit", type=int, default=0, help="Maximum URLs to process in --url-list mode; 0 means no limit.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Batch JSONL manifest path.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Batch JSON/Markdown output directory.")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Do not skip successful URL records in manifest.")
    parser.set_defaults(resume=True)
    parser.add_argument("--json", action="store_true", help="Print only final JSON result in --url mode.")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        credentials = load_getnote_credentials(env_file=Path(args.env_file).expanduser())
        api = GetNoteAPI(credentials, base_url=args.api_base_url, timeout=args.request_timeout)
        tags = normalize_tags(args.tag, default_if_empty=bool(args.url_list))

        if args.url_list:
            return run_url_list(args, api, tags)

        result = run_single_workflow(
            api,
            args.url,
            title=args.title,
            tags=tags,
            task_interval=args.task_interval,
            task_timeout=args.task_timeout,
            emit_events=not args.json,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - command-line tool should report cleanly.
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
