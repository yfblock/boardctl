"""CLI entry: run (one-shot full flow) + ls + power + check, cyclopts
annotation-driven — the type IS the validation (repeat is int, power state
is a Literal; illegal arguments error at the parse layer). The global
-b/--board is received at the meta layer, which resolves the board config
once and injects it into subcommands declaring cfg (ls/check don't declare
it, so it isn't resolved)."""
import os
import signal
import sys
from typing import Annotated, Literal

import cyclopts
from cyclopts import Parameter
from cyclopts.help import DefaultFormatter, PanelSpec
from rich import box

from . import __version__, power
from .config import BUNDLED_BOARDS_DIR, available_boards, load_board
from .schema import BoardCfg
from .runner import do_run

# result_action='return_value': app.meta() returns instead of sys.exit(0) —
# keeps it embeddable (tests/programmatic calls); exit codes are owned by
# each command's own sys.exit and error paths.
# help_formatter: same rich two-column layout, panel frame = invisible box.SIMPLE
app = cyclopts.App(name='boardctl', version=__version__,
                   result_action='return_value',
                   help_formatter=DefaultFormatter(
                       panel_spec=PanelSpec(box=box.SIMPLE)))


class _Interrupted(BaseException):
    """Catchable interrupt translated from SIGTERM and friends"""


def _on_signal(signum, _frame):
    raise _Interrupted(f'signal {signum}')


def _board_name(raw):
    """Omitted -b: auto-select when exactly one user board exists (bundled example doesn't count)."""
    if raw is None:
        user_boards = {n: p for n, p in available_boards().items()
                       if not p.startswith(BUNDLED_BOARDS_DIR + os.sep)}
        if len(user_boards) == 1:
            return next(iter(user_boards))
        sys.exit('Specify a board with -b. Available: '
                 + (' '.join(sorted(user_boards)) or '(none; put a config in ~/.config/boardctl/ first)'))
    return raw


_NO_BOARDS = ('No board configs found. Put board TOMLs in ~/.config/boardctl/\n'
              '(the bundled example under boardctl/boards/ is a good template), or point $BOARDCTL_BOARDS at a directory')


@app.meta.default
def _launch(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    board: Annotated[str | None,
                     Parameter(name=['-b', '--board'],
                               help='board name (default: auto-selected when there is exactly one user board)')] = None,
):
    """Dev-board control tool: one-shot full flow (cold boot → transport →
    execute → assert → after-handling); boards and boot targets are configured
    in ~/.config/boardctl, with pluggable transport/power/boot-mode"""
    command, bound, ignored = app.parse_args(tokens)
    if 'cfg' in ignored:                 # resolve the board only for subcommands declaring cfg
        ignored['cfg'] = load_board(_board_name(board))
    command(*bound.args, **bound.kwargs, **ignored)


@app.command
def run(
    name: Annotated[str | None, Parameter(help='boot target name (omitted: list available targets)')] = None,
    repeat: Annotated[int, Parameter(name=['-r', '--repeat'],
                                     help='repeat count (>1: cold boot each round, PASS/FAIL summary at the end)')] = 1,
    *,
    cfg: Annotated[BoardCfg, Parameter(parse=False)],
):
    """One-shot full-flow boot (target configured in [run.<name>]; omit the target name to list available targets)"""
    if repeat < 1:   # int annotation guarantees the type; only the range is checked here
        sys.exit(f'--repeat/-r must be a positive integer, got: {repeat!r}')

    def ensure_off():
        print('\n[boardctl] interrupted, ensuring power-off...', file=sys.stderr, flush=True)
        p = power.Power(cfg)
        try:
            state = p.status()
        except SystemExit:
            state = None
        if state is False:
            return  # already off
        if not p.off(check=False):
            print('[boardctl] automatic power-off failed, please check the power state manually', file=sys.stderr)

    # hook installed after cfg is settled: exits during board-name resolution don't trigger cleanup
    old_term = signal.signal(signal.SIGTERM, _on_signal)
    try:
        do_run(cfg, name, repeat)
    except (KeyboardInterrupt, _Interrupted):
        ensure_off()
        sys.exit(130)
    except Exception:
        ensure_off()
        raise
    finally:
        signal.signal(signal.SIGTERM, old_term)


@app.command(name='power')
def power_ctl(
    state: Annotated[Literal['on', 'off', 'status'],
                     Parameter(help='on: power on / off: power off / status: query state')],
    *,
    cfg: Annotated[BoardCfg, Parameter(parse=False)],
):
    """Power control (via power plugins: mijia/command)"""
    p = power.Power(cfg)
    if state == 'status':
        val = p.status()
        if val is not None:
            print('on' if val else 'off')
    else:
        print(f'[{cfg.name}] power {"on" if state == "on" else "off"} ({p.desc})',
              flush=True)
        (p.on if state == 'on' else p.off)()


@app.command
def ls():
    """List dev boards"""
    boards = available_boards()
    if not boards:
        sys.exit(_NO_BOARDS)
    for name in sorted(boards):
        cfg = load_board(name)
        desc = f' — {cfg.description}' if cfg.description else ''
        print(f'{cfg.name}{desc}')


@app.command
def check(
    name: Annotated[str | None, Parameter(help='board name (omitted: validate all)')] = None,
):
    """Validate board config format (the shape declared in schema.py; no hardware touched); exit code 1 when any config is invalid"""
    boards = available_boards()
    if not boards:
        sys.exit(_NO_BOARDS)
    failed = 0
    for n in [name] if name is not None else sorted(boards):
        try:
            load_board(n)   # unknown-board/invalid-config checks live in load_board
            print(f'{n}: OK')
        except SystemExit as e:
            failed += 1
            print(e.code)
    if failed:
        sys.exit(1)


def main():
    app.meta(sys.argv[1:])
