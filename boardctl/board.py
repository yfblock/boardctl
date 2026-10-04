"""Dev-board domain: one board = serial channel + resident capture stream +
power + console (composition, mirroring the config's [serial]/[power]/
[console] sections). Holds the "power on into an interactive state" flows
(cold boot / quiet power-on) and the console-session factory. The display
(tap) lifecycle belongs here: attach before power-on, detach before
power-off; programmatic callers can swap the sink (set_display).
Dependency direction: board → {power, serial, stream, console}; never reversed."""
import sys
import time

from .console import Console
from .power import Power
from .serial import SerialChannel
from .stream import ConsoleStream


class Board:
    """One board = serial + resident capture stream + power + console;
    context manager: enter starts the capture thread, exit stops it and
    closes the serial."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg.name
        self.serial = SerialChannel.from_cfg(cfg)   # one board ↔ one serial channel
        self.stream = ConsoleStream(self.serial)    # read side owned by the capture thread
        self.power = Power(cfg)
        self.console = Console.from_cfg(cfg)
        self._display = None    # programmatic display sink (run_collect); None = live stdout

    def __enter__(self):
        self.stream.start()
        return self

    def __exit__(self, *exc):
        self.stream.stop()
        self.serial.close()

    @property
    def prompt(self):
        return self.console.prompt

    def session(self):
        """Open a console session on the board's resident capture stream (borrowed, not owned)."""
        return self.console.session(self.stream)

    # ---- display (tap): hooked on capture events, shown as captured ----
    def set_display(self, out):
        """Programmatic sink swap (run_collect/MCP): a service process's
        stdout is a protocol channel — device bytes must not land on it."""
        self._display = out

    def _show(self, text):
        out = self._display if self._display is not None else sys.stdout
        out.write(text)
        out.flush()

    def _power_cycle(self, note=None):
        """Power off -> delay -> power on; note = the notice line printed
        before power-on.

        Ordering discipline: notice printed → tap attached → power on — SPL
        bytes come out the instant power applies, so the notice can't be
        torn into the byte stream. Tap detaches before power-off: line noise
        in the power-off window stays off screen."""
        self.stream.set_tap(None)
        print('powering off...', flush=True)
        self.power.off()
        time.sleep(self.power.reset_delay)
        print('powering on...', flush=True)
        if note:
            print(note, flush=True)
        self.stream.set_tap(self._show)   # power-on bytes display live from here
        self.power.on()

    def cold_boot(self, boot_timeout=60):
        """Power off → on → poll for the prompt (back to a clean interactive
        state from any state). Periodically sends Ctrl-C to clear leftover
        input — not usable for passive watching."""
        self._power_cycle(note='waiting for console prompt...')
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            if self.console.interactive_ready(self.session(), timeout=6):
                return
            time.sleep(2)
        sys.exit(f'console prompt not seen within {boot_timeout}s of power-on')

    def quiet_boot(self):
        """Quiet power-on (mode=watch): off → delay → drain + clear → on,
        zero serial writes — any write would interrupt the board's own flow.
        Capture and display both start at power-on."""
        self.stream.set_tap(None)   # power-off window (incl. last round's leftovers) stays off screen
        print('powering off...', flush=True)
        self.power.off()
        time.sleep(self.power.reset_delay)
        self.serial.drain()     # power-off noise still in the kernel receive buffer
        self.stream.clear()     # capture log and decoder residue: observation starts at power-on
        print('powering on (quiet, no serial writes)...', flush=True)
        self.stream.set_tap(self._show)
        self.power.on()

    def reboot(self):
        """Power-cycle back, without waiting for the prompt (after=reset finish)."""
        self._power_cycle()

    def power_off(self):
        """Detach the display (flushing backlog first), then cut power."""
        self.stream.set_tap(None)
        self.power.off()
