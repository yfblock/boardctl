"""Resident-capture domain: a reader thread continuously decodes channel
bytes into a capture log; waiting = watermark + predicate + condition-variable
wakeup (no polling). With capture and waiting decoupled:

- bytes between phases aren't lost — nobody has to be reading first; bytes
  land in the log, waiters count from their own watermark (in the old model
  the kernel socket buffer played this role; the watermark moved up into
  userspace, turning "where to count from" from calling discipline into
  interface semantics);
- display hangs on capture events (tap): new text is called back in the
  reader thread's context as captured — everything from power-on (boot
  logs/command echo/execution output) reaches the screen naturally, without
  each waiter printing for itself; before detaching, the backlog is flushed
  (no display gap), on re-attach no replay of the power-off window's bytes
  (line noise isn't re-shown); the power-off window is handled by Board
  detaching the tap;
- fd lending (loady's Ymodem) handshakes with the capture thread via
  park/resume: protocol bytes during the lend belong to the borrower and
  don't enter the log; after resume the bytes left in the channel pick up
  seamlessly;
- outbound still writes straight to the channel (single writer on the
  calling thread); the device's echo of input is inbound bytes, naturally
  entering the log (and naturally on screen).

The read side belongs solely to the capture thread, the write side solely to
the calling thread — the channel object itself is never touched.
"""
import codecs
import threading
import time


class ConsoleStream:
    """Resident capture stream: reader thread + capture log + watermark
    waiting; writes and fd lending pass through to the underlying channel"""

    def __init__(self, channel):
        self.channel = channel          # SerialChannel shape (read/write/fd)
        self._cond = threading.Condition()
        self._log = ''                  # capture log (accumulated decoded text)
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self._thread = None
        self._stop = False
        self._parked = False            # fd-lend period: reader thread stands down
        self._paused = False            # reader confirmed out of read (handshake with the borrower)
        self._error = None              # fatal reader error (bridge down etc.), re-raised on waiters
        self._tap = None                # display callback: shown as captured, in the reader thread
        self._shown = 0                 # display watermark: log length already fed to the tap

    # ---- lifecycle ----
    def start(self):
        if self._thread is not None:
            return
        self._stop = False
        self._thread = threading.Thread(target=self._pump, name='boardctl-console',
                                        daemon=True)
        self._thread.start()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _pump(self):
        try:
            while True:
                with self._cond:
                    if self._stop:
                        return
                    if self._parked:
                        self._paused = True
                        self._cond.notify_all()
                        while self._parked and not self._stop:
                            self._cond.wait(0.5)
                        self._paused = False
                        if self._stop:
                            return
                        continue
                data = self.channel.read(256)   # read without the lock; re-acquire to append
                if data:
                    tap, chunk = None, ''   # decode may be empty (multi-byte char split across reads)
                    with self._cond:
                        text = self._decoder.decode(data)
                        if text:
                            self._log += text
                            chunk = self._log[self._shown:]
                            self._shown = len(self._log)
                            tap = self._tap
                            self._cond.notify_all()
                    if tap is not None and chunk:
                        try:
                            tap(chunk)  # callback without the lock: slow display can't stall waiters/lend handshake
                        except Exception:
                            pass        # a display fault must not kill the capture thread
        except Exception as e:   # bridge down/channel error: waiters shouldn't sit out the timeout, re-raise
            with self._cond:
                self._error = e
                self._cond.notify_all()

    # ---- outbound & fd (straight to the channel; the read side belongs solely to the capture thread) ----
    def write(self, data):
        """Write bytes to the channel; the device's echo of input enters the capture log naturally as inbound bytes"""
        if isinstance(data, str):
            data = data.encode()
        self.channel.write(data)

    @property
    def fd(self):
        return self.channel.fd

    def blocking_fd(self):
        return self.channel.blocking_fd()

    # ---- capture log & waiting ----
    def mark(self):
        """Current watermark: text()/wait() count from here afterwards"""
        with self._cond:
            return len(self._log)

    def text(self, since):
        """Window text since the watermark (a snapshot)"""
        with self._cond:
            return self._log[since:]

    def wait(self, pred, since, timeout):
        """From watermark since, wait until the predicate holds: new bytes
        wake immediately (condition variable, no polling). Returns (window
        text, whether it hit within the timeout).

        The predicate may also express a time condition (e.g. expiry of
        the loss-stopping linger window) — expiry is backstopped by the
        timeout wakeup. Display doesn't live here: it hangs on capture
        events (set_tap), waiters mind only the predicate."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                text = self._log[since:]
                if pred(text):
                    return text, True
                if self._error is not None:
                    raise self._error
                if deadline is not None:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        return text, False
                    self._cond.wait(rem)
                else:
                    self._cond.wait(0.5)

    def set_tap(self, fn):
        """Attach/detach the display callback (tap): fn(text) executes in the
        reader thread's context — shown as captured, "displayed from within
        the stream"; waiters mind only the predicate, no printing duty mixed
        in.

        Before detaching (fn=None) the old callback first flushes the
        undisplayed backlog — the display has no gap relative to capture;
        on re-attach no replay of bytes captured while detached (power-off
        noise isn't re-shown), display starts from the moment of attaching.

        Callback exceptions are swallowed: a display fault must not poison
        the capture thread or waiters."""
        with self._cond:
            prev, backlog = self._tap, self._log[self._shown:]
            self._shown = len(self._log)
            self._tap = fn
        if prev is not None and backlog:
            try:
                prev(backlog)
            except Exception:
                pass

    def clear(self):
        """Empty the capture log and reset decoder residue (drop power-off
        noise before a quiet power-on). All earlier watermarks are voided —
        the caller must guarantee no waiters are in flight; the undisplayed
        backlog is dropped too (noise isn't fed back into the display)"""
        with self._cond:
            self._log = ''
            self._shown = 0
            self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    # ---- fd lending support (Ymodem for loady) ----
    def park(self):
        """Call before lending: returns only once the reader thread has
        confirmed it's out of read — from then on all bytes belong to the
        borrower and don't enter the capture log"""
        with self._cond:
            self._parked = True
            while not self._paused and not self._stop and self._error is None:
                self._cond.wait(0.5)

    def resume(self):
        """Call after returning: the reader thread goes back to the read
        loop, bytes left in the channel pick up seamlessly"""
        with self._cond:
            self._parked = False
            self._cond.notify_all()
