"""电源控制:全部方式统一为插件(plugins/power),本模块只做语义与编排

- power_on / power_off / power_status:原语(经当前电源插件)
- do_reset / power_cycle_and_wait:断电重启流程
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
