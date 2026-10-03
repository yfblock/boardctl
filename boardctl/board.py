"""开发板域:一块具体的板。组合电源域与串口域,承载"开机进入可交互态"的
流程(冷启动等提示符 / 静默上电)与 U-Boot 会话工厂——这些原先住在
power.py 里,让电源域长出了串口知识;现在电源只管动作,开机流程归板卡。
依赖方向:board → {power, serial, session};禁止反向。
"""
import sys
import time

from . import power
from .session import UbootSession


class Board:
    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg['name']
        self.prompt = cfg['uboot']['prompt']

    def session(self):
        """打开一个 U-Boot 会话(串口通道随会话关闭)"""
        return UbootSession.from_cfg(self.cfg)

    def cold_boot(self, boot_timeout=60):
        """断电 → 上电 → 轮询等待 U-Boot 提示符(从任意状态回到干净提示符)。
        会周期性向串口发 Ctrl-C 清残留输入——不可用于被动观察"""
        delay = float(self.cfg['power'].get('reset_delay', 3))
        print('断电...', flush=True)
        power.power_off(self.cfg)
        time.sleep(delay)
        print('上电,等待 U-Boot 提示符...', flush=True)
        power.power_on(self.cfg)
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            with self.session() as s:
                ok, _ = s.wait_prompt(timeout=6)
                if ok:
                    return
            time.sleep(2)
        sys.exit(f'上电后 {boot_timeout} 秒内未等到 U-Boot 提示符')

    def quiet_boot(self, channel):
        """静默上电(exec=watch 被动模式):断 → 延时 → 清噪 → 合,
        全程不向串口写入一个字节——板子自己跑自动流程,任何写入都会打断它
        (故不能复用 cold_boot:轮询等提示符会周期性发 Ctrl-C)。
        channel: 已挂好的串口通道;断电期噪声在合闸前清掉,
        保证之后收到的第一个字节就是启动输出"""
        delay = float(self.cfg['power'].get('reset_delay', 3))
        print('断电...', flush=True)
        power.power_off(self.cfg)
        time.sleep(delay)
        channel.drain()
        print('上电(静默,不写串口)...', flush=True)
        power.power_on(self.cfg)
