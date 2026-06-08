---
name: getnote-transcribe
description: Use as the compatibility router when a GetNote transcript/import request may involve a public URL, existing note_id, or local audio/video file.
---

# GetNote Transcribe Router

This is a thin router. Pick exactly one scene skill before running commands:

- Public `http`/`https` URL or URL list: use `$getnote-url-import`.
- Existing GetNote `note_id`, "已有笔记", or private original transcript: use `$getnote-note-original`.
- Local `.mp3`, `.mp4`, `.m4a`, `.wav`, `.mov`, `.webm`, or similar media file: use `$getnote-local-media`, which follows the desktop PC audio upload -> ASR -> polish stream path.

Compatibility wrappers remain available from this directory:

```bash
python3 scripts/getnote_url_workflow.py --help
python3 scripts/getnote_desktop_original.py --help
```

Rules:

- Do not create public share links unless the user explicitly asks for public sharing.
- URL import must not read desktop tokens.
- Existing `note_id` transcript export must not call the OpenAPI URL save flow.
- 本地音视频自动导入 must support `--dry-run`; dry-run must not request upload tokens, PUT OSS, or create notes.
- Newer local audio notes may not support the older `/original` response; local media import must fall back to PC ASR output and report the `/original` error.
