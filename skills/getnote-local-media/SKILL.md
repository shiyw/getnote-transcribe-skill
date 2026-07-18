---
name: getnote-local-media
description: Use when importing a local audio/video file into GetNote through the desktop PC audio flow and exporting the ASR transcript.
---

# GetNote Local Media

Use for 本地音视频自动导入（本地 `.mp3` / `.mp4` 等）。**Official OpenAPI cannot upload audio** — `note/save` only allows `plain_text` / `img_text` / `link`. Do not use `$getnote-url-import` or `getnote save` for local media.

This flow converts local media to MP3, requests a signed PC upload token, PUTs the file to OSS, calls `/voicenotes/pc/v1/asr/file`, creates an audio note through `/voicenotes/pc/v1/notes/polish/stream`, then exports the PC ASR transcript. `/original` export is best-effort only because newer desktop audio notes may not return the older web original shape.

## Dependencies

- Shared helpers are **vendored** at `scripts/getnote_common.py` (same directory as the workflow). Skill installers only copy this skill folder, so do not depend on a monorepo `skills/_shared/` sibling.
- Prefer the workflow script that uploads with **curl** and `Content-Type: audio/mp3`. A urllib path that sends `audio/mpeg` will fail OSS with `SignatureDoesNotMatch`.

## Run

Run from this skill directory (or pass absolute script path):

```bash
# Optional: force-refresh access JWT when you already know LoginRequired will hit
python3 scripts/getnote_refresh_desktop_token.py --force --json

python3 scripts/getnote_local_media_workflow.py ./audio.mp3 --dry-run
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 \
  --timeout 14400 \
  --title "optional title" \
  --output transcript.md \
  --raw-asr-json asr.json \
  --raw-note-json note.json
```

Supported interface:

- Workflow: positional `media_path`, `--output`, `--raw-asr-json`, `--raw-note-json`, `--raw-original-json`, `--raw-sse-jsonl`, `--title`, `--timeout`, `--dry-run`
- Refresh helper: `--force`, `--export-env`, `--export-refresh`, `--json`, `--print-token` (off by default), `--desktop-storage-dir`

## Desktop auth (PC audio path)

This path uses **desktop PC JWT**, not the OpenAPI `getnote auth` API key.

| Item | Detail |
|------|--------|
| App name | macOS app is **得到大脑** (`/Applications/得到大脑.app`); Electron user-data still under `iget-biji-desktop` |
| Token storage | `~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb` |
| Access token | LocalStorage key `token` (JWT). Often ~30 minutes TTL (`exp - iat`) |
| Refresh token | LocalStorage key `refresh_token` (opaque). Longer TTL via `refresh_token_expire_at` |
| Override | `GETNOTE_WEB_TOKEN=<jwt>` if set **and still fresh** |
| Auto-refresh | Workflow calls `ensure_desktop_access_tokens()`: env → fresh desktop JWT → refresh API |

### When you see `HTTP 403` / `LoginRequired`

1. Confirm desktop app is installed and was logged in at least once (so `refresh_token` exists).
2. Opening 得到大脑 alone may **not** rewrite a fresh access JWT if the old one is merely expired.
3. **Preferred for agents: run the refresh helper** (uses plyvel + refresh API). Do **not** invent tokens.

```bash
# dependency (once): python3 -m pip install plyvel-ci
# Prefer plyvel-ci on macOS universal2; plain plyvel needs system leveldb headers.

python3 scripts/getnote_refresh_desktop_token.py --force --json \
  --export-env /tmp/getnote_web_token.env

# then either rely on auto-refresh inside the workflow, or:
set -a && source /tmp/getnote_web_token.env && set +a
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 --output transcript.md ...
```

Status output looks like `ok refreshed=true left_min=29.8` or JSON with `success` / `exp` / `left_min` only — **never print full tokens** unless you intentionally pass `--print-token`.

### How refresh works (do not shortcut)

