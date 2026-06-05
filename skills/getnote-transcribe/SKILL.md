---
name: getnote-transcribe
description: Use when saving public http/https URLs into GetNote, exporting GetNote summaries plus source text/transcripts, or retrieving transcripts from existing GetNote desktop local_audio notes without public sharing.
---

# GetNote Transcribe

Use the bundled scripts. For public URLs, use the OpenAPI workflow. For existing audio uploaded through the GetNote desktop app, use the private desktop original workflow. Do not create public share links unless the user explicitly asks for that mode.

## Run

Run from the directory containing this `SKILL.md`:

```bash
python3 scripts/getnote_url_workflow.py --help
python3 scripts/getnote_desktop_original.py --help
```

Credentials come from environment variables or `--env-file`; never print them:

```bash
GETNOTE_API_KEY=...
GETNOTE_CLIENT_ID=...
```

Single URL:

```bash
python3 scripts/getnote_url_workflow.py \
  --url "https://example.com/article" \
  --title "Optional title" \
  --tag "GetNote转译" \
  --json
```

Use `--tag` repeatedly when multiple manual tags are needed.

Batch URLs:

```bash
python3 scripts/getnote_url_workflow.py \
  --url-list urls.txt \
  --tag "GetNote转译" \
  --output-dir getnote_exports \
  --manifest getnote_manifest.jsonl
```

Batch input is one URL per line; blank lines and `#` comments are ignored. Batch output goes to `getnote_exports/json/`, `getnote_exports/markdown/`, and a resumable JSONL manifest. Use `--limit N` for quota-safe smoke tests.

Existing desktop note, such as audio uploaded through the GetNote app:

```bash
python3 scripts/getnote_desktop_original.py \
  1912003447071346264 \
  --output transcript.md \
  --raw-json original.json
```

This reads the desktop login state from:

```text
~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb
```

or uses `GETNOTE_WEB_TOKEN` if set. Never print tokens.

## Rules

- Only use public `http` or `https` URLs that GetNote can fetch. If GetNote rejects a URL, report the API error and URL.
- `/note/save` may not apply tags, so the script saves first, then calls `/note/tags/add` after it has a `note_id`.
- In OpenAPI URL detail, `content` is the AI summary. Source text/transcript comes from `web_content`, `web_page.content`, or `audio.original`.
- App-uploaded `local_audio` detail may not contain `web_content`, `web_page`, or `audio`. If normal detail only has summary fields, fetch the transcript through `GET /voicenotes/web/notes/{note_id}/original` with the desktop login state.
- The private original response stores transcript data as a JSON string in `c.content`; format `sentence_list` as timestamped transcript lines.
- Do not use public share URLs for private notes unless the user explicitly asks for public sharing.
- `task/progress` can return `status: success` with stale `error_msg`; trust `status`, then confirm via note detail.
- QPS errors such as `10202 qps_bucket_exceeded` mean wait and retry; batch resume skips successful manifest records.
- Expired desktop tokens can fail even when the note exists. Ask the user to open/sign in to GetNote desktop or provide `GETNOTE_WEB_TOKEN`; do not log token contents.

## Verification

After editing the workflow or this skill, run:

```bash
python3 scripts/getnote_url_workflow.py --help
python3 scripts/getnote_desktop_original.py --help
python3 -m py_compile scripts/getnote_url_workflow.py scripts/getnote_desktop_original.py
```
