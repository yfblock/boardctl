"""开发板域:一块具体的板。对应配置文件里的 [serial]/[power]/[console] 段——
板包含一截串口通道、一个常驻捕获流、一个电源对象与一个控制台对象(组合,
与配置结构一致;控制台是什么载荷由 [console].prompt 决定:U-Boot、Linux
shell、其他 CLI),承载"开机进入可交互态"的流程(冷启动等提示符 / 静默
上电)与控制台会话工厂。
会话与传输插件都在板的捕获流上工作(借用);整轮 run 一条连接:读侧唯一
归捕获线程,写侧由调用线程直写通道,fd 借出经 park/resume 让位。
依赖方向:board → {power, serial, stream, console};禁止反向。
"""
import sys
import time

from .console import Console
from .power import Power
from .serial import SerialChannel
from .stream import ConsoleStream


class Board:
    """一块板 = 串口 + 常驻捕获流 + 电源 + 控制台;上下文管理器:
    进入起捕获线程,退出停线程、关串口"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg['name']
        self.serial = SerialChannel.from_cfg(cfg)   # 一块板 ↔ 一截串口([serial] 段)
        self.stream = ConsoleStream(self.serial)    # 读侧唯一归捕获线程
        self.power = Power(cfg)                     # 一块板 ↔ 一个电源([power] 段)
        self.console = Console.from_cfg(cfg)        # 一块板 ↔ 一个控制台([console] 段)

    def __enter__(self):
        self.stream.start()
        return self

    def __exit__(self, *exc):
        self.stream.stop()
        self.serial.close()

    @property
    def prompt(self):
        """控制台提示符(执行结束判定依据)——常用捷径"""
        return self.console.prompt

    def session(self):
        """在板的常驻捕获流上开一个控制台会话(借用,不持有)"""
        return self.console.session(self.stream)

    def cold_boot(self, boot_timeout=60):
        """断电 → 上电 → 轮询等待控制台提示符(从任意状态回到干净可交互态,
        不论载荷是 U-Boot、Linux shell 还是其他 CLI)。启动输出留在捕获
        日志里,不被轮询消费丢弃。轮询会周期性向串口发 Ctrl-C 清残留
        输入——不可用于被动观察"""
        self.power.reset()   # off -> reset_delay -> on(节拍统一在电源域)
        print('等待控制台提示符...', flush=True)
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            if self.console.interactive_ready(self.session(), timeout=6):
                return
            time.sleep(2)
        sys.exit(f'上电后 {boot_timeout} 秒内未等到控制台提示符')

    def quiet_boot(self):
        """静默上电(mode=watch 被动模式):断 → 延时 → 清噪 → 合,
        全程不向串口写入一个字节——板子自己跑自动流程,任何写入都会打断它
        (故不能复用 cold_boot:轮询等提示符会周期性发 Ctrl-C)。
        清噪 = 内核缓冲 drain + 捕获日志 clear:上电后收到的第一个字节
        就是启动输出(捕获日志的起点即上电)"""
        delay = float(self.cfg['power'].get('reset_delay', 3))
        print('断电...', flush=True)
        self.power.off()
        time.sleep(delay)
        self.serial.drain()     # 内核接收缓冲里的断电噪声
        self.stream.clear()     # 捕获日志与解码残态:观察起点 = 上电
        print('上电(静默,不写串口)...', flush=True)
        self.power.on()
