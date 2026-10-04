"""Console domain: the interactive payload running on the board — U-Boot,
a Linux shell, any other CLI. boardctl has exactly one convention about the
console: an interactive session with a prompt (prompt configurable, Ctrl-C
can interrupt the current input line); everything prompt-driven (waiting for
the prompt/executing commands/collecting output) unfolds on the resident
capture stream's watermarks (stream.py) — the session only decides "where
to count from, what to write, what to wait for"; byte reading belongs
uniformly to the capture thread. U-Boot-specific load addresses, serverip,
tftpboot/loady commands don't belong here — they live in the [uboot] config
section and in transport plugins/cmd templates.
"""


class Console:
    """A board's console: prompt + session factory + interactive-state check"""

    def __init__(self, prompt):
        self.prompt = prompt

    @classmethod
    def from_cfg(cls, cfg):
        return cls(cfg.console.prompt)

    def session(self, stream):
        """Open a console session on the board's resident capture stream (borrowed, not owned)"""
        return ConsoleSession(stream, self.prompt)

    def interactive_ready(self, session, timeout=6):
        """Whether the system has reached an interactive state after power-on (prompt responds)"""
        return session.wait_prompt(timeout=timeout)[0]


class ConsoleSession:
    """Prompt session on a resident capture stream (borrows the stream,
    doesn't own it).

    The watermark is taken before writing: an old prompt already lying in
    the log naturally falls outside the window — the old model relied on the
    calling discipline of "already at the prompt when entering", now it's
    interface semantics. cmd only suits mid-flow commands that return to the
    prompt (environment prep/file pulls); the final instruction of a boot
    payload (which may never come back) belongs to runner's streaming
    engine."""

    def __init__(self, stream, prompt):
        self.stream = stream
        self.prompt = prompt

    def read_until(self, pattern, timeout):
        """Wait until pattern appears in the window text; returns (accumulated text, whether it hit)"""
        since = self.stream.mark()
        return self.stream.wait(lambda text: pattern in text, since, timeout)

    def wait_prompt(self, timeout=8):
        """First Ctrl-C to clear any leftover unfinished input line
        (quote/continuation state), then wait for the prompt; returns
        (whether it succeeded, text received meanwhile)"""
        since = self.stream.mark()
        self.stream.write(b'\x03\r')
        text, hit = self.stream.wait(lambda text: self.prompt in text, since, timeout)
        return hit, text

    def cmd(self, cmdline, timeout=30):
        """Execute one mid-flow command, collecting output up to the next
        prompt; returns (output, whether the prompt arrived) — on timeout
        the output is truncated, the caller uses False to tell "didn't get
        it all\" from \"got it all but without the expected content\""""
        since = self.stream.mark()
        self.stream.write(cmdline + '\r')
        return self.stream.wait(lambda text: self.prompt in text, since, timeout)
