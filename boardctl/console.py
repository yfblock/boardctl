"""交互式串口终端:raw 模式、按键本地命令、autoboot 自动拦截、退出自动断电"""
import codecs
import os
import select
import signal
import sys
import termios
import threading
import time
import tty

import serial

from . import power

CTRL_A = 0x01
QUIT_BYTE = 0x1C              # Ctrl-\ 任意时刻直接退出
QUIT_KEYS = (0x71, 0x78, 0x18)  # Ctrl-A q / Ctrl-A x(ostool 惯例) / Ctrl-A Ctrl-X

BOOT_MARKERS = ('u-boot', 'hit any key', 'autoboot', 'arp retry')
SERVER_ERROR = 'device open failure'
INTERRUPT_INTERVAL = 0.1
INTERRUPT_WINDOW = 15.0

HELP = (
    '\r\n[本地按键]\r\n'
    '  Ctrl-\\      退出(任意时刻)\r\n'
    '  Ctrl-A x/q  退出\r\n'
    '  Ctrl-A b    手动开启一轮 autoboot 拦截\r\n'
    '  Ctrl-A h    显示本帮助\r\n'
    '  其他按键    原样转发到设备(包括 Ctrl-C)\r\n'
)


def cmsg(text):
    print(f'\r\n{text}\r\n', end='', flush=True)


def console_reader(ser, write_lock, manual_trigger, stop, quit_event, prompts):
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    buf = ''
    window_until = 0.0
    last_sent = 0.0

    while not stop.is_set() and not quit_event.is_set():
        try:
            data = ser.read(100)
        except Exception:  # 关闭竞态:主线程 close() 后底层 socket 置 None
            return
        if data:
            text = decoder.decode(data)
            print(text, end='', flush=True)
            low = text.lower()
            if SERVER_ERROR in low:
                cmsg('串口服务器打不开物理串口(服务器端设备不可用),稍后重连')
                return
            buf = (buf + low)[-160:]

        now = time.monotonic()
        if manual_trigger.is_set():
            manual_trigger.clear()
            window_until = now + INTERRUPT_WINDOW

        if window_until == 0.0:
            if any(m in buf for m in BOOT_MARKERS):
                buf = ''
                window_until = now + INTERRUPT_WINDOW
                cmsg('检测到启动特征,发送按键打断 autoboot...')
        elif now < window_until:
            if any(p in buf for p in prompts):
                buf = ''
                window_until = 0.0  # 已停在提示符,停止发送
            elif now - last_sent >= INTERRUPT_INTERVAL:
                last_sent = now
                try:
                    with write_lock:
                        ser.write(b'\r\x03')
                except Exception:  # 同上,关闭竞态
                    return
        else:
            buf = ''
            window_until = 0.0


def handle_stdin(data, ser, write_lock, manual_trigger, state):
    for c in data:
        if c == QUIT_BYTE:
            return 'quit'
        if state['prefix']:
            state['prefix'] = False
            if c in QUIT_KEYS:
                return 'quit'
            if c == ord('b'):
                manual_trigger.set()
                cmsg('手动触发拦截窗口')
            elif c == ord('h'):
                print(HELP, end='', flush=True)
            elif c == CTRL_A:
                with write_lock:
                    ser.write(bytes([CTRL_A]))
        elif c == CTRL_A:
            state['prefix'] = True
        else:
            with write_lock:
                ser.write(bytes([c]))
    return None


def console_session(ser, write_lock, manual_trigger, stop, quit_event, state, prompts):
    reader = threading.Thread(
        target=console_reader,
        args=(ser, write_lock, manual_trigger, stop, quit_event, prompts),
        daemon=True)
    reader.start()

    with write_lock:
        ser.write(b'\r')
    manual_trigger.set()

    while True:
        if quit_event.is_set():
            return 'quit'
        r, _, _ = select.select([sys.stdin], [], [], 0.2)
        if r:
            data = os.read(sys.stdin.fileno(), 1024)
            if not data:
                return 'quit'
            try:
                if handle_stdin(data, ser, write_lock, manual_trigger, state) == 'quit':
                    return 'quit'
            except Exception:  # 串口失效(含关闭竞态)
                return 'reconnect'
        if not reader.is_alive():
            return 'reconnect'


def console_wait_or_quit(seconds, state, quit_event):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if quit_event.is_set():
            return False
        r, _, _ = select.select([sys.stdin], [], [], 0.2)
        if not r:
            continue
        data = os.read(sys.stdin.fileno(), 1024)
        if not data:
            return False
        for c in data:
            if c == QUIT_BYTE or (state['prefix'] and c in QUIT_KEYS):
                return False
            state['prefix'] = (c == CTRL_A)
    return True


def do_console(cfg):
    prompts = list(dict.fromkeys([cfg['uboot']['prompt'], '=>']))
    raw_mode = sys.stdin.isatty()
    if raw_mode:
        old_attrs = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())

    write_lock = threading.Lock()
    manual_trigger = threading.Event()
    stop = threading.Event()
    quit_event = threading.Event()
    state = {'prefix': False}
    signal.signal(signal.SIGTERM, lambda *_: quit_event.set())
    signal.signal(signal.SIGINT, lambda *_: quit_event.set())

    power_off = cfg['power'].get('off_on_exit') and cfg['power'].get('off_cmd')
    banner = f'连接 {cfg["serial"]["url"]} | Ctrl-\\ 退出, Ctrl-A h 帮助'
    if power_off:
        banner += ',退出时自动断电'
    cmsg(banner)
    try:
        while True:
            try:
                ser = serial.serial_for_url(
                    cfg['serial']['url'], timeout=cfg['serial']['timeout'])
            except serial.SerialException as e:
                cmsg(f'连接失败: {e},3 秒后重试')
                if not console_wait_or_quit(3, state, quit_event):
                    return
                continue
            try:
                result = console_session(
                    ser, write_lock, manual_trigger, stop, quit_event, state, prompts)
            finally:
                try:
                    ser.close()
                except OSError:
                    pass
            if result == 'quit' or quit_event.is_set():
                return
            if not console_wait_or_quit(3, state, quit_event):
                return
    finally:
        stop.set()
        if raw_mode:
            termios.tcdrain(sys.stdin.fileno())
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)
        # 按配置在退出时断电(power.off_on_exit)
        if power_off:
            cmsg('退出:执行断电(power.off_on_exit)')
            if not power.power_off(cfg, check=False):
                cmsg('断电失败,请手动确认电源状态')
        cmsg('已退出')
