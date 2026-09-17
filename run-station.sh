#!/bin/sh
set -eu
cd "$(dirname "$0")"
PYTHON_BIN="${TXRX_PYTHON:-.venv/bin/python}"
"$PYTHON_BIN" scripts/doctor.py
exec "$PYTHON_BIN" -m station --port "${TXRX_PORT:-8000}"
