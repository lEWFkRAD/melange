#!/bin/sh
# Start the Melange service (bridge as a live service) on 127.0.0.1.
#   MELANGE_PORT       port to bind (default 8798)
#   MELANGE_STORES_FILE  registry JSON (default service/stores.json)
#   PYTHON             interpreter (default: the living-replay venv if
#                      present, else python3). The workbook clamp path
#                      needs openpyxl (the workbook profile); everything
#                      else is stdlib + living_replay.
set -e
cd "$(dirname "$0")/.."
if [ -z "$PYTHON" ]; then
  if [ -x "$HOME/workspace/living-replay/venv/bin/python" ]; then
    PYTHON="$HOME/workspace/living-replay/venv/bin/python"
  else
    PYTHON=python3
  fi
fi
export PYTHONPATH="src:service${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" service/melange_service.py
