"""Boot-mode plugin interface conventions (plugins are classes):

Each plugin module must provide:
  PLUGIN: a RunMode subclass         # the plugin class (subclasses declare NAME themselves)

RunMode subclass conventions:
  __init__(self, cfg)                  # board config (global info, same source as runner.cfg)
  launch(self, runner) -> (channel, cmdline, done)
                                       # runner = the orchestration object for this
                                       # target (one board ↔ many runners;
                                       # board/cfg/name/t all live in it) —
                                       # the specific object IS the
                                       # corresponding runner's data;
                                       # validate target fields + power on /
                                       # transport per the mode;
                                       # return (the board's serial channel,
                                       # the command to send) for the
                                       # streaming engine;
                                       # cmdline=None means passive capture
                                       # with zero writes (watch);
                                       # done non-None means launch concluded
                                       # itself (e.g. uboot loads without
                                       # executing -> 'loaded'), the runner
                                       # skips streaming and returns directly

Division of labor: mode plugins only interpret "how this target gets
brought up" (power-on style/whether to transport/command shape); the
streaming engine/assertions/after-handling/repeat are held uniformly by
the runner — verdict and after-handling semantics are identical for every
mode; that invariant is guaranteed by shared code, not by each plugin's
diligence. The class attribute NAME corresponds to [run.*].mode. Available
domain dependencies: board (board domain) / serial / console. Plugins must
not import each other. Dropping a new .py file in this directory
auto-registers it.
"""
import re
import sys
from abc import ABC, abstractmethod

import msgspec


def expand_cmd(name, cmd, vals):
    """Expand a target's cmd template (the executed command is config data,
    not code): variables come from the vals mapping (flipped out of the
    target by target_vars; mode-level defaults like uboot's {addr}/{entry}
    are injected by each mode before the call); an unknown variable errors
    by name, no silent {var} literal left behind"""

    def _sub(m):
        k = m.group(1)
        if k not in vals or vals[k] is None:
            sys.exit(f'cmd of run.{name} uses {{{k}}}, but the target has no such key configured')
        return str(vals[k])

    return re.sub(r'\{(\w+)\}', _sub, cmd)


def target_vars(t):
    """Target (RunTarget) → cmd-template variable mapping: the target's own
    keys, None stripped. Absent means absent — None fields don't act as
    variables, equivalent to the old post-strip-None dict"""
    return {k: v for k, v in msgspec.to_builtins(t).items() if v is not None}


class RunMode(ABC):
    """Boot-mode abstraction: how one [run.<name>] target "gets brought up" —
    encapsulation = power-on style/transport-or-not/command shape hidden in
    the class; polymorphism = the runner picks a subclass via [run.*].mode,
    streaming/assertions/after-handling shared"""

    NAME = None            # registry name (subclasses must set), matches [run.*].mode

    @abstractmethod
    def launch(self, runner):
        """Validate + power on + transport; return (channel, cmdline, done)"""
