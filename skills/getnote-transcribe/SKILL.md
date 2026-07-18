---
name: getnote-transcribe
description: Use as the compatibility router when a GetNote transcript/import request may involve a public URL, existing note_id, or local audio/video file.
---

# GetNote Transcribe Router

This is a thin router. Pick **exactly one** scene skill before running commands.

## Decision matrix

| Input | Skill | Auth |
|-------|--------|------|
| Public `http`/`https` URL or URL list | `$getnote-url-import` | OpenAPI (`GETNOTE_API_KEY` + `GETNOTE_CLIENT_ID`) |
| Existing GetNote `note_id` / 已有笔记 / 私有原文转写 | `$getnote-note-original` | Desktop PC JWT (得到大脑) or `GETNOTE_WEB_TOKEN` |
| Local `.mp3`, `.mp4`, `.m4a`, `.wav`, `.mov`, `.webm`, or similar | `$getnote-local-media` | Desktop PC JWT (得到大脑) or `GETNOTE_WEB_TOKEN` |

Compatibility wrappers remain available from this directory:

```bash
python3 scripts/getnote_url_workflow.py --help
python3 scripts/getnote_desktop_original.py --help
```

## Rules

- Do not create public share links unless the user explicitly asks for public sharing.
- URL import must not read desktop tokens.
- Existing `note_id` transcript export must not call the OpenAPI URL save flow.
- 本地音视频自动导入 must support `--dry-run`; dry-run must not request upload tokens, PUT OSS, or create notes.
- Newer local audio notes may not support the older `/original` response; local media import must fall back to PC ASR output and report the `/original` error.

## OpenAPI cannot upload audio

Official OpenAPI `POST /open/api/v1/resource/note/save` accepts only:

- `plain_text`
- `img_text` (requires `image_urls`)
- `link` (requires `link_url`)

`audio` / `local_audio` / `meeting` return `invalid note_type`. CLI `getnote save` only accepts URL / text / image — **not** local mp3/mp4.

For local media import + ASR, always use `$getnote-local-media` (desktop PC path). Do not try OpenAPI or `getnote save` for audio files.

## Local-media notes (details in `$getnote-local-media`)

- Desktop app product name is **得到大脑**; PC JWT lives under `iget-biji-desktop` Local Storage. This is **not** OpenAPI `getnote auth` API-key auth.
- Long imports: raise `--timeout` (e.g. 7200–14400). After OSS PUT, silent HTTPS wait is usually ASR/polish, not a hang.
- Multi-file batches: access JWT ~30m TTL. Use `$getnote-local-media` refresh helper (or rely on `ensure_desktop_access_tokens` auto-refresh) between long jobs if you see `LoginRequired`. **Do not regex-scrape raw leveldb files for `refresh_token`** — use plyvel (see local-media skill).
- Scene skills vendor `scripts/getnote_common.py` inside each package (skill installers do not ship monorepo `_shared/`). OSS upload must use `Content-Type: audio/mp3` + curl PUT (not `audio/mpeg`).
