"""boardctl — dev-board control toolkit (design inspired by ostool on crates.io)

One-way layering: cli → runner → board → {power, serial, stream, console} →
plugins (transport / power / mode families, auto-discovered by directory,
see plugins/__init__.py). Config shapes and defaults have a single source in
schema.py; board TOMLs live in ~/.config/boardctl (see config.py)."""

# Version source of truth; pyproject reads it dynamically via hatch
__version__ = '0.14.0'
