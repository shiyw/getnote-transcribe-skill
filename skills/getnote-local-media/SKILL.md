---
name: getnote-local-media
description: Use when importing a local audio/video file into GetNote through the desktop PC audio flow and exporting the ASR transcript.
---

# GetNote Local Media

Use for 本地音视频自动导入（本地 `.mp3` / `.mp4` 等）。**Official OpenAPI cannot upload audio** — `note/save` only allows `plain_text` / `img_text` / `link`. Do not use `$getnote-url-import` or `getnote save` for local media.

This flow converts local media to MP3, requests a signed PC upload token, PUTs the file to OSS, calls `/voicenotes/pc/v1/asr/file`, creates an audio note through `/voicenotes/pc/v1/notes/polish/stream`, then exports the PC ASR transcript. `/original` export is best-effort only because newer desktop audio notes may not return the older web original shape.

## Dependencies

- Script imports `getnote_common` from sibling `_shared/` (`skills/_shared/getnote_common.py`).
- If this workspace only installed scene skills without `_shared`, set  
  `PYTHONPATH` to a tree that contains `getnote_common.py` (for example the full getnote-transcribe-skill checkout), or symlink/copy `_shared` next to the scene skills.
- Prefer the workflow script that uploads with **curl** and `Content-Type: audio/mp3`. A urllib path that sends `audio/mpeg` will fail OSS with `SignatureDoesNotMatch`.

## Run

Run from this skill directory (or pass absolute script path):

```bash
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 --dry-run
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 \
  --timeout 14400 \
  --title "optional title" \
  --output transcript.md \
  --raw-asr-json asr.json \
  --raw-note-json note.json
```

Supported interface: positional `media_path`, `--output`, `--raw-asr-json`, `--raw-note-json`, `--raw-original-json`, `--raw-sse-jsonl`, `--title`, `--timeout`, `--dry-run`.

## Desktop auth (PC audio path)

This path uses **desktop PC JWT**, not the OpenAPI `getnote auth` API key.

| Item | Detail |
|------|--------|
| App name | macOS app is **得到大脑** (`/Applications/得到大脑.app`); Electron user-data still under `iget-biji-desktop` |
| Token storage | `~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb` |
| Access token | LocalStorage key `token` (JWT). Often ~30 minutes TTL (`exp - iat`) |
| Refresh token | LocalStorage key `refresh_token` (opaque). Longer TTL via `refresh_token_expire_at` |
| Override | `GETNOTE_WEB_TOKEN=<jwt>` skips desktop storage for that process |

### When you see `HTTP 403` / `LoginRequired`

1. Confirm desktop app is installed and previously logged in.
2. Opening 得到大脑 alone may **not** rewrite a fresh access token if the old JWT is merely expired.
3. Refresh via API (preferred for agents), then export `GETNOTE_WEB_TOKEN`:

```bash
# refresh_token is the latin1 string stored under LocalStorage key refresh_token
# (Chromium value has a leading 0x01 type byte; strip it. Do not invent the token.)
curl -sS -X POST 'https://notes-api.biji.com/account/v2/web/user/auth/refresh' \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: iget-biji-desktop/2.1.0 GetNotePCAPP/2.1.0' \
  -d '{"refresh_token":"<from leveldb refresh_token>"}'
# Response: c.token.token is the new JWT → GETNOTE_WEB_TOKEN
```

4. If refresh returns `20124` / 刷新Token已过期, user must re-login in 得到大脑.
5. For **multi-file** batches longer than ~20–30 minutes, re-check JWT `exp` (or refresh) **between** files; mid-batch `LoginRequired` is expected after long polish streams.

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
