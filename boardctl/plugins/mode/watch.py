"""watch boot mode: passive — the board runs its own flow (bootcmd/on-board
scripts); boardctl writes nothing the whole way, not even the Ctrl-C of a
prompt wait (it would interrupt the board's flow). Noise is cleared before
the quiet power-on, so capture starts at the very first boot byte."""
import sys

from . import RunMode


class WatchMode(RunMode):
    NAME = 'watch'

    def __init__(self, cfg):
        self.cfg = cfg

    def launch(self, runner):
        board, name, t = runner.board, runner.name, runner.t
        for k in ('file', 'cmd'):
            if getattr(t, k):
                sys.exit(f'run.{name} (mode=watch) is passive and rejects {k} '
                         '(the board does its own transport and execution)')
        if t.reset_before:
            print(f'[{name}] cold boot (quiet: power-off -> power-on, no serial writes)', flush=True)
            board.quiet_boot()
        print(f'[{name}] passive watching (mode=watch: no commands sent)', flush=True)
        return board.stream, None, None


PLUGIN = WatchMode
