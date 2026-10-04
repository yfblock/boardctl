"""watch boot mode: passive watching — the board does its own transport and
execution (bootcmd/on-board automatic scripts); boardctl writes nothing
the whole way: no commands sent, not even the Ctrl-C of a cold boot's
prompt-wait (it would interrupt the board's flow).

The capture stream is resident (the connection was established when Board
was constructed); noise is cleared before the quiet power-on — boot
output lands in the capture log in full from the very first byte."""
import sys

from . import RunMode


class WatchMode(RunMode):
    NAME = 'watch'

    def __init__(self, cfg):
        self.cfg = cfg

    def launch(self, runner):
        board, name, t = runner.board, runner.name, runner.t   # this runner's object data
        for k in ('file', 'cmd'):
            if getattr(t, k):
                sys.exit(f'run.{name} (mode=watch) is passive and rejects {k} '
                         '(the board does its own transport and execution)')
        if t.reset_before:
            print(f'[{name}] cold boot (quiet: power-off -> power-on, no serial writes)', flush=True)
            board.quiet_boot()   # noise clearing + power-on inside: the capture log starts at power-on
        print(f'[{name}] passive watching (mode=watch: no commands sent)', flush=True)
        return board.stream, None, None


PLUGIN = WatchMode
