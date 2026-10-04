"""Serial domain: pure byte channel — knows only URLs and bytes, no prompts,
no power, no boards."""
import fcntl
import os

import serial


class SerialChannel:
    """Serial byte channel: read/write/drain + fd lending to a subprocess (Ymodem)."""

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
        """Empty the receive buffer (power-off line noise)."""
        self.ser.reset_input_buffer()

    @property
    def fd(self):
        """Underlying fd (socket:// → its socket's fd); None if unavailable."""
        raw = getattr(self.ser, 'sock', None)
        if raw is not None:
            return raw.fileno()
        try:
            return self.ser.fileno()
        except Exception:
            return None

    def blocking_fd(self):
        """fd with O_NONBLOCK cleared (a subprocess read treats EAGAIN as timeout); None if unavailable."""
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
