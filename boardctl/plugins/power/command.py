"""command power plugin (the default): runs the on_cmd/off_cmd/status_cmd
configured in [power], locally or remotely per the top-level ssh_host.
status_cmd may be omitted; arbitrary command output can't be parsed into a
bool → status returns None."""
import sys

from ...shell import run as run_shell
from . import PowerDevice


class CommandPower(PowerDevice):
    NAME = 'command'

    def __init__(self, cfg):
        self.cfg = cfg

    def _cmd(self, key):
        command = getattr(self.cfg.power, key)
        if not command:
            sys.exit(f'[power] missing {key} (the command power plugin needs on_cmd/off_cmd)')
        return command

    def on(self):
        run_shell(self.cfg, self._cmd('on_cmd'), check=True)

    def off(self):
        run_shell(self.cfg, self._cmd('off_cmd'), check=True)

    def status(self):
        status = self.cfg.power.status_cmd
        if status:
            run_shell(self.cfg, status, check=False)
        return None   # arbitrary output can't be reliably parsed into a bool


PLUGIN = CommandPower
