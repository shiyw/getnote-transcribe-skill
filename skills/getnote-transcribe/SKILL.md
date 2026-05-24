---
name: getnote-transcribe
description: Use when saving public URLs into GetNote via OpenAPI, waiting for processing, adding tags, and exporting AI summaries plus source body/transcript. Supports public http/https URLs that GetNote can fetch, including normal webpages/articles/docs/blogs, Douyin/抖音, Xiaohongshu/小红书, Bilibili, YouTube, podcast/audio pages such as 小宇宙, and other generic URL sources.
---

# GetNote Transcribe

## Overview

Use the bundled script to save URLs into GetNote through OpenAPI only, wait for GetNote processing, apply manual tags, read note detail, and export AI summary plus the original web body or transcript.

Do not rely on the GetNote CLI, browser client, share links, or client-only APIs unless the user explicitly asks for that mode.

## Command

Run from the directory containing this `SKILL.md`:

```bash
python3 scripts/getnote_url_workflow.py --help
```

Credentials are read from environment variables or from `--env-file`:

```bash
GETNOTE_API_KEY=...
GETNOTE_CLIENT_ID=...
```

Never print secrets from env vars or `.env` files.

## Single URL

```bash
python3 scripts/getnote_url_workflow.py \
  --url "https://example.com/article" \
  --title "Optional title" \
  --tag "GetNote转译" \
  --json
```

Use `--tag` repeatedly when multiple manual tags are needed.

## Batch URLs

Create a plain text URL list, one URL per line. Blank lines and `#` comments are ignored.

```bash
python3 scripts/getnote_url_workflow.py \
  --url-list urls.txt \
  --tag "GetNote转译" \
  --output-dir getnote_exports \
  --manifest getnote_manifest.jsonl
```

Batch mode writes raw JSON under `getnote_exports/json/`, readable Markdown under `getnote_exports/markdown/`, and a resumable JSONL manifest at `getnote_manifest.jsonl`.

Use `--limit N` to conserve save quota while testing.

## Supported Sources

GetNote's backend decides exact fetchability. Use this skill for public `http` and `https` URLs, including:

- Ordinary webpages, articles, docs, blog posts, and newsletters.
- Short-video and social links such as Douyin/抖音 and Xiaohongshu/小红书.
- Video pages such as Bilibili and YouTube.
- Podcast or audio pages such as 小宇宙 episode/show links.
- Other generic public URLs that GetNote can save as link notes.

If GetNote rejects or cannot fetch a URL, report the API error and the URL. Do not replace this workflow with scraper logic unless the user asks for a scraper.

## Gotchas

- `/note/save` does not reliably apply manual tags. The script saves first, then calls `/note/tags/add` after a `note_id` exists.
- `content` is the AI summary. The source body/transcript is usually `web_page.content`; `web_content` is also supported if the API returns it.
- `/note/task/progress` may return `status: success` with a stale `error_msg`; trust `status`, then confirm through note detail.
- QPS errors such as `10202 qps_bucket_exceeded` mean wait and retry. The manifest lets batch mode resume successful URLs.
- Real saves consume write quota. Prefer `--limit` for smoke tests.

## Verification

After editing the workflow or this skill, run:

```bash
python3 scripts/getnote_url_workflow.py --help
python3 -m py_compile scripts/getnote_url_workflow.py
```
