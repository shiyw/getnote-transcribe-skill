---
name: getnote-note-original
description: Use when the user already has a GetNote note_id and wants the private original transcript via the desktop login state.
---

# GetNote Note Original

Use for existing GetNote notes, especially app-uploaded `local_audio` notes whose normal detail does not contain the verbatim transcript.

Run from this skill directory:

```bash
python3 scripts/getnote_desktop_original.py 1912003447071346264 --output transcript.md --raw-json original.json
```

Supported interface: positional `note_id`, `--output`, `--raw-json`, `--desktop-storage-dir`, `--timeout`.

Boundaries:

- Uses the desktop login state from `~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb`, or `GETNOTE_WEB_TOKEN` if explicitly set.
- Calls private `/voicenotes/web/notes/{note_id}/original`.
- The transcript is parsed from `c.content.sentence_list` and formatted as timestamped Markdown.
- Do not create public share links, and do not call the OpenAPI URL save flow for an existing `note_id`.