| Step | Detail |
|------|--------|
| 1. Read LevelDB | Copy `Local Storage/leveldb` to a temp dir, drop `LOCK`, open with **plyvel** |
| 2. Key shape | Chromium key like `_file://\x00\x01refresh_token` → DOM key `refresh_token` |
| 3. Value shape | Leading `0x01` type byte, then UTF-8 string. Strip the first byte |
| 4. TTL check | Optional `refresh_token_expire_at` (unix seconds). If past → user must re-login |
| 5. API | `POST https://notes-api.biji.com/account/v2/web/user/auth/refresh` |
| 6. Headers | `Content-Type: application/json`, `User-Agent: iget-biji-desktop/2.1.0 GetNotePCAPP/2.1.0` |
| 7. Body | `{"refresh_token":"<opaque from step 3>"}` |
| 8. Success | `h.c == 0`; new access JWT at **`c.token.token`** |
| 9. Rotate | Response may include a new `refresh_token`; prefer it for the next refresh |
| 10. Use | Export `GETNOTE_WEB_TOKEN=<jwt>` or let `ensure_desktop_access_tokens()` return it |

Shared implementation lives in `scripts/getnote_common.py` (vendored; monorepo source of truth is `skills/_shared/getnote_common.py`):

- `load_desktop_localstorage_items` / `load_desktop_refresh_token`
- `refresh_desktop_access_token`
- `ensure_desktop_access_tokens` (used by local-media + note-original workflows)

Manual curl equivalent (only after you already have the **correct** refresh_token string from plyvel — not from regex over raw `.ldb` bytes):

```bash
curl -sS -X POST 'https://notes-api.biji.com/account/v2/web/user/auth/refresh' \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: iget-biji-desktop/2.1.0 GetNotePCAPP/2.1.0' \
  -d '{"refresh_token":"<from plyvel LocalStorage refresh_token>"}'
# Response: c.token.token is the new JWT → GETNOTE_WEB_TOKEN
```

### Critical pitfalls

- **Do not regex-scrape raw `.ldb` / `.log` files** for `refresh_token`. LevelDB block compression corrupts runs of identical characters (e.g. a prefix of many `A`s becomes binary garbage). Tokens reconstructed that way often get `20124 刷新Token已过期` even when the real refresh_token is still valid for days.
- `load_desktop_tokens()` (JWT scrape from file bytes) is fine for the short-lived **access** JWT already written as text; it is **not** a substitute for reading `refresh_token` via plyvel.
- If refresh returns `20124` / `刷新Token已过期` **after** a correct plyvel read, the refresh_token is truly dead → user must re-login in 得到大脑.
- Access JWT ~30m TTL. For **multi-file** batches longer than ~20–30 minutes, re-check `exp` (or run the refresh helper) **between** files; mid-batch `LoginRequired` during long polish streams is expected if the process held one JWT for too long.

## Runtime expectations (do not misread as hang)

| Stage | Typical behavior |
|-------|------------------|
| Transcode | Local ffmpeg → 16 kHz mono 64 kbps MP3 in a temp dir |
| Upload token | Fast GET to PC API |
| OSS PUT | Seconds to tens of seconds; this is the only phase with bulk upload traffic |
| ASR `/asr/file` | Client blocks on HTTPS with **no upload traffic**; multi-hour audio often finishes in a few minutes but can take longer |
| Polish stream | Often the slowest stage (many minutes, thousands of SSE events for long lectures) |
| `/original` | Best-effort; failure is OK if PC ASR markdown was written |

- Default `--timeout` is **300s** — too short for long lectures during polish. Use something like `7200`–`14400` for multi-hour media.
- Process sample showing SSL `poll` / no children after OSS PUT usually means **waiting on ASR or polish**, not a dead process.
- Log stage transitions (transcode / upload / OSS / ASR / note) for multi-hour jobs so silent waits are observable.

## OSS upload pitfalls

- Signed upload expects **`Content-Type: audio/mp3`** (see `put_content_type` on the upload-token response). `audio/mpeg` causes `SignatureDoesNotMatch`.
- When `put_md5` is empty, do not invent a Content-MD5 header that disagrees with the signed string; the maintained curl PUT path matches production desktop behavior.
- Use the content type from the upload-token response when present.

## Boundaries

- `--dry-run` only checks the local file, transcode plan, and desktop token availability; it must not request upload tokens, PUT OSS, or create notes.
- Requires the desktop login state, or `GETNOTE_WEB_TOKEN` if explicitly set.
- Do not call OpenAPI URL import for local files.
- Do not create public share links.
- `--raw-note-json` redacts signed media URL query strings before writing.
- `--raw-sse-jsonl` is optional debug output; final note events redact signed media URL query strings before writing.
- If `/original` fails, report the error and keep the PC ASR transcript as the output instead of treating the import as failed.
