"""开发板域:一块具体的板。对应配置文件里的 [serial]/[power]/[console] 段——
板包含一截串口通道、一个常驻捕获流、一个电源对象与一个控制台对象(组合,
与配置结构一致;控制台是什么载荷由 [console].prompt 决定:U-Boot、Linux
shell、其他 CLI),承载"开机进入可交互态"的流程(冷启动等提示符 / 静默
上电)与控制台会话工厂。
会话与传输插件都在板的捕获流上工作(借用);整轮 run 一条连接:读侧唯一
归捕获线程,写侧由调用线程直写通道,fd 借出经 park/resume 让位。
显示(tap)生命周期也归板:上电前挂上(上电起的输出即捕即显——启动
日志/回显不再黑盒)、断电前摘下(线路噪声不上屏);程序化调用可把
显示出口换成缓冲(run_collect——设备字节不落服务进程的 stdout)。
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
    进入起捕获线程,退出停线程、关串口。显示(tap)上电前挂、断电前摘"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg['name']
        self.serial = SerialChannel.from_cfg(cfg)   # 一块板 ↔ 一截串口([serial] 段)
        self.stream = ConsoleStream(self.serial)    # 读侧唯一归捕获线程
        self.power = Power(cfg)                     # 一块板 ↔ 一个电源([power] 段)
        self.console = Console.from_cfg(cfg)        # 一块板 ↔ 一个控制台([console] 段)
        self._display = None    # 程序化显示出口(run_collect);None = stdout 实时

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

    # ---- 显示(tap):挂捕获事件,即捕即显 ----
    def set_display(self, out):
        """程序化调用(run_collect/MCP)换显示出口:设备输出写进 out 而
        非 stdout——服务进程(MCP)的 stdout 是协议通道,设备字节不得
        落上去"""
        self._display = out

    def _show(self, text):
        out = self._display if self._display is not None else sys.stdout
        out.write(text)
        out.flush()

    def _power_cycle(self, note=None):
        """断电 -> 延时 -> 上电(节拍值归电源域 reset_delay)。note 是
        上电前的提示行(冷启动的"等待控制台提示符"):提示先落屏、
        再挂显示、再上电——上电即出 SPL 字节,提示行才不会被撕进
        字节流中间,也不会晚于对串口的任何写入(轮询 Ctrl-C 在其后的
        等待循环里)。显示在断电前摘下、上电前挂上:上电起的输出
        即捕即显,断电窗口的线路噪声不上屏"""
        self.stream.set_tap(None)
        print('断电...', flush=True)
        self.power.off()
        time.sleep(self.power.reset_delay)
        print('上电...', flush=True)
        if note:
            print(note, flush=True)
        self.stream.set_tap(self._show)   # 提示已落屏,此后上电字节即捕即显
        self.power.on()

    def cold_boot(self, boot_timeout=60):
        """断电 → 上电 → 轮询等待控制台提示符(从任意状态回到干净可交互态,
        不论载荷是 U-Boot、Linux shell 还是其他 CLI)。启动输出即捕即显
        (tap 挂在上电前)——等待不再是黑盒。轮询会周期性向串口发 Ctrl-C
        清残留输入——不可用于被动观察"""
        self._power_cycle(note='等待控制台提示符...')
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
        就是启动输出(捕获与显示的起点都是上电)"""
        self.stream.set_tap(None)   # 断电窗口(含上轮残留):线路噪声不上屏
        print('断电...', flush=True)
        self.power.off()
        time.sleep(self.power.reset_delay)
        self.serial.drain()     # 内核接收缓冲里的断电噪声
        self.stream.clear()     # 捕获日志与解码残态:观察起点 = 上电
        # 提示先落屏再挂显示(同冷启动纪律):上电即出 SPL 字节,
        # 提示行不被撕进字节流中间
        print('上电(静默,不写串口)...', flush=True)
        self.stream.set_tap(self._show)
        self.power.on()

    def reboot(self):
        """断电重启回提示符(after=reset 收尾):冷启动同款节拍,不等
        提示符(由下一轮/用户接管);上电起的输出继续即捕即显"""
        self._power_cycle()

    def power_off(self):
        """断电(after=off 收尾):先摘显示再断电——断电后的线路噪声不上屏
        (摘下前放完积压,尾显不丢)"""
        self.stream.set_tap(None)
        self.power.off()
