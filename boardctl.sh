#!/bin/sh
# boardctl 启动器:任意目录可用,相对路径参数不受影响
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$DIR/.venv/bin/python" -m boardctl "$@"
