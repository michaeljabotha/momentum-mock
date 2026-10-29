#!/usr/bin/env bash
# Seed (if needed) and serve the mock partner API on :9808.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m app.seed
exec .venv/bin/uvicorn app.main:app --reload --port 9808
