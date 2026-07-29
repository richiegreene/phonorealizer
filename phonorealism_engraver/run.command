#!/bin/bash
# Double-clickable launcher for the Engraver (macOS).
#
# Local-only by default: this is a desk tool, not something performers join.

cd "$(dirname "$0")" || exit 1

VENV=".venv"
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment…"
  python3 -m venv "$VENV" || exit 1
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r requirements.txt || exit 1
fi

exec "$VENV/bin/python" -m server.app --port 8200 "$@"
