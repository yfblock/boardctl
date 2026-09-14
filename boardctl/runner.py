"""run / cmd 编排:冷启动 -> 传输(插件) -> 执行(插件) -> expect 断言 -> 收尾"""
import os
import subprocess
import sys

from . import power
from .config import BASE_DIR
from .plugins import EXECUTORS, TRANSPORT
from .session import UbootSession


def do_cmd(cfg, commands):
    with UbootSession(cfg) as s:
        ok, text = s.wait_prompt()
        if not ok:
            sys.exit('等待 U-Boot 提示符超时——设备可能正在启动或不在命令行。\n'
                     f'最后输出: {text[-200:]!r}\n'
                     '可先 power reset 后再试。')
        for c in commands:
            out = s.cmd(c)
            # 去掉开头的命令回显
            if out.startswith(c):
                out = out[len(c):].lstrip('\r\n')
            print(out.strip('\r\n'), flush=True)


def do_run(cfg, name):
    """按板卡配置里的 [run.<名字>] 一键启动:(可选冷启动) -> 传输 -> 执行 -> 收尾"""
    targets = cfg.get('run', {})
    if not name:
        if not targets:
            sys.exit(f'{cfg["name"]} 配置里没有 [run.*] 启动目标')
        print(f'{cfg["name"]} 可启动目标(boardctl run <名字>):')
        for k, t in targets.items():
            desc = t.get('desc', '')
            print(f'  {k:12} exec={t.get("exec", "none"):8} {t.get("file", "")}  {desc}')
        return
    if name not in targets:
        sys.exit(f'未定义的启动目标 {name!r},可用: {" ".join(targets) or "(无)"}')
    t = targets[name]

    if t.get('reset_before'):
        print(f'[{name}] 冷启动(断电->上电->等提示符)', flush=True)
        power.power_cycle_and_wait(cfg)

    path = t['file']
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    if not os.path.isfile(path):
        sys.exit(f'文件不存在: {path}(先构建?)')
    addr = t.get('addr', cfg['uboot']['load_addr'])   # 加载地址
    entry = t.get('entry', addr)                      # 跳转/执行地址,默认与加载地址相同
    method = t.get('method', 'tftp')
    transport = TRANSPORT.get(method)
    if transport is None:
        sys.exit(f'未知传输方式 {method!r},可用: {" ".join(sorted(TRANSPORT)) or "(无)"}')

    print(f'[{name}] 传输 {t["file"]} ({method}) -> {addr}', flush=True)
    if not transport.send(cfg, path, addr):
        sys.exit(1)

    exec_mode = t.get('exec', 'none')
    executor = EXECUTORS.get(exec_mode)
    if executor is None:
        sys.exit(f'未知 exec 方式: {exec_mode}(可用: {" ".join(sorted(EXECUTORS))})')
    cmdline = executor.build_cmd(entry)
    if cmdline is None:
        print(f'[{name}] 已加载到 {addr}(exec={exec_mode},未执行)')
        return

    timeout = float(t.get('timeout', 15))
    print(f'[{name}] 执行: {cmdline}', flush=True)
    with UbootSession(cfg) as s:
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('等待 U-Boot 提示符超时')
        out = s.cmd(cmdline, timeout)
        print(out.strip('\r\n'), flush=True)

    # 期望断言:expect 为字符串或字符串列表,全部命中才算 PASS
    expects = t.get('expect')
    if isinstance(expects, str):
        expects = [expects]
    verdict = None
    if expects:
        missing = [e for e in expects if e not in out]
        verdict = 'PASS' if not missing else f'FAIL(未出现: {missing})'
        print(f'[{name}] 结果: {verdict}', flush=True)

    # 收尾:off 断电 | reset 重启回提示符 | none 保持现状(兼容旧的 reset_after 布尔)
    after = t.get('after', 'reset' if t.get('reset_after') else 'none')
    if after == 'off':
        print(f'[{name}] 断电收尾(after=off)', flush=True)
        power.power_off(cfg)
        print(f'[{name}] 已断电,流程结束', flush=True)
    elif after == 'reset':
        print(f'[{name}] 输出结束,重启回提示符(after=reset)', flush=True)
        power.do_reset(cfg)
    if verdict is not None and not verdict.startswith('PASS'):
        sys.exit(1)
