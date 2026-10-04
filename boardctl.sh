#!/bin/sh
# boardctl launcher: usable from any directory, relative-path arguments unaffected
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$DIR/.venv/bin/python" -m boardctl "$@"
