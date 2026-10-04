"""Console domain: the board's interactive payload (U-Boot, a Linux shell,
any CLI) — one convention: an interactive session with a prompt.
Prompt-driven waiting/executing unfolds on the capture stream's watermarks;
byte reading belongs to the capture thread. U-Boot specifics (load
addresses, serverip, tftpboot/loady) live in [uboot] and plugins, not here."""


class Console:
    """A board's console: prompt + session factory + interactive-state check."""

    def __init__(self, prompt):
        self.prompt = prompt

    @classmethod
    def from_cfg(cls, cfg):
        return cls(cfg.console.prompt)

    def session(self, stream):
        """Open a console session on the board's resident capture stream (borrowed, not owned)."""
        return ConsoleSession(stream, self.prompt)

    def interactive_ready(self, session, timeout=6):
        """Whether the prompt responds after power-on."""
        return session.wait_prompt(timeout=timeout)[0]


class ConsoleSession:
    """Prompt session on a borrowed capture stream. The watermark is taken
    before writing, so an old prompt already in the log falls outside the
    window. cmd() suits mid-flow commands that return to the prompt; a
    payload's final instruction (which may never come back) belongs to
    runner's streaming engine."""

    def __init__(self, stream, prompt):
        self.stream = stream
        self.prompt = prompt

    def read_until(self, pattern, timeout):
        """Wait until pattern appears in the window text; returns (text, hit)."""
        since = self.stream.mark()
        return self.stream.wait(lambda text: pattern in text, since, timeout)

    def wait_prompt(self, timeout=8):
        """Ctrl-C to clear any leftover unfinished input line, then wait for
        the prompt; returns (hit, text received meanwhile)."""
        since = self.stream.mark()
        self.stream.write(b'\x03\r')
        text, hit = self.stream.wait(lambda text: self.prompt in text, since, timeout)
        return hit, text

    def cmd(self, cmdline, timeout=30):
        """Execute one mid-flow command, collecting output up to the next
        prompt; returns (output, hit) — on timeout the output is truncated,
        the caller tells "didn't get it all" from "got it all" via hit."""
        since = self.stream.mark()
        self.stream.write(cmdline + '\r')
        return self.stream.wait(lambda text: self.prompt in text, since, timeout)
