---
name: getnote-local-media
description: Use when importing a local audio/video file into GetNote and exporting the resulting private original transcript.
---

# GetNote Local Media

Use for 本地音视频自动导入. This flow converts local media to MP3, requests a GetNote upload token, PUTs the file to OSS, creates a `local_audio` note through `stream_on_local_audio`, waits for the resulting `note_id`, then exports `/original`.

Run from this skill directory:

```bash
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 --dry-run
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 --output transcript.md --raw-original-json original.json --raw-sse-jsonl events.jsonl
```

Supported interface: positional `media_path`, `--output`, `--raw-original-json`, `--raw-sse-jsonl`, `--title`, `--timeout`, `--dry-run`.

Boundaries:

- `--dry-run` only checks the local file, transcode plan, and desktop token availability; it must not request upload tokens, PUT OSS, or create notes.
- Requires the desktop login state, or `GETNOTE_WEB_TOKEN` if explicitly set.
- Do not call OpenAPI URL import for local files.
- Do not create public share links.
