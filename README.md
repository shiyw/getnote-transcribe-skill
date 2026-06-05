# getnote-transcribe-skill

GetNote save/read/export skill. It saves public URLs through GetNote OpenAPI, waits for processing, adds manual tags, reads note detail, and exports AI summary plus source content. For local audio uploaded through the GetNote desktop app, it can export the private `/original` transcript using the desktop login state, without creating public share links.

## Codex Skill

The installable skill lives in `skills/getnote-transcribe/`. Invoke it as `$getnote-transcribe` when you want Codex to save URLs into GetNote and export summaries plus source content.

The public URL workflow script is bundled inside the skill:

```bash
python3 skills/getnote-transcribe/scripts/getnote_url_workflow.py --help
```

The private desktop original transcript exporter is also bundled:

```bash
python3 skills/getnote-transcribe/scripts/getnote_desktop_original.py --help
```

## Setup

Create `.env` in this directory:

```bash
GETNOTE_API_KEY=gk_live_xxx
GETNOTE_CLIENT_ID=cli_xxx
```

The URL workflow does not require the `getnote` CLI. It only uses OpenAPI:

- `POST /open/api/v1/resource/note/save`
- `POST /open/api/v1/resource/note/task/progress`
- `POST /open/api/v1/resource/note/tags/add`
- `GET /open/api/v1/resource/note/detail?id=...`

The desktop original workflow does not use OpenAPI credentials. It reads candidate JWTs from the local GetNote desktop LevelDB storage, or from `GETNOTE_WEB_TOKEN` if explicitly provided. Do not print these tokens.

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

Existing GetNote desktop note, such as `local_audio` uploaded through the app:

```bash
python3 skills/getnote-transcribe/scripts/getnote_desktop_original.py \
  1912003447071346264 \
  --output transcript.md \
  --raw-json original.json
```

This calls the private web endpoint:

```text
GET https://get-notes.luojilab.com/voicenotes/web/notes/{note_id}/original
```

The response stores the transcript as a JSON string in `c.content`; `sentence_list` is formatted into Markdown with timestamps and speaker labels.

## Gotchas

- `/note/save` does not apply manual tags even if `tags` is included in the save payload. The script intentionally calls `/note/tags/add` after it has a `note_id`.
- `content` is the AI summary. The full source body is usually `web_page.content`; future `web_content` is also supported if the API starts returning it.
- App-uploaded `local_audio` notes do not expose transcripts in normal note detail. In verified CLI output they only returned `content`, `created_at`, `id`, `note_id`, `note_type`, `tags`, `title`, and `updated_at`; `content` was the AI summary, not the verbatim transcript.
- For app-uploaded audio, use `getnote_desktop_original.py` and the desktop login state. Do not create or use public share URLs unless the user explicitly asks for that mode.
- The desktop token may expire. If every candidate token fails with login/auth errors, open GetNote desktop and let it refresh login state, or pass a fresh token through `GETNOTE_WEB_TOKEN`.
- GetNote may return QPS errors (`10202 qps_bucket_exceeded`). Wait and retry; the manifest lets batch mode resume successful URLs.
- `task/progress` can return `status: success` with a stale `error_msg`. The script trusts `status`, then confirms by reading note detail.
- Write-note quota is separate from read quota. Real E2E tests consume save quota; prefer using existing note IDs for read-only checks.

## Verification

```bash
python3 -m unittest test_getnote_workflow.py
python3 -m py_compile \
  skills/getnote-transcribe/scripts/getnote_url_workflow.py \
  skills/getnote-transcribe/scripts/getnote_desktop_original.py \
  test_getnote_workflow.py
```
