---
name: getnote-note-original
description: Use when the user already has a GetNote note_id and wants the private original transcript via the desktop login state.
---

# GetNote Note Original

Use for existing GetNote notes, especially app-uploaded `local_audio` notes whose normal OpenAPI/detail response does not contain the verbatim transcript.

## Run

Run from this skill directory:

```bash
python3 scripts/getnote_desktop_original.py 1912003447071346264 --output transcript.md --raw-json original.json
```

Supported interface: positional `note_id`, `--output`, `--raw-json`, `--desktop-storage-dir`, `--timeout`.

## Desktop auth

Same PC JWT path as `$getnote-local-media` (not OpenAPI API key):

| Item | Detail |
|------|--------|
| App | **得到大脑** (`/Applications/得到大脑.app`) |
| Storage | `~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb` |
| Override | `GETNOTE_WEB_TOKEN=<jwt>` |

If you see `HTTP 403` / `LoginRequired`, refresh or re-login as documented in `$getnote-local-media` (refresh API + optional `GETNOTE_WEB_TOKEN`). Opening the app alone may not refresh an expired access token.

## Boundaries

- Calls private `/voicenotes/web/notes/{note_id}/original`.
- Transcript is parsed from `c.content.sentence_list` and formatted as timestamped Markdown when available.
- Newer desktop/PC audio notes may not return the older web `/original` shape; report the error and fall back to whatever PC ASR / note content is available rather than treating the whole request as a hard product failure when a partial transcript exists.
- Do not create public share links, and do not call the OpenAPI URL save flow for an existing `note_id`.
