"""loady transport: loady (Ymodem) on the device + local lrzsz sender, over
the serial, zero network dependencies."""
import os
import re
import shutil
import subprocess
import sys
import time

from ...console import ConsoleSession
from . import Transport


class LoadyTransport(Transport):
    NAME = 'loady'

    def __init__(self, cfg):
        self.cfg = cfg

    def _sender(self):
        sender = self.cfg.loady.sender
        if sender and os.path.isfile(sender):
            return sender
        return shutil.which('lrzsz-sb') or shutil.which('sb')

    def send(self, channel, path, addr):
        """channel: the board's resident capture stream, lent by the orchestrator."""
        sender = self._sender()
        if not sender:
            sys.exit('no Ymodem sender found (Arch: lrzsz-sb from the lrzsz package; Debian: sb from lrzsz)')
        s = ConsoleSession(channel, self.cfg.console.prompt)
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('timed out waiting for the U-Boot prompt; the device may not be at the U-Boot command line')
        channel.write(f'loady {addr}\r')
        time.sleep(1.5)  # wait for the device to enter Ymodem receive mode

        # lend the fd to the sender: park the capture thread first — Ymodem
        # protocol bytes during the lend belong to the sender and stay out
        # of the log; after resume the remaining bytes pick up seamlessly
        channel.park()
        try:
            fd = channel.blocking_fd()
            if fd is None:
                sys.exit('this serial URL does not support handing the fd to the Ymodem sender')

            p = subprocess.Popen([sender, os.path.abspath(path)],
                                 stdin=fd, stdout=fd, stderr=subprocess.PIPE)
            try:
                _, err = p.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
                print('Ymodem sender timed out (180s), terminated')
                return False
        finally:
            channel.resume()
        tail, _ = s.read_until(s.prompt, 10)
        print(err.decode('utf-8', 'replace').strip())
        # serial-side output isn't reprinted: the tap already shows it live;
        # success stays silent, only size checks or failure verdicts print
        m = re.search(r'Total Size\s*=\s*(0x[0-9a-fA-F]+|\d+)', tail)
        if m:
            size = int(m.group(1), 0)
            actual = os.path.getsize(path)
            ok = size == actual
            if not ok:
                print(f'loady size mismatch: device received {size} bytes (local {actual})')
            return ok
        print('loady transfer failed (no Total Size report seen)')
        return False


PLUGIN = LoadyTransport
