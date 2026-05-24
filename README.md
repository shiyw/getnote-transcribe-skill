# getnote-transcribe-skill

API-only GetNote URL save/read/export skill. It saves URLs through GetNote OpenAPI, waits for processing, adds manual tags, reads note detail, and exports AI summary plus `web_page.content`.

## Codex Skill

The installable skill lives in `skills/getnote-transcribe/`. Invoke it as `$getnote-transcribe` when you want Codex to save URLs into GetNote and export summaries plus source content.

The workflow script is bundled inside the skill:

```bash
python3 skills/getnote-transcribe/scripts/getnote_url_workflow.py --help
```

## Setup

Create `.env` in this directory:

```bash
GETNOTE_API_KEY=gk_live_xxx
GETNOTE_CLIENT_ID=cli_xxx
```

The script does not require the `getnote` CLI. It only uses OpenAPI:

- `POST /open/api/v1/resource/note/save`
- `POST /open/api/v1/resource/note/task/progress`
- `POST /open/api/v1/resource/note/tags/add`
- `GET /open/api/v1/resource/note/detail?id=...`

## Usage

Single URL:

```bash
python3 skills/getnote-transcribe/scripts/getnote_url_workflow.py \
  --url https://www.iana.org/help/example-domains \
  --title "Example domains" \
  --tag GetNote转译 \
  --json
```

Batch URL list:

```bash
python3 skills/getnote-transcribe/scripts/getnote_url_workflow.py \
  --url-list urls.txt \
  --tag GetNote转译 \
  --output-dir getnote_exports \
  --manifest getnote_manifest.jsonl
```

`urls.txt` is plain text, one URL per line:

```text
# blank lines and comments are ignored
https://www.iana.org/help/example-domains
https://www.iana.org/domains/reserved
```

Batch mode writes:

- raw JSON: `getnote_exports/json/*.json`
- readable Markdown: `getnote_exports/markdown/*.md`
- resumable manifest: `getnote_manifest.jsonl`

If no `--tag` is provided in batch mode, the default tag is `GetNote转译`.

## Gotchas

- `/note/save` does not apply manual tags even if `tags` is included in the save payload. The script intentionally calls `/note/tags/add` after it has a `note_id`.
- `content` is the AI summary. The full source body is usually `web_page.content`; future `web_content` is also supported if the API starts returning it.
- GetNote may return QPS errors (`10202 qps_bucket_exceeded`). Wait and retry; the manifest lets batch mode resume successful URLs.
- `task/progress` can return `status: success` with a stale `error_msg`. The script trusts `status`, then confirms by reading note detail.
- Write-note quota is separate from read quota. Real E2E tests consume save quota; prefer using existing note IDs for read-only checks.

## Verification

```bash
python3 -m unittest test_getnote_workflow.py
python3 -m py_compile skills/getnote-transcribe/scripts/getnote_url_workflow.py test_getnote_workflow.py
```
