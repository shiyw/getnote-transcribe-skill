#!/usr/bin/env bash
# Copy monorepo source-of-truth helpers into each scene skill package.
# skill-manager / skills.sh install one skill directory at a time and do not
# include skills/_shared/, so consumers must ship getnote_common.py inside the skill.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/skills/_shared/getnote_common.py"

if [[ ! -f "$SRC" ]]; then
  echo "missing source: $SRC" >&2
  exit 1
fi

targets=(
  "$ROOT/skills/getnote-local-media/scripts/getnote_common.py"
  "$ROOT/skills/getnote-note-original/scripts/getnote_common.py"
)

for dest in "${targets[@]}"; do
  mkdir -p "$(dirname "$dest")"
  cp "$SRC" "$dest"
  echo "vendored -> $dest"
done
