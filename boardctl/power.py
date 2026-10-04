"""Power domain: pure power actions (on/off/status), never touches the
serial. Power is a facade wrapping the PowerDevice plugin picked by
[power].method, with unified error handling — callers (Board/cli/runner/mcp)
see only Power, never the plugin. The off→delay→on cadence orchestration
lives in the board domain; this domain only holds the cadence value."""
import sys


class Power:
    """A board's power: wraps one PowerDevice plugin instance with unified error handling."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.method = cfg.power.method
        from .plugins import POWER   # function-local: avoids an import cycle
        cls = POWER.get(self.method)
        if cls is None:
            sys.exit(f'unknown power plugin {self.method!r}, available: {" ".join(sorted(POWER)) or "(none)"}')
        self.device = cls(cfg)

    @property
    def desc(self):
        return f'plugin {self.method}'

    def on(self):
        try:
            self.device.on()
        except SystemExit:
            raise
        except Exception as e:
            sys.exit(f'power-on failed ({self.desc}): {e}')

    def off(self, check=True) -> bool:
        """Power off; check=False returns False on failure instead of exiting."""
        try:
            self.device.off()
            return True
        except SystemExit:
            raise
        except Exception as e:
            print(f'power-off failed ({self.desc}): {e}', file=sys.stderr)
            if check:
                sys.exit(1)
            return False

    @property
    def reset_delay(self):
        """Seconds between power-off and power-on (shared by cold boot/reboot/quiet power-on)."""
        return self.cfg.power.reset_delay

    def status(self):
        """Returns bool, or None when unparseable (e.g. the command plugin)."""
        try:
            val = self.device.status()
        except SystemExit:
            raise
        except Exception as e:
            sys.exit(f'power status query failed ({self.desc}): {e}')
        return None if val is None else bool(val)
