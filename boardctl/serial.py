"""串口域:纯字节通道。只认 URL 与字节——不懂提示符、不懂电源、不懂板卡。

原先散在控制台会话类(打开/读写)与 loady 插件(fd 借出 + O_NONBLOCK
清理)里的底层串口细节,全部收编到这里。
"""
import fcntl
import os

import serial


class SerialChannel:
    """串口字节通道:read/write/drain,可把底层 fd 借给子进程(Ymodem)"""

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
        """清空接收缓冲(如断电期间的线路噪声)"""
        self.ser.reset_input_buffer()

    @property
    def fd(self):
        """底层 fd(socket:// 串口用其 socket 的 fd);无可得 fd 时为 None"""
        raw = getattr(self.ser, 'sock', None)
        if raw is not None:
            return raw.fileno()
        try:
            return self.ser.fileno()
        except Exception:
            return None

    def blocking_fd(self):
        """清掉 timeout 设置的 O_NONBLOCK 后返回 fd——否则子进程 read 会把
        EAGAIN 当超时;无可得 fd 时返回 None"""
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
