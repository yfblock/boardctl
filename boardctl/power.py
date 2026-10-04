"""电源域:纯电源动作(on/off/status),绝不碰串口——
"开机进入可交互态"(冷启动等提示符/静默上电)是板卡域 board.py 的事,
它组合本域与串口域完成;断电→延时→上电的节拍编排也在板域(显示 tap
要挂在上电前),本域只持有节拍值(reset_delay)。Power 即本域的面向对象
抽象:包住经 [power].method 选中的 PowerDevice 插件实例,统一错误包装
——插件层多态 = 不同子类同一接口;域门面多态 = 调用方(Board/cli/
runner/mcp)只见 Power,不见插件。
"""
import sys


class Power:
    """一块板的电源:包一个 PowerDevice 插件实例,统一错误包装与子命令语义"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.method = cfg.power.method   # defaults to command (declared in schema)
        from .plugins import POWER   # function-local import: avoids a board→power→plugins→plugin→board cycle
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

    @property
    def reset_delay(self):
        """断电→上电间隔秒数(冷启动/重启/静默上电共用的节拍值;
        节拍编排 off→延时→on 在板域 board.py)"""
        return self.cfg.power.reset_delay

    def status(self):
        """查询状态;返回 bool,无法解析(如 command 插件)时返回 None"""
        try:
            val = self.device.status()
        except SystemExit:
            raise
        except Exception as e:
            sys.exit(f'查询电源状态失败({self.desc}): {e}')
        return None if val is None else bool(val)
