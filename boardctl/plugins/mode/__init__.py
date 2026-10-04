"""Boot-mode plugin interface: a module provides PLUGIN = a RunMode subclass
(the class declares NAME, matched by [run.*].mode).

  __init__(self, cfg)                     # board config
  launch(self, runner) -> (channel, cmdline, done)

runner is this target's orchestration object (board/cfg/name/t live in it).
cmdline=None means passive capture with zero writes (watch); done non-None
means launch concluded itself (e.g. uboot loads without executing ->
'loaded') and the runner skips streaming.

Division of labor: modes only interpret how a target gets brought up —
streaming, assertions, after-handling and repeat are held by the runner,
identical for every mode. Plugins must not import each other."""
import re
import sys
from abc import ABC, abstractmethod

import msgspec


def expand_cmd(name, cmd, vals):
    """Expand {var} from vals; an unknown variable errors by name (no silent
    {var} literal left behind)."""

    def _sub(m):
        k = m.group(1)
        if k not in vals or vals[k] is None:
            sys.exit(f'cmd of run.{name} uses {{{k}}}, but the target has no such key configured')
        return str(vals[k])

    return re.sub(r'\{(\w+)\}', _sub, cmd)


def target_vars(t):
    """RunTarget → cmd-template variable mapping: the target's own keys, None stripped."""
    return {k: v for k, v in msgspec.to_builtins(t).items() if v is not None}


class RunMode(ABC):
    """Boot-mode abstraction: how one [run.<name>] target gets brought up."""

    NAME = None            # registry name (subclasses must set), matches [run.*].mode

    @abstractmethod
    def launch(self, runner):
        """Validate + power on + transport; return (channel, cmdline, done)."""
