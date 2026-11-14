#!/usr/bin/env bash
# Serve the Lydian launch page locally.
cd "$(dirname "$0")"
PORT="${1:-8000}"
echo "Lydian launch page -> http://localhost:$PORT"
python3 -m http.server "$PORT"
