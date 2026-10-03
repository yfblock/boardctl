"""开发板域:一块具体的板。对应配置文件里的 [serial]/[power]/[uboot] 段——
板包含一截串口通道与一个电源对象(组合,与配置结构一致),承载"开机进入
可交互态"的流程(冷启动等提示符 / 静默上电)与 U-Boot 会话工厂。
会话与传输插件都用板自己的通道(借用),整轮 run 一条连接。
依赖方向:board → {power, serial, session};禁止反向。
"""
import sys
import time

from .power import Power
from .serial import SerialChannel
from .session import UbootSession


class Board:
    """一块板 = 一截串口 + 一个电源 + U-Boot 提示符;上下文管理器关串口"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg['name']
        self.prompt = cfg['uboot']['prompt']
        self.serial = SerialChannel.from_cfg(cfg)   # 一块板 ↔ 一截串口([serial] 段)
        self.power = Power(cfg)                     # 一块板 ↔ 一个电源([power] 段)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.serial.close()

    def session(self):
        """在板自己的串口通道上开一个 U-Boot 会话(借用,不关通道)"""
        return UbootSession(self.serial, self.prompt)

    def cold_boot(self, boot_timeout=60):
        """断电 → 上电 → 轮询等待 U-Boot 提示符(从任意状态回到干净提示符)。
        会周期性向串口发 Ctrl-C 清残留输入——不可用于被动观察"""
        delay = float(self.cfg['power'].get('reset_delay', 3))
        print('断电...', flush=True)
        self.power.off()
        time.sleep(delay)
        print('上电,等待 U-Boot 提示符...', flush=True)
        self.power.on()
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            if self.session().wait_prompt(timeout=6)[0]:
                return
            time.sleep(2)
        sys.exit(f'上电后 {boot_timeout} 秒内未等到 U-Boot 提示符')

    def quiet_boot(self):
        """静默上电(exec=watch 被动模式):断 → 延时 → 清噪 → 合,
        全程不向串口写入一个字节——板子自己跑自动流程,任何写入都会打断它
        (故不能复用 cold_boot:轮询等提示符会周期性发 Ctrl-C)。
        调用前会话须已挂在板的通道上;断电期噪声在合闸前清掉,
        保证之后收到的第一个字节就是启动输出"""
        delay = float(self.cfg['power'].get('reset_delay', 3))
        print('断电...', flush=True)
        self.power.off()
        time.sleep(delay)
        self.serial.drain()
        print('上电(静默,不写串口)...', flush=True)
        self.power.on()
