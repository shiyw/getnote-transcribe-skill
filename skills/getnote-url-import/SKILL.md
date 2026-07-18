---
name: getnote-url-import
description: Use when saving public http/https URLs or URL lists into GetNote through OpenAPI and exporting summaries plus source text.
---

# GetNote URL Import

Use for **public URL inputs only**. This flow calls GetNote OpenAPI, waits for processing, applies tags after a `note_id` exists, and exports the AI summary plus original/source text.

## Run

Run from this skill directory:

```bash
python3 scripts/getnote_url_workflow.py --url "https://example.com/article" --tag "GetNote转译" --json
python3 scripts/getnote_url_workflow.py --url-list urls.txt --tag "GetNote转译" --output-dir getnote_exports --manifest getnote_manifest.jsonl
```

Supported interface: `--url`, `--url-list`, `--tag`, `--output-dir`, `--manifest`, `--json`.

## OpenAPI create capabilities (verified)

`POST https://openapi.biji.com/open/api/v1/resource/note/save` supported `note_type` values:

| `note_type` | Required fields | Notes |
|-------------|-----------------|--------|
| `plain_text` | `content` | Text note |
| `img_text` | `image_urls` | Image note; not audio |
| `link` | `link_url` | Async task; poll `/open/api/v1/resource/note/task/progress` |

**Not supported for create via OpenAPI:**

- `audio`, `local_audio`, `meeting`, or any local file upload endpoint under `openapi.biji.com`
- Paths such as `/resource/audio/upload`, `/resource/media/upload`, `/resource/file/upload` return 404

CLI equivalent: `getnote save <url|text|image_path>` — same three modalities only.

For local mp3/mp4 import + ASR, use `$getnote-local-media` (desktop PC JWT path), not this skill.

## Boundaries

- Requires `GETNOTE_API_KEY` and `GETNOTE_CLIENT_ID` from env or `--env-file`.
- Do not use desktop login tokens in this flow.
- OpenAPI **can read** existing audio notes' summary fields; detail source text may come from `web_content`, `web_page.content`, or `audio.original`. Field `content` is typically the AI summary.
- Do not use this for existing private `note_id` transcripts or local media files.
- Do not create public share links unless the user explicitly asks.
