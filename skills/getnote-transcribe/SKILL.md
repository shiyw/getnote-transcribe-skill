---
name: getnote-transcribe
description: Use when saving one or more public http/https URLs into GetNote via OpenAPI, including webpages, docs, Douyin/抖音, Xiaohongshu/小红书, Bilibili, YouTube, and podcast/audio pages such as 小宇宙; waits for processing, applies tags, and exports the AI summary plus source text/transcript.
---

# GetNote Transcribe

Use the bundled OpenAPI script. Do not switch to the GetNote CLI, browser client, share links, or scraper logic unless the user asks for that mode.

## Run

Run from the directory containing this `SKILL.md`:

```bash
python3 scripts/getnote_url_workflow.py --help
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

## Rules

- Only use public `http` or `https` URLs that GetNote can fetch. If GetNote rejects a URL, report the API error and URL.
- `/note/save` may not apply tags, so the script saves first, then calls `/note/tags/add` after it has a `note_id`.
- `content` is the AI summary. Source text/transcript comes from `web_content`, `web_page.content`, or `audio.original`.
- `task/progress` can return `status: success` with stale `error_msg`; trust `status`, then confirm via note detail.
- QPS errors such as `10202 qps_bucket_exceeded` mean wait and retry; batch resume skips successful manifest records.

## Verification

After editing the workflow or this skill, run:

```bash
python3 scripts/getnote_url_workflow.py --help
python3 -m py_compile scripts/getnote_url_workflow.py
```
