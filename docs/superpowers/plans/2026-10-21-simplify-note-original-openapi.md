# OpenAPI-based Note Original Transcript Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify `getnote-note-original` to retrieve note transcripts directly via OpenAPI (`https://openapi.biji.com`), eliminating the desktop LevelDB, plyvel, and private Web JWT dependencies for reading notes.

**Architecture:** Refactor `skills/getnote-note-original/scripts/getnote_desktop_original.py` to use `GET /open/api/v1/resource/note/detail` via standard library urllib and API credentials (`GETNOTE_API_KEY`, `GETNOTE_CLIENT_ID`). Format detailed transcripts with priority: `note.audio.sentences` (sentence timestamps & speakers) > `note.audio.original` (verbatim audio text) > `note.web_page.content` (verbatim media/link text) > `note.content` (fallback AI summary). Update skills metadata, router, README, and unit tests.

**Tech Stack:** Python 3 (standard library: `urllib.request`, `json`, `argparse`, `pathlib`), unittest.

## Global Constraints

- No external dependencies beyond standard library for `getnote-note-original` (no `plyvel`, no leveldb).
- Never read, write, or log secrets from `.env` directly in user output.
- All code comments and user-facing docs in Simplified Chinese.
- Follow Chinese copywriting guidelines (spaces between CJK and ASCII, full-width punctuation, 「」 quotes).
- All unit tests must pass via `./runtest.sh`.

## Review Focus

1. Notes with `audio.sentences`: Must output millisecond-accurate timestamps `[MM:SS - MM:SS]` and speaker names.
2. Notes with `audio.original` (long continuous speech without sentence breakdown): Must output full verbatim text.
3. Notes with `web_page.content` (livestreams/web links with embedded timestamps): Must output full verbatim text.
4. Notes with only `content`: Must fall back gracefully to content with an informative header.
5. Missing credentials or invalid note_id: Must fail fast with clear, actionable error messages.

---

### Task 1: Refactor `getnote_desktop_original.py` to use OpenAPI

**Files:**
- Modify: `skills/getnote-note-original/scripts/getnote_desktop_original.py`

- [x] Define `ApiCredentials`, `load_getnote_credentials`, and minimal `GetNoteAPI` client.
- [x] Implement `ms_to_timestamp(ms)` helper for formatting `[MM:SS]` or `[HH:MM:SS]`.
- [x] Implement `format_transcript_markdown(note)` prioritizing `audio.sentences` -> `audio.original` -> `web_page.content` -> `content`.
- [x] Wire CLI args: `note_id`, `--output`, `--raw-json`, `--env-file`, `--api-base-url`, `--timeout`.
- [x] Verify standalone execution on real notes (`1912003447071346264`, `1924686210618893336`, `1923292563524115424`).

### Task 2: Update Skill Definitions, Router, and README

**Files:**
- Modify: `skills/getnote-note-original/SKILL.md`
- Modify: `skills/getnote-note-original/agents/openai.yaml`
- Modify: `skills/getnote-transcribe/SKILL.md`
- Modify: `skills/getnote-transcribe/agents/openai.yaml`
- Modify: `README.md`

- [x] Update `skills/getnote-note-original/SKILL.md` to document OpenAPI authentication (`GETNOTE_API_KEY` + `GETNOTE_CLIENT_ID`).
- [x] Update `skills/getnote-transcribe/SKILL.md` decision matrix to reflect OpenAPI for existing notes.
- [x] Update agent definitions in `openai.yaml`.
- [x] Update `README.md` layout, prerequisites, and usage examples.

### Task 3: Update Unit Tests and Verify

**Files:**
- Modify: `test_getnote_workflow.py`
- Verify: `runtest.sh`

- [x] Update `test_getnote_workflow.py` to test OpenAPI credential loading, transcript formatting logic, and CLI execution.
- [x] Update skill router existence tests to check updated keywords.
- [x] Run `./runtest.sh` to ensure all tests pass and static compilation succeeds.
