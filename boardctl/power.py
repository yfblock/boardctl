"""电源域:纯电源动作(on/off/status),绝不碰串口——
"开机进入可交互态"(冷启动等提示符/静默上电)是板卡域 board.py 的事,
它组合本域与串口域完成。插件即类(PowerDevice 子类,见 plugins/power/),
经 [power].method 选择,多态 = 不同子类同一接口。
- power_on / power_off / power_status:门面(错误包装经当前电源插件)
- do_power:power 子命令语义;do_reset:断电重启(after=reset 收尾用)
"""
import sys
import time


def _device(cfg):
    from .plugins import POWER   # 函数内 import:避免 board→power→plugins→插件→board 环
    method = cfg['power'].get('method') or 'command'  # 未配置时默认命令插件
    cls = POWER.get(method)
    if cls is None:
        sys.exit(f'未知电源插件 {method!r},可用: {" ".join(sorted(POWER)) or "(无)"}')
    return cls(cfg)


def method_desc(cfg):
    return f'插件 {cfg["power"].get("method") or "command"}'


def power_on(cfg):
    try:
        _device(cfg).on()
    except SystemExit:
        raise
    except Exception as e:
        sys.exit(f'上电失败({method_desc(cfg)}): {e}')


def power_off(cfg, check=True) -> bool:
    """断电;check=False 时不因失败退出进程,改为返回 False"""
    try:
        _device(cfg).off()
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
        val = _device(cfg).status()
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
