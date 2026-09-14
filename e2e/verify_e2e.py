#!/usr/bin/env python3
"""端到端验收:部署两套测试到 SG2002 并逐字节比对串口原始输出。

前置:板卡在 U-Boot 提示符(或任意状态,脚本会先 reset)。
用法:../../.venv/bin/python verify_e2e.py   (在 e2e/ 下)
"""
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOARDCTL = os.path.join(ROOT, '.venv/bin', 'python')
URL = ('172.16.0.7', 5000)

# 期望的原始字节流(裸机程序只发 \n;U-Boot echo 发 \r\n)
BM_EXPECTED = b'BM-TEST-START\nBM-COUNTER-1\nBM-COUNTER-2\nBM-COUNTER-3\nBM-TEST-DONE\n'
SCR_EXPECTED = b'SCRIPT-START\r\nSCRIPT-MIDDLE\r\nSCRIPT-DONE\r\n'


def sh(*args):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(f'命令失败: {" ".join(args)}')
    return r.stdout


def run_capture(cmdline, seconds):
    """连接串口,执行一条 U-Boot 命令,收集原始字节流"""
    s = socket.create_connection(URL, timeout=3)
    s.settimeout(0.5)
    time.sleep(0.8)
    s.sendall(cmdline.encode() + b'\r')
    out = b''
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            d = s.recv(4096)
        except socket.timeout:
            continue
        if not d:
            break
        out += d
    s.close()
    return out


def phase_reset():
    print('== 断电重启,回到 U-Boot 提示符 ==', flush=True)
    sh(BOARDCTL, '-m', 'boardctl', '-b', 'sg2002', 'reset')
    time.sleep(9)


failures = 0

# ---- 测试 1:裸机(tftp 部署 + go 执行,预期死循环)
phase_reset()
print('== 测试 1:裸机程序 ==', flush=True)
sh(BOARDCTL, '-m', 'boardctl', '-b', 'sg2002', 'send',
   'e2e/baremetal/hello.bin', '--method', 'tftp', '--addr', '0x80080000')
out = run_capture('go 0x80080000', 8)
if BM_EXPECTED in out:
    print('PASS: 66 字节标记流逐字节一致')
    print(f"      {BM_EXPECTED.decode().replace(chr(10), ' / ')}")
else:
    failures += 1
    print(f'FAIL: 未找到期望字节流,实际原始输出 {len(out)} 字节:')
    print(repr(out))

# ---- 测试 2:U-Boot 脚本(uImage 镜像 + source 执行,预期干净返回)
phase_reset()
print('== 测试 2:U-Boot 脚本 ==', flush=True)
sh(BOARDCTL, '-m', 'boardctl', '-b', 'sg2002', 'send',
   'e2e/script/test_uboot.scr', '--method', 'tftp', '--addr', '0x80080000')
out = run_capture('source 0x80080000', 8)
ok = SCR_EXPECTED in out and b'Unknown command' not in out and b'soph#' in out
if ok:
    print('PASS: 三标记 + 无报错 + 干净返回 soph#')
else:
    failures += 1
    print(f'FAIL: 实际原始输出 {len(out)} 字节:')
    print(repr(out))

print()
print('结果: ' + ('全部通过 ✅' if failures == 0 else f'{failures} 项失败 ❌'))
sys.exit(1 if failures else 0)
