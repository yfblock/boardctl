"""command 电源插件:执行 [power] 里配置的 on_cmd / off_cmd / status_cmd 命令

"特制开关机命令"方式:任意 shell 命令,经顶层 ssh_host 决定本机/远端执行。
status_cmd 可缺省;命令输出无法可靠解析时 get_power 返回 None(上层原样打印)。
method 未配置时默认即本插件。
"""
import sys

from ...shell import run as run_shell

NAME = 'command'
CFG_SECTION = 'power'
DEFAULTS = {'on_cmd': None, 'off_cmd': None, 'status_cmd': None}


def _cmd(cfg, key):
    command = cfg['power'].get(key)
    if not command:
        sys.exit(f'[power] 缺少 {key}(command 电源插件需要 on_cmd/off_cmd)')
    return command


def set_power(cfg, on):
    run_shell(cfg, _cmd(cfg, 'on_cmd' if on else 'off_cmd'), check=True)


def get_power(cfg):
    status = cfg['power'].get('status_cmd')
    if status:
        run_shell(cfg, status, check=False)
    return None  # 任意命令的输出无法可靠解析为 bool
