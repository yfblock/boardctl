"""Dev-board domain: one concrete board. Maps to the [serial]/[power]/[console]
sections in a config file — a board bundles a piece of serial channel, one
resident capture stream, one power object and one console object (composition,
mirroring the config structure; what console payload it is comes from
[console].prompt: U-Boot, Linux shell, other CLIs), and carries the
"power on into an interactive state" flows (cold boot waiting for the prompt /
quiet power-on) plus the console-session factory.

Sessions and transport plugins both work on the board's capture stream
(borrowed); a whole run uses one connection: the read side belongs solely to
the capture thread, the write side is written straight to the channel by the
calling thread, fd lending yields via park/resume. The display (tap)
lifecycle also belongs to the board: attached before power-on (output from
power-on is shown as captured — boot logs/echoes are no longer a black box),
detached before power-off (line noise stays off screen); programmatic calls
can swap the display sink for a buffer (run_collect — device bytes never
land on the service process's stdout).
Dependency direction: board → {power, serial, stream, console}; never reversed.
"""
import sys
import time

from .console import Console
from .power import Power
from .serial import SerialChannel
from .stream import ConsoleStream


class Board:
    """One board = serial + resident capture stream + power + console;
    context manager: entering starts the capture thread, exiting stops the
    thread and closes the serial. Display (tap) attaches before power-on,
    detaches before power-off"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg.name
        self.serial = SerialChannel.from_cfg(cfg)   # one board ↔ one serial channel ([serial] section)
        self.stream = ConsoleStream(self.serial)    # the read side belongs solely to the capture thread
        self.power = Power(cfg)                     # one board ↔ one power object ([power] section)
        self.console = Console.from_cfg(cfg)        # one board ↔ one console ([console] section)
        self._display = None    # programmatic display sink (run_collect); None = live stdout

    def __enter__(self):
        self.stream.start()
        return self

    def __exit__(self, *exc):
        self.stream.stop()
        self.serial.close()

    @property
    def prompt(self):
        """Console prompt (the basis for execution-end detection) — a frequent shortcut"""
        return self.console.prompt

    def session(self):
        """Open a console session on the board's resident capture stream (borrowed, not owned)"""
        return self.console.session(self.stream)

    # ---- display (tap): hooked on capture events, shown as captured ----
    def set_display(self, out):
        """For programmatic calls (run_collect/MCP), swap the display sink:
        device output goes into out instead of stdout — a service process's
        (MCP) stdout is a protocol channel, device bytes must not land on it"""
        self._display = out

    def _show(self, text):
        out = self._display if self._display is not None else sys.stdout
        out.write(text)
        out.flush()

    def _power_cycle(self, note=None):
        """Power off -> delay -> power on (the cadence value is the power
        domain's reset_delay); note is the notice line before power-on
        (the cold boot's "waiting for console prompt").

        Ordering discipline: the notice lands on screen first, then the
        display attaches, then power-on — SPL bytes come out the moment
        power applies, so the notice line can't get torn into the middle
        of the byte stream, nor arrive later than any write to the serial
        (the polling Ctrl-C lives in the wait loop after it).

        The display detaches before power-off and attaches before
        power-on: output from power-on is shown as captured, line noise
        in the power-off window stays off screen"""
        self.stream.set_tap(None)
        print('powering off...', flush=True)
        self.power.off()
        time.sleep(self.power.reset_delay)
        print('powering on...', flush=True)
        if note:
            print(note, flush=True)
        self.stream.set_tap(self._show)   # the notice has landed; power-on bytes display live from here
        self.power.on()

    def cold_boot(self, boot_timeout=60):
        """Power off → power on → poll for the console prompt (back to a
        clean interactive state from any state, whether the payload is
        U-Boot, a Linux shell or another CLI).

        Boot output is shown as captured (the tap attaches before
        power-on) — waiting is no longer a black box. Polling periodically
        sends Ctrl-C to the serial to clear leftover input — not usable
        for passive watching"""
        self._power_cycle(note='waiting for console prompt...')
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            if self.console.interactive_ready(self.session(), timeout=6):
                return
            time.sleep(2)
        sys.exit(f'console prompt not seen within {boot_timeout}s of power-on')

    def quiet_boot(self):
        """Quiet power-on (mode=watch passive mode): off → delay → noise
        clear → on, without writing a single byte to the serial — the board
        runs its own automatic flow, any write would interrupt it (hence
        cold_boot can't be reused: polling for the prompt periodically
        sends Ctrl-C).

        Noise clear = kernel-buffer drain + capture-log clear: the first
        byte received after power-on is boot output (capture and display
        both start at power-on)"""
        self.stream.set_tap(None)   # power-off window (incl. last round's leftovers): line noise stays off screen
        print('powering off...', flush=True)
        self.power.off()
        time.sleep(self.power.reset_delay)
        self.serial.drain()     # power-off noise still in the kernel receive buffer
        self.stream.clear()     # capture log and decoder residue: observation starts at power-on
        # the notice lands on screen before the display attaches (same
        # cold-boot discipline): SPL bytes arrive at power-on without tearing
        # the notice line into the byte stream
        print('powering on (quiet, no serial writes)...', flush=True)
        self.stream.set_tap(self._show)
        self.power.on()

    def reboot(self):
        """Power-cycle reboot back to the prompt (after=reset finish): same
        cadence as cold boot, doesn't wait for the prompt (the next round or
        the user takes over); output from power-on keeps showing as captured"""
        self._power_cycle()

    def power_off(self):
        """Power off (after=off finish): detach the display before cutting
        power — line noise after power-off stays off screen (backlog flushed
        before detaching, the tail of the display isn't lost)"""
        self.stream.set_tap(None)
        self.power.off()
