#!/usr/bin/env python3
"""迷你 TFTP 服务器:只处理读请求(RRQ),octet 模式,支持 blksize/tsize 选项协商。

用法: python3 tftp_server.py [根目录]   # 默认 tftpboot
设计目标: 让 SG2002 设备从本机(伪装 192.168.1.17)拉取启动文件。
"""
import os
import socket
import sys
import time

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else 'tftpboot')
PORT = 69
ACK_TIMEOUT = 5   # 等 ACK 超时(秒)
RETRIES = 3       # 每块重试次数


def emit(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def error(sock, addr, code, msg):
    sock.sendto(bytes([0, 5]) + bytes([code >> 8, code & 0xFF])
                + msg.encode() + b'\x00', addr)


def parse_rrq(data):
    parts = data[2:].split(b'\x00')
    filename = parts[0].decode('utf-8', 'replace')
    mode = parts[1].decode('utf-8', 'replace').lower() if len(parts) > 1 else ''
    opts = {}
    for i in range(2, len(parts) - 1, 2):
        opts[parts[i].decode('latin-1').lower()] = parts[i + 1].decode('latin-1')
    return filename, mode, opts


def wait_ack(sock, addr, block):
    """等待指定块的 ACK;超时返回 False"""
    deadline = time.monotonic() + ACK_TIMEOUT
    while time.monotonic() < deadline:
        try:
            d, _ = sock.recvfrom(65536)
        except socket.timeout:
            return False
        if len(d) >= 4 and d[:2] == bytes([0, 4]) and d[2:4] == block:
            return True
    return False


def handle_rrq(sock, addr, data):
    filename, mode, opts = parse_rrq(data)
    emit(f'RRQ {addr[0]}:{addr[1]} {filename} mode={mode} opts={opts or "无"}')

    # 只允许读 ROOT 内的文件,拒绝路径穿越
    path = os.path.realpath(os.path.join(ROOT, filename))
    if not path.startswith(ROOT + os.sep):
        emit(f'  拒绝: 路径越界 {filename}')
        error(sock, addr, 2, 'Access violation')
        return
    if not os.path.isfile(path):
        emit(f'  文件不存在: {filename} -> 返回错误, 设备走后备启动路径')
        error(sock, addr, 1, 'File not found')
        return

    content = open(path, 'rb').read()

    # 选项协商: 只回应 blksize/tsize,其余忽略(客户端回退默认值)
    blksize = 512
    if opts:
        oack = bytes([0, 6])
        if 'blksize' in opts:
            blksize = max(8, min(int(opts['blksize']), 65464))
            oack += b'blksize\x00' + str(blksize).encode() + b'\x00'
        if 'tsize' in opts:
            oack += b'tsize\x00' + str(len(content)).encode() + b'\x00'
        sock.sendto(oack, addr)
        if not wait_ack(sock, addr, bytes([0, 0])):  # ACK 块号 0
            emit(f'  放弃: OACK 后未收到 ACK0')
            return

    block = 1
    while True:
        chunk = content[(block - 1) * blksize: block * blksize]
        pkt = bytes([0, 3]) + bytes([block >> 8, block & 0xFF]) + chunk
        for attempt in range(RETRIES):
            sock.sendto(pkt, addr)
            if wait_ack(sock, addr, bytes([block >> 8, block & 0xFF])):
                break
        else:
            emit(f'  放弃: 块 {block} 重试 {RETRIES} 次无 ACK')
            return
        if len(chunk) < blksize:
            break
        block += 1
    emit(f'  已发送 {filename}: {len(content)} 字节 / {block} 块')


def main():
    os.makedirs(ROOT, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', PORT))
    sock.settimeout(ACK_TIMEOUT)
    emit(f'TFTP 就绪: UDP 0.0.0.0:{PORT}, 根目录 {ROOT}')
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue
        op = data[:2] if len(data) >= 2 else b''
        if op == bytes([0, 1]):
            try:
                handle_rrq(sock, addr, data)
            except Exception as e:  # 单个会话出错不影响服务
                emit(f'  会话异常: {e!r}')
        elif op == bytes([0, 2]):
            emit(f'WRQ {addr[0]} (不支持, 拒绝)')
            error(sock, addr, 4, 'Write not supported')


if __name__ == '__main__':
    main()
