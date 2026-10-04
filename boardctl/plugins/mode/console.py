"""console boot mode: no transport, execute cmd directly once powered on to
the prompt (Linux shell shape). No address semantics: {addr}/{entry} are
unavailable here (unconfigured means an error naming the variable),
variables come from the target's own keys."""
import sys

from . import RunMode, expand_cmd, target_vars


class ConsoleMode(RunMode):
    NAME = 'console'

    def __init__(self, cfg):
        self.cfg = cfg

    def launch(self, runner):
        board, name, t = runner.board, runner.name, runner.t
        for k in ('file', 'method', 'addr', 'entry'):
            if getattr(t, k):
                sys.exit(f'run.{name} (mode=console) rejects {k}: console mode only executes '
                         'commands, no transport/address semantics (to transfer a file use mode = "uboot")')
        if not t.cmd:
            sys.exit(f'run.{name} (mode=console) needs cmd configured (the command executed directly on the console)')
        cmdline = expand_cmd(name, t.cmd, target_vars(t))

        if t.reset_before:
            print(f'[{name}] cold boot (power-off -> power-on -> wait for prompt)', flush=True)
            board.cold_boot()

        print(f'[{name}] executing: {cmdline}', flush=True)
        return board.stream, cmdline, None   # cold_boot already confirmed the prompt


PLUGIN = ConsoleMode
