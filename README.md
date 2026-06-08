# getnote-transcribe-skill

GetNote import/transcript skills. The repo keeps the old `$getnote-transcribe` entry as a thin router and splits real work into scene skills so public URLs, private originals, and local media imports do not trigger each other by accident.

## Skill Layout

- `skills/getnote-transcribe/`: compatibility router.
- `skills/getnote-url-import/`: public URL -> OpenAPI save -> summary/source export.
- `skills/getnote-note-original/`: existing `note_id` -> desktop login-state `/original` transcript.
- `skills/getnote-local-media/`: 本地音视频自动导入 -> OSS upload -> `local_audio` note -> `/original` transcript.
- `skills/_shared/`: shared desktop token, Bearer header, `/original` parsing, and transcript Markdown helpers.

The old script paths in `skills/getnote-transcribe/scripts/` remain as compatibility wrappers.

## Setup

URL import needs OpenAPI credentials:

```bash
GETNOTE_API_KEY=gk_live_xxx
GETNOTE_CLIENT_ID=cli_xxx
```

Private original and local media flows use the GetNote desktop login state from:

```text
~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb
```

or `GETNOTE_WEB_TOKEN` if explicitly provided. Never print tokens.

## Usage

Public URL:

```bash
python3 skills/getnote-url-import/scripts/getnote_url_workflow.py \
  --url https://www.iana.org/help/example-domains \
  --title "Example domains" \
  --tag GetNote转译 \
  --json
```

Batch URL list:

```bash
python3 skills/getnote-url-import/scripts/getnote_url_workflow.py \
  --url-list urls.txt \
  --tag GetNote转译 \
  --output-dir getnote_exports \
  --manifest getnote_manifest.jsonl
```

Existing note original:

```bash
python3 skills/getnote-note-original/scripts/getnote_desktop_original.py \
  1912003447071346264 \
  --output transcript.md \
  --raw-json original.json
```

Local media dry-run:

```bash
python3 skills/getnote-local-media/scripts/getnote_local_media_workflow.py \
  ./audio.mp3 \
  --dry-run
```

Local media import:

```bash
python3 skills/getnote-local-media/scripts/getnote_local_media_workflow.py \
  ./audio.mp3 \
  --output transcript.md \
  --raw-original-json original.json \
  --raw-sse-jsonl events.jsonl
```

## Boundaries

- Do not create public share links unless the user explicitly asks for public sharing.
- URL import uses OpenAPI only and must not read desktop tokens.
- Existing `note_id` original export must not call OpenAPI URL save.
- 本地音视频自动导入 is a script-backed workflow, not a product concept named "CLI upload".
- `--dry-run` checks local file, transcode plan, and token availability only; it must not request upload tokens, PUT OSS, or create notes.
- OpenAPI detail source text comes from `web_content`, `web_page.content`, or `audio.original`; `content` is the AI summary.
- Private `/original` stores transcript data as JSON in `c.content.sentence_list`.

## Verification

```bash
bash ./runtest.sh
bash .codex/hooks/run-tests.sh
python3 skills/getnote-url-import/scripts/getnote_url_workflow.py --help
python3 skills/getnote-note-original/scripts/getnote_desktop_original.py --help
python3 skills/getnote-local-media/scripts/getnote_local_media_workflow.py --help
```
