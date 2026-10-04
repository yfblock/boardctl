"""常驻捕获域:一条读线程把通道字节持续解码进捕获日志,等待 = 水位 +
谓词 + 条件变量唤醒(不轮询)。捕获与等待解耦之后:

- 阶段间隙的字节不丢——不必等谁开始读,字节先落日志,等待者从自己的
  水位起算(旧模型里这个角色由内核 socket 缓冲兼任;水位上移到用户态,
  "从哪起算"从调用纪律变成接口语义);
- 显示挂在捕获事件上(tap):捕到新文本即在读线程上下文回调——上电起
  的一切(启动日志/命令回显/执行输出)自然上屏,不靠各等待者自己打印;
  摘下前放完积压(显示无缺口),重挂不回放断电窗口的字节(线路噪声
  不补屏);断电窗口由 Board 摘下 tap;
- fd 借出(loady 的 Ymodem)经 park/resume 与捕获线程握手:借出期间的
  协议字节归借用方,不进日志;resume 后通道里剩余的字节无缝接上;
- 出站仍走通道直写(单写者在调用线程);设备对输入的回显是入站字节,
  自然进日志(也自然上屏)。

读侧唯一归捕获线程,写侧唯一归调用线程——通道对象本身不碰。
"""
import codecs
import threading
import time


class ConsoleStream:
    """常驻捕获流:读线程 + 捕获日志 + 水位等待;写与 fd 借出直通底层通道"""

    def __init__(self, channel):
        self.channel = channel          # SerialChannel shape (read/write/fd)
        self._cond = threading.Condition()
        self._log = ''                  # capture log (accumulated decoded text)
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self._thread = None
        self._stop = False
        self._parked = False            # fd-lend period: reader thread stands down
        self._paused = False            # reader confirmed out of read (handshake with the borrower)
        self._error = None              # fatal reader error (bridge down etc.), re-raised on waiters
        self._tap = None                # display callback: shown as captured, in the reader thread
        self._shown = 0                 # display watermark: log length already fed to the tap

    # ---- lifecycle ----
    def start(self):
        if self._thread is not None:
            return
        self._stop = False
        self._thread = threading.Thread(target=self._pump, name='boardctl-console',
                                        daemon=True)
        self._thread.start()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _pump(self):
        try:
            while True:
                with self._cond:
                    if self._stop:
                        return
                    if self._parked:
                        self._paused = True
                        self._cond.notify_all()
                        while self._parked and not self._stop:
                            self._cond.wait(0.5)
                        self._paused = False
                        if self._stop:
                            return
                        continue
                data = self.channel.read(256)   # read without the lock; re-acquire to append
                if data:
                    tap, chunk = None, ''   # decode may be empty (multi-byte char split across reads)
                    with self._cond:
                        text = self._decoder.decode(data)
                        if text:
                            self._log += text
                            chunk = self._log[self._shown:]
                            self._shown = len(self._log)
                            tap = self._tap
                            self._cond.notify_all()
                    if tap is not None and chunk:
                        try:
                            tap(chunk)  # callback without the lock: slow display can't stall waiters/lend handshake
                        except Exception:
                            pass        # a display fault must not kill the capture thread
        except Exception as e:   # bridge down/channel error: waiters shouldn't sit out the timeout, re-raise
            with self._cond:
                self._error = e
                self._cond.notify_all()

    # ---- outbound & fd (straight to the channel; the read side belongs solely to the capture thread) ----
    def write(self, data):
        """写字节到通道;设备对输入的回显会作为入站字节自然进捕获日志"""
        if isinstance(data, str):
            data = data.encode()
        self.channel.write(data)

    @property
    def fd(self):
        return self.channel.fd

    def blocking_fd(self):
        return self.channel.blocking_fd()

    # ---- capture log & waiting ----
    def mark(self):
        """当前水位:此后 text()/wait() 从这里起算"""
        with self._cond:
            return len(self._log)

    def text(self, since):
        """取水位以来的窗口文本(快照)"""
        with self._cond:
            return self._log[since:]

    def wait(self, pred, since, timeout):
        """从水位 since 起等待谓词成立:新字节即唤醒(条件变量,不轮询)。
        返回 (窗口文本, 是否在超时内命中)。谓词也可表达时间条件
        (如止损续收窗口的到期)——到期由 timeout 兜底唤醒。
        显示不在此处:挂在捕获事件上(set_tap),等待者只管谓词。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                text = self._log[since:]
                if pred(text):
                    return text, True
                if self._error is not None:
                    raise self._error
                if deadline is not None:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        return text, False
                    self._cond.wait(rem)
                else:
                    self._cond.wait(0.5)

    def set_tap(self, fn):
        """挂/摘显示回调(tap):fn(text) 在读线程上下文执行——捕到即显,
        "中断中显示";等待者只管谓词,不掺打印职责。
        摘下(fn=None)前先经旧回调放完未显示的积压——显示相对捕获无
        缺口;重挂不回放摘下期间的字节(断电噪声不补屏),从挂上那一刻
        起显示。回调异常被吞:显示故障不该毒害捕获线程与等待者。"""
        with self._cond:
            prev, backlog = self._tap, self._log[self._shown:]
            self._shown = len(self._log)
            self._tap = fn
        if prev is not None and backlog:
            try:
                prev(backlog)
            except Exception:
                pass

    def clear(self):
        """清空捕获日志并重置解码残态(静默上电前丢弃断电噪声)。
        此前的水位全部作废——调用方须保证没有在途等待者;未显示的积压
        一并丢弃(噪声不回放进显示)"""
        with self._cond:
            self._log = ''
            self._shown = 0
            self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    # ---- fd lending support (Ymodem for loady) ----
    def park(self):
        """借出前调用:读线程确认已退出 read 才返回——此后字节全归借用方,
        不进捕获日志"""
        with self._cond:
            self._parked = True
            while not self._paused and not self._stop and self._error is None:
                self._cond.wait(0.5)

    def resume(self):
        """归还后调用:读线程回到 read 循环,通道里剩余的字节无缝接上"""
        with self._cond:
            self._parked = False
            self._cond.notify_all()
