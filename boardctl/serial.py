"""Serial domain: pure byte channel. Knows only URLs and bytes — no prompts,
no power, no boards.

Low-level serial details once scattered across the console-session class
(open/read/write) and the loady plugin (fd lending + O_NONBLOCK cleanup)
are all collected here.
"""
import fcntl
import os

import serial


class SerialChannel:
    """Serial byte channel: read/write/drain, can lend the underlying fd to
    a subprocess (Ymodem)"""

    def __init__(self, url, timeout):
        self.ser = serial.serial_for_url(url, timeout=timeout)

    @classmethod
    def from_cfg(cls, cfg):
        return cls(cfg.serial.url, cfg.serial.timeout)

    def read(self, n=256):
        return self.ser.read(n)

    def write(self, data):
        self.ser.write(data.encode() if isinstance(data, str) else data)

    def drain(self):
        """Empty the receive buffer (e.g. line noise during power-off)"""
        self.ser.reset_input_buffer()

    @property
    def fd(self):
        """Underlying fd (socket:// serials use their socket's fd); None when no fd is obtainable"""
        raw = getattr(self.ser, 'sock', None)
        if raw is not None:
            return raw.fileno()
        try:
            return self.ser.fileno()
        except Exception:
            return None

    def blocking_fd(self):
        """Return the fd after clearing the O_NONBLOCK set by timeout —
        otherwise a subprocess read treats EAGAIN as a timeout; returns None
        when no fd is obtainable"""
        fd = self.fd
        if fd is None:
            return None
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
        return fd

    def close(self):
        try:
            self.ser.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
