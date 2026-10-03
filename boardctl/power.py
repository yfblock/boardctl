"""电源域:纯电源动作(on/off/status),绝不碰串口——
"开机进入可交互态"(冷启动等提示符/静默上电)是板卡域 board.py 的事,
它组合本域与串口域完成。Power 即本域的面向对象抽象:包住经 [power].method
选中的 PowerDevice 插件实例,统一错误包装——插件层多态 = 不同子类同一
接口;域门面多态 = 调用方(Board/cli/runner/mcp)只见 Power,不见插件。
"""
import sys
import time


class Power:
    """一块板的电源:包一个 PowerDevice 插件实例,统一错误包装与子命令语义"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.method = cfg['power'].get('method') or 'command'   # 未配置时默认命令插件
        from .plugins import POWER   # 函数内 import:避免 board→power→plugins→插件→board 环
        cls = POWER.get(self.method)
        if cls is None:
            sys.exit(f'未知电源插件 {self.method!r},可用: {" ".join(sorted(POWER)) or "(无)"}')
        self.device = cls(cfg)

    @property
    def desc(self):
        return f'插件 {self.method}'

    def on(self):
        try:
            self.device.on()
        except SystemExit:
            raise
        except Exception as e:
            sys.exit(f'上电失败({self.desc}): {e}')

    def off(self, check=True) -> bool:
        """断电;check=False 时不因失败退出进程,改为返回 False"""
        try:
            self.device.off()
            return True
        except SystemExit:
            raise
        except Exception as e:
            print(f'断电失败({self.desc}): {e}', file=sys.stderr)
            if check:
                sys.exit(1)
            return False

    def status(self):
        """查询状态;返回 bool,无法解析(如 command 插件)时返回 None"""
        try:
            val = self.device.status()
        except SystemExit:
            raise
        except Exception as e:
            sys.exit(f'查询电源状态失败({self.desc}): {e}')
        return None if val is None else bool(val)

    def apply(self, state):
        """power 子命令语义:status 打印开/关;on/off 执行动作;完成即 exit(0)"""
        if state == 'status':
            val = self.status()
            if val is not None:
                print('开' if val else '关')
            sys.exit(0)
        (self.on if state == 'on' else self.off)()
        sys.exit(0)

    def reset(self):
        """断电重启(after=reset 收尾用):off -> reset_delay -> on"""
        delay = float(self.cfg['power'].get('reset_delay', 3))
        print('断电...', flush=True)
        self.off()
        time.sleep(delay)
        print('上电...', flush=True)
        self.on()
        print(f'已重启(如需看启动输出: boardctl -b {self.cfg["name"]} console)')
