---
name: getnote-local-media
description: Use when importing a local audio/video file into GetNote through the desktop PC audio flow and exporting the ASR transcript.
---

# GetNote Local Media

Use for 本地音视频自动导入. This flow converts local media to MP3, requests a signed PC upload token, PUTs the file to OSS, calls `/voicenotes/pc/v1/asr/file`, creates an audio note through `/voicenotes/pc/v1/notes/polish/stream`, then exports the PC ASR transcript. `/original` export is best-effort only because newer desktop audio notes may not return the older web original shape.

Run from this skill directory:

```bash
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 --dry-run
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 --output transcript.md --raw-asr-json asr.json --raw-note-json note.json --raw-sse-jsonl events.jsonl
```

Supported interface: positional `media_path`, `--output`, `--raw-asr-json`, `--raw-note-json`, `--raw-original-json`, `--raw-sse-jsonl`, `--title`, `--timeout`, `--dry-run`.

Boundaries:

- `--dry-run` only checks the local file, transcode plan, and desktop token availability; it must not request upload tokens, PUT OSS, or create notes.
- Requires the desktop login state, or `GETNOTE_WEB_TOKEN` if explicitly set.
- Do not call OpenAPI URL import for local files.
- Do not create public share links.
- `--raw-note-json` redacts signed media URL query strings before writing.
- If `/original` fails, report the error and keep the PC ASR transcript as the output instead of treating the import as failed.
