"""常驻捕获域:一条读线程把通道字节持续解码进捕获日志,等待 = 水位 +
谓词 + 条件变量唤醒(不轮询)。捕获与等待解耦之后:

- 阶段间隙的字节不丢——不必等谁开始读,字节先落日志,等待者从自己的
  水位起算(旧模型里这个角色由内核 socket 缓冲兼任;水位上移到用户态,
  "从哪起算"从调用纪律变成接口语义);
- fd 借出(loady 的 Ymodem)经 park/resume 与捕获线程握手:借出期间的
  协议字节归借用方,不进日志;resume 后通道里剩余的字节无缝接上;
- 出站仍走通道直写(单写者在调用线程);设备对输入的回显是入站字节,
  自然进日志。

读侧唯一归捕获线程,写侧唯一归调用线程——通道对象本身不碰。
"""
import codecs
import threading
import time


class ConsoleStream:
    """常驻捕获流:读线程 + 捕获日志 + 水位等待;写与 fd 借出直通底层通道"""

    def __init__(self, channel):
        self.channel = channel          # SerialChannel 形状(read/write/fd)
        self._cond = threading.Condition()
        self._log = ''                  # 捕获日志(解码后的累计文本)
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self._thread = None
        self._stop = False
        self._parked = False            # fd 借出期:读线程让位
        self._paused = False            # 读线程已确认退出 read(借出方握手)
        self._error = None              # 读线程的致命错误(桥断开等),等待者代抛

    # ---- 生命周期 ----
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
                data = self.channel.read(256)   # 不持锁读,append 时再上锁
                if data:
                    with self._cond:
                        text = self._decoder.decode(data)
                        if text:
                            self._log += text
                            self._cond.notify_all()
        except Exception as e:   # 桥断开/通道异常:等待者不该干等超时,代抛
            with self._cond:
                self._error = e
                self._cond.notify_all()

    # ---- 出站与 fd(直通通道;读侧唯一归捕获线程) ----
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

    # ---- 捕获日志与等待 ----
    def mark(self):
        """当前水位:此后 text()/wait() 从这里起算"""
        with self._cond:
            return len(self._log)

    def text(self, since):
        """取水位以来的窗口文本(快照)"""
        with self._cond:
            return self._log[since:]

    def wait(self, pred, since, timeout, on_chunk=None):
        """从水位 since 起等待谓词成立:新字节即唤醒(条件变量,不轮询)。
        返回 (窗口文本, 是否在超时内命中)。谓词也可表达时间条件
        (如止损续收窗口的到期)——到期由 timeout 兜底唤醒。
        on_chunk:等待期间对新到文本的回调,在调用线程上下文执行且不持锁
        ——回调里可安全打印,打印阻塞不会拖住读线程。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            cursor = since
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
                if on_chunk is not None and len(self._log) > cursor:
                    chunk = self._log[cursor:]
                    cursor = len(self._log)
                    self._cond.release()      # 回调不持锁
                    try:
                        on_chunk(chunk)
                    finally:
                        self._cond.acquire()
                    continue                  # 回调后重查谓词/超时
                if deadline is not None:
                    self._cond.wait(min(rem, 0.5))
                else:
                    self._cond.wait(0.5)

    def clear(self):
        """清空捕获日志并重置解码残态(静默上电前丢弃断电噪声)。
        此前的水位全部作废——调用方须保证没有在途等待者"""
        with self._cond:
            self._log = ''
            self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    # ---- fd 借出配合(loady 的 Ymodem) ----
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
