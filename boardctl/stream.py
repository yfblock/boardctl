"""Resident capture: a reader thread continuously decodes channel bytes into
a capture log; waiting = watermark + predicate + condition-variable wakeup
(no polling); display is a tap callback fired from the reader thread as text
is captured.

Ownership: the read side belongs solely to the reader thread, the write side
solely to the calling thread. Waiters count from their own watermark — bytes
between phases land in the log, never lost. During an fd lend (park/resume,
Ymodem) protocol bytes belong to the borrower and stay out of the log."""
import codecs
import threading
import time


class ConsoleStream:
    """Reader thread + capture log + watermark waiting; writes and fd lending
    pass through to the underlying channel."""

    def __init__(self, channel):
        self.channel = channel          # SerialChannel shape (read/write/fd)
        self._cond = threading.Condition()
        self._log = ''                  # accumulated decoded text
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self._thread = None
        self._stop = False
        self._parked = False            # fd-lend period: reader stands down
        self._paused = False            # reader confirmed out of read (lend handshake)
        self._error = None              # fatal reader error (bridge down etc.), re-raised on waiters
        self._tap = None                # display callback, runs in the reader thread
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
                            tap(chunk)  # callback without the lock: slow display can't stall waiters
                        except Exception:
                            pass        # a display fault must not kill the capture thread
        except Exception as e:   # bridge down/channel error: re-raise on waiters instead of sitting out the timeout
            with self._cond:
                self._error = e
                self._cond.notify_all()

    # ---- outbound & fd (straight to the channel; the read side belongs solely to the capture thread) ----
    def write(self, data):
        """Write to the channel; the device's echo returns as inbound bytes (into the log)."""
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
        """Current watermark: text()/wait() count from here afterwards."""
        with self._cond:
            return len(self._log)

    def text(self, since):
        """Window text since the watermark (a snapshot)."""
        with self._cond:
            return self._log[since:]

    def wait(self, pred, since, timeout):
        """Wait from watermark until pred holds on the window text; new
        bytes wake immediately. A predicate may express a time condition —
        its expiry is backstopped by the timeout wakeup."""
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
        """Attach/detach the display callback: fn(text) runs in the reader
        thread, shown as captured. Detach flushes the backlog first (no
        display gap); re-attach doesn't replay bytes captured while
        detached. Callback exceptions are swallowed."""
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
        """Empty the log and reset decoder residue (drop power-off noise).
        Voids all earlier watermarks — no waiters may be in flight."""
        with self._cond:
            self._log = ''
            self._shown = 0
            self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    # ---- fd lending support (Ymodem for loady) ----
    def park(self):
        """Before lending: returns once the reader confirms it's out of read —
        from then on all bytes belong to the borrower."""
        with self._cond:
            self._parked = True
            while not self._paused and not self._stop and self._error is None:
                self._cond.wait(0.5)

    def resume(self):
        """After returning: the reader resumes; bytes left in the channel pick up seamlessly."""
        with self._cond:
            self._parked = False
            self._cond.notify_all()
