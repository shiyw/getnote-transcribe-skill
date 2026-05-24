# getnote-transcribe-skill

API-only GetNote URL save/read/export workflow.

## Setup

Create `.env`:

```bash
GETNOTE_API_KEY=gk_live_xxx
GETNOTE_CLIENT_ID=cli_xxx
```

## Usage

Single URL:

```bash
python3 getnote_url_workflow.py --url https://example.com --tag GetNote转译
```

Batch URL list:

```bash
python3 getnote_url_workflow.py --url-list urls.txt --tag GetNote转译
```

`urls.txt` is plain text, one URL per line. Blank lines and `#` comments are ignored. Batch mode writes JSON and Markdown under `getnote_exports/`, and records progress in `getnote_manifest.jsonl`.
