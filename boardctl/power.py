"""Power domain: pure power actions (on/off/status), never touches the
serial — "power on into an interactive state" (cold boot waiting for the
prompt / quiet power-on) is the board domain's business in board.py, which
composes this domain with the serial domain; the off→delay→on cadence
orchestration also lives in the board domain (the display tap must attach
before power-on); this domain only holds the cadence value (reset_delay).
Power is this domain's object-oriented abstraction: it wraps the
PowerDevice plugin instance selected via [power].method with unified error
handling — plugin-layer polymorphism = different subclasses, one interface;
domain-facade polymorphism = callers (Board/cli/runner/mcp) see only Power,
never the plugin.
"""
import sys


class Power:
    """A board's power: wraps one PowerDevice plugin instance with unified
    error handling and subcommand semantics"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.method = cfg.power.method   # defaults to command (declared in schema)
        from .plugins import POWER   # function-local import: avoids a board→power→plugins→plugin→board cycle
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
        """Power off; with check=False a failure doesn't exit the process, it returns False instead"""
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
        """Seconds between power-off and power-on (the cadence value shared
        by cold boot/reboot/quiet power-on; the off→delay→on cadence
        orchestration is in the board domain, board.py)"""
        return self.cfg.power.reset_delay

    def status(self):
        """Query the state; returns bool, or None when unparseable (e.g. the command plugin)"""
        try:
            val = self.device.status()
        except SystemExit:
            raise
        except Exception as e:
            sys.exit(f'power status query failed ({self.desc}): {e}')
        return None if val is None else bool(val)
