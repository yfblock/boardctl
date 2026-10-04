"""tftp transport plugin: the device pulls via tftpboot. How files get
staged is declared explicitly via [tftp].method:
remote   = scp to a remote tftp server;
external = a resident tftpd (e.g. tftpd-hpa) already serves UDP 69 on this
           host; just drop the file into its root dir — no port probing, no
           server setup, no privileges.
"""
import os
import re
import shutil
import subprocess
import sys

from ...console import ConsoleSession
from . import Transport


def _port_listeners(port, files=('/proc/net/udp', '/proc/net/udp6')):
    """Find sockets bound to this local UDP port in /proc/net/udp{,6}
    (visible without privileges). Non-empty return = some process holds the
    port (e.g. a resident tftpd-hpa)."""
    found = []
    for f in files:
        try:
            with open(f) as fh:
                next(fh, None)   # header line
                for line in fh:
                    cols = line.split()
                    if len(cols) > 1 and ':' in cols[1]:
                        try:
                            if int(cols[1].rsplit(':', 1)[1], 16) == port:
                                found.append(f'{f}: {cols[1]}')
                        except ValueError:
                            continue
        except OSError:
            continue
    return found


def _drop_into(local_dir, path, fname):
    """Drop the file into the tftp root dir; skip if already in place (avoids self-copy)"""
    dst = os.path.join(local_dir, fname)
    if os.path.realpath(path) == os.path.realpath(dst):
        return
    os.makedirs(local_dir, exist_ok=True)
    shutil.copy(path, dst)


class TftpTransport(Transport):
    NAME = 'tftp'

    def __init__(self, cfg):
        self.cfg = cfg

    def _stage_file(self, path):
        """Put the file where the TFTP server can read it"""
        t = self.cfg.tftp
        method = t.method
        fname = os.path.basename(path)

        if method == 'remote':
            ssh, rdir = t.ssh_host, t.remote_dir
            if not (ssh and rdir):
                sys.exit('tftp.method=remote needs tftp.ssh_host and tftp.remote_dir')
            r = subprocess.run(['scp', '-q', os.path.abspath(path), f'{ssh}:{rdir}/'],
                               timeout=60)
            if r.returncode != 0:
                sys.exit(f'scp to {ssh}:{rdir} failed — most likely directory permissions.\n'
                         f'One-time fix: ssh -t {ssh} "sudo chown $USER {rdir}"\n'
                         'or switch this target to method = "loady" (no privileges needed, slower)')
        elif method == 'external':
            # a resident tftpd already serves UDP 69 on this host: boardctl
            # only stages the file; whether the server runs is the declarer's
            # business — probing the port would guess intent, so don't (just a
            # one-line heads-up if it looks down)
            local_dir = os.path.abspath(t.local_dir)
            _drop_into(local_dir, path, fname)
            if os.path.exists('/proc/net/udp') and not _port_listeners(69):
                print('warning: no UDP 69 listener on this host — the resident tftpd seems not to be running, the device pull will most likely fail',
                      file=sys.stderr, flush=True)
        else:
            if method == 'local':
                sys.exit('tftp method="local" (boardctl self-hosting a temporary TFTP server) has been removed:\n'
                         'with a resident tftpd (e.g. tftpd-hpa) on this host, use method = "external";\n'
                         'without tftpd, switch the target to method = "loady" (Ymodem over serial, no privileges)')
            sys.exit(f'unknown tftp.method: {method} (available: remote / external)')

    def send(self, channel, path, addr):
        """channel: the board's resident capture stream (lent by the
        orchestrator; the plugin opens no connection of its own and doesn't
        close it when done)"""
        self._stage_file(path)
        fname = os.path.basename(path)
        server_ip = self.cfg.uboot.server_ip
        s = ConsoleSession(channel, self.cfg.console.prompt)
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('timed out waiting for the U-Boot prompt; the device may not be at the U-Boot command line')
        if self.cfg.uboot.ensure_server_ip and server_ip:
            s.cmd(f'setenv serverip {server_ip}')
        out, hit = s.cmd(f'tftpboot {addr} {fname}', timeout=60)
        # success stays silent: the echo (shown live by the tap) already has
        # the tftpboot line and Bytes transferred; only locally-known facts
        # (size check) or failure verdicts get printed
        m = re.search(r'Bytes transferred = (\d+)', out)
        if m:
            actual = os.path.getsize(path)
            size = int(m.group(1))
            ok = size == actual
            if not ok:
                print(f'tftp size mismatch: device received {size} bytes (local {actual})')
            return ok
        print('tftp transfer failed (no Bytes transferred seen'
              + ('' if hit else '; prompt wait timed out, output is truncated') + ')')
        return False


PLUGIN = TftpTransport
