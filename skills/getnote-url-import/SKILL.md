---
name: getnote-url-import
description: Use when saving public http/https URLs or URL lists into GetNote through OpenAPI and exporting summaries plus source text.
---

# GetNote URL Import

Use for public URL inputs only. This flow calls GetNote OpenAPI, waits for processing, applies tags after a `note_id` exists, and exports the AI summary plus original/source text.

Run from this skill directory:

```bash
python3 scripts/getnote_url_workflow.py --url "https://example.com/article" --tag "GetNote转译" --json
python3 scripts/getnote_url_workflow.py --url-list urls.txt --tag "GetNote转译" --output-dir getnote_exports --manifest getnote_manifest.jsonl
```

Supported interface: `--url`, `--url-list`, `--tag`, `--output-dir`, `--manifest`, `--json`.

Boundaries:

- Requires `GETNOTE_API_KEY` and `GETNOTE_CLIENT_ID` from env or `--env-file`.
- Do not use desktop login tokens in this flow.
- OpenAPI detail source text comes from `web_content`, `web_page.content`, or `audio.original`; `content` is the AI summary.
- Do not use this for existing private `note_id` transcripts or local media files.
