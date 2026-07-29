#!/bin/bash
# Double-clickable launcher for the Perform hub (macOS).
#
#   ./run.command          plain HTTP on :8000 — pair with `cloudflared`
#   ./run.command --tls    HTTPS on :8443 with a self-signed cert, no internet
#
# Microphones need a secure origin, so one of those two is always required;
# a bare http:// LAN address will never be granted a microphone.

cd "$(dirname "$0")" || exit 1

VENV=".venv"
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment…"
  python3 -m venv "$VENV" || exit 1
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r requirements.txt || exit 1
fi

if [ "$1" = "--tls" ]; then
  shift
  exec "$VENV/bin/python" -m server.hub --tls --port 8443 "$@"
else
  exec "$VENV/bin/python" -m server.hub --port 8000 "$@"
fi
