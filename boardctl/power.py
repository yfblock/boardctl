"""电源控制:全部方式统一为插件(plugins/power),本模块只做语义与编排

- power_on / power_off / power_status:原语(经当前电源插件)
- do_reset / power_cycle_and_wait:断电重启流程(后者轮询等提示符,会写串口)
- power_cycle_quiet:静默断电重启(零写入,被动模式 exec=watch 专用)
- [power].method 选择插件;mijia = 原生小米云,command = 特制开关机命令(默认)
"""
import sys
import time

from .plugins import POWER
from .session import UbootSession


def _plugin(cfg):
    method = cfg['power'].get('method') or 'command'  # 未配置时默认命令插件
    p = POWER.get(method)
    if p is None:
        sys.exit(f'未知电源插件 {method!r},可用: {" ".join(sorted(POWER)) or "(无)"}')
    return p


def method_desc(cfg):
    return f'插件 {cfg["power"].get("method") or "command"}'


def power_on(cfg):
    try:
        _plugin(cfg).set_power(cfg, True)
    except SystemExit:
        raise
    except Exception as e:
        sys.exit(f'上电失败({method_desc(cfg)}): {e}')


def power_off(cfg, check=True) -> bool:
    """断电;check=False 时不因失败退出进程,改为返回 False"""
    try:
        _plugin(cfg).set_power(cfg, False)
        return True
    except SystemExit:
        raise
    except Exception as e:
        print(f'断电失败({method_desc(cfg)}): {e}', file=sys.stderr)
        if check:
            sys.exit(1)
        return False


def power_status(cfg):
    """查询状态;返回 bool,无法解析(如 command 插件)时打印输出并返回 None"""
    try:
        val = _plugin(cfg).get_power(cfg)
    except SystemExit:
        raise
    except Exception as e:
        sys.exit(f'查询电源状态失败({method_desc(cfg)}): {e}')
    return None if val is None else bool(val)


def do_power(cfg, state):
    if state == 'status':
        val = power_status(cfg)
        if val is not None:
            print('开' if val else '关')
        sys.exit(0)
    (power_on if state == 'on' else power_off)(cfg)
    sys.exit(0)


def do_reset(cfg):
    delay = float(cfg['power'].get('reset_delay', 3))
    print('断电...', flush=True)
    power_off(cfg)
    time.sleep(delay)
    print('上电...', flush=True)
    power_on(cfg)
    print(f'已重启(如需看启动输出: boardctl -b {cfg["name"]} console)')


def power_cycle_quiet(cfg, ser):
    """静默断电重启(被动模式 exec=watch 专用):断 -> 延时 -> 清噪 -> 合,
    全程不向串口写入一个字节——板子自己跑自动流程,任何写入都会打断它
    (故不能复用 power_cycle_and_wait:轮询等提示符会周期性发 Ctrl-C)。
    ser: 已打开的串口;上电前清掉断电期间的线路噪声,
    保证之后收到的第一个字节就是启动输出"""
    delay = float(cfg['power'].get('reset_delay', 3))
    print('断电...', flush=True)
    power_off(cfg)
    time.sleep(delay)
    ser.reset_input_buffer()
    print('上电(静默,不写串口)...', flush=True)
    power_on(cfg)


def power_cycle_and_wait(cfg, boot_timeout=60):
    """断电 -> 上电 -> 轮询等待 U-Boot 提示符(从任意状态回到干净的提示符)"""
    delay = float(cfg['power'].get('reset_delay', 3))
    print('断电...', flush=True)
    power_off(cfg)
    time.sleep(delay)
    print('上电,等待 U-Boot 提示符...', flush=True)
    power_on(cfg)
    deadline = time.monotonic() + boot_timeout
    while time.monotonic() < deadline:
        with UbootSession(cfg) as s:
            ok, _ = s.wait_prompt(timeout=6)
            if ok:
                return
        time.sleep(2)
    sys.exit(f'上电后 {boot_timeout} 秒内未等到 U-Boot 提示符')
