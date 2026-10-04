"""uboot boot mode (the default of [run.*].mode): cold boot -> transport
plugin stages the file -> cmd executes.

The concentration point of U-Boot-specific knowledge: the load-address
default chain (addr <- uboot.load_addr, entry <- addr), the {addr}/{entry}
template variables, waiting for the prompt after transport before
executing."""
import os
import sys

from ...config import BASE_DIR
from . import RunMode, expand_cmd, target_vars


def _expand(cfg, name, t):
    """uboot command expansion: the {addr}/{entry} default chain — addr <-
    uboot.load_addr, entry <- addr (target keys take precedence)"""
    vals = target_vars(t)
    vals.setdefault('addr', cfg.uboot.load_addr)
    vals.setdefault('entry', vals['addr'])
    return expand_cmd(name, t.cmd, vals)


class UbootMode(RunMode):
    NAME = 'uboot'

    def __init__(self, cfg):
        self.cfg = cfg

    def launch(self, runner):
        board, name, t = runner.board, runner.name, runner.t   # this runner's object data
        cmdline = _expand(self.cfg, name, t) if t.cmd else None

        if t.reset_before:
            print(f'[{name}] cold boot (power-off -> power-on -> wait for prompt)', flush=True)
            board.cold_boot()

        if t.file is None:
            sys.exit(f'run.{name} (mode=uboot) needs file configured; '
                     'to execute a command without transport use mode = "console", for passive watching use mode = "watch"')
        path = t.file
        if not os.path.isabs(path):
            path = os.path.join(BASE_DIR, path)
        if not os.path.isfile(path):
            sys.exit(f'file not found: {path} (built it first?)')
        addr = t.addr or self.cfg.uboot.load_addr   # load address (entry {entry} comes from the cmd template)
        method = t.method or 'tftp'
        from .. import TRANSPORT   # function-local import: the registry is filled by the plugins package __init__
        transport = TRANSPORT.get(method)
        if transport is None:
            sys.exit(f'unknown transport method {method!r}, available: {" ".join(sorted(TRANSPORT)) or "(none)"}')

        print(f'[{name}] transferring {t.file} ({method}) -> {addr}', flush=True)
        if not transport(self.cfg).send(board.stream, path, addr):
            sys.exit(1)

        if cmdline is None:
            print(f'[{name}] loaded to {addr} (no cmd configured, not executing)')
            return None, None, 'loaded'

        print(f'[{name}] executing: {cmdline}', flush=True)
        s = board.session()   # the same capture stream: transport and execution share it
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('timed out waiting for the U-Boot prompt')
        return s.stream, cmdline, None


PLUGIN = UbootMode
