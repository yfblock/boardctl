"""Board config discovery + loading: $BOARDCTL_BOARDS → ~/.config/boardctl →
the bundled example (template fallback only). load_board: toml parse →
inject name → msgspec validation (shape and defaults in schema.py) → BoardCfg."""
import os
import sys
import tomllib
from pathlib import Path

import msgspec

from . import schema

# project root: run-target file paths and local command cwd resolve against it
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# example template shipped with the package, lowest priority
BUNDLED_BOARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boards')


def boards_dirs():
    """Board config directory search order (deduplicated, existing only)."""
    candidates = [
        os.environ.get('BOARDCTL_BOARDS'),
        str(Path.home() / '.config' / 'boardctl'),
        BUNDLED_BOARDS_DIR,
    ]
    seen, out = set(), []
    for d in candidates:
        if d:
            d = os.path.abspath(d)
            if d not in seen and os.path.isdir(d):
                seen.add(d)
                out.append(d)
    return out


def available_boards():
    """{name: path} over all dirs; on name collisions the first dir wins."""
    names = {}
    for d in boards_dirs():
        for p in sorted(Path(d).glob('*.toml')):
            names.setdefault(p.stem, str(p))
    return names


def load_board(name):
    boards = available_boards()
    if name not in boards:
        sys.exit(f"unknown board {name!r}, available: {' '.join(sorted(boards)) or '(no boards in the config dirs)'}")
    with open(boards[name], 'rb') as f:
        data = tomllib.load(f)
    data['name'] = name
    try:
        return msgspec.convert(data, schema.BoardCfg, strict=False)
    except msgspec.ValidationError as e:
        sys.exit(f'board {name} has an invalid config ({boards[name]}):\n{e}')
