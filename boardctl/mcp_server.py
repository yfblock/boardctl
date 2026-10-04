"""boardctl MCP server: exposes ls / run / power status as MCP tools for
clients like Claude.

After installing (pip install 'boardctl[mcp]'), register:
  claude mcp add boardctl -- boardctl-mcp
The tools really control the hardware power (auto power on/off), as noted in
their docstrings.
"""
import functools

from . import power, runner
from .config import available_boards, load_board

try:
    try:
        from mcp.server.mcpserver import MCPServer as FastMCP   # mcp 2.x (FastMCP renamed)
    except ImportError:
        from mcp.server.fastmcp import FastMCP                  # mcp 1.x
except ImportError as e:  # pragma: no cover
    raise SystemExit('MCP dependency missing, install the extra: pip install "boardctl[mcp]"') from e

mcp = FastMCP('boardctl')

MAX_SHOW_ROUNDS = 3   # max rounds shown in run_target results (full output_tail is in the return)


def _tool_guard(fn):
    """The underlying APIs lean heavily on sys.exit for errors; SystemExit is
    a BaseException and would drag the whole MCP 2.x tool coroutine down if it
    escaped — uniformly converted to error text here."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SystemExit as e:
            msg = e.code if isinstance(e.code, str) else f'exit {e.code}'
            return f'error: {msg}'
    return wrapper


def _format_round(r):
    head = (f"round {r['round']}: {'PASS' if r['pass'] else 'FAIL'}"
         + (f", end={r.get('ended', '?')}" if r.get('ended') else '')
         + (f"({r['error']})" if r.get('error') else ''))
    return head + '\n' + r.get('output_tail', '')


@mcp.tool()
@_tool_guard
def ls_boards() -> str:
    """List configured dev boards (from ~/.config/boardctl/) and their boot targets."""
    lines = []
    for name in sorted(available_boards()):
        cfg = load_board(name)
        lines.append(f"{name} — {cfg.description}")
        for k, t in cfg.run.items():
            lines.append(f"  target {k}: {t.desc or ''} "
                         f"(cmd={t.cmd or t.mode or '(load only)'}, method={t.method or 'tftp'})")
    return '\n'.join(lines) or '(no boards configured; see the bundled example.toml for a template)'


@mcp.tool()
@_tool_guard
def power_status(board: str) -> str:
    """Query a dev board's power state (on/off); returns "unknown" when the command power plugin cannot parse it. Read-only, no side effects."""
    val = power.Power(load_board(board)).status()
    return 'unknown (this board\'s power plugin cannot parse the state)' if val is None else ('on' if val else 'off')


@mcp.tool()
@_tool_guard
def run_target(board: str, target: str, repeat: int = 1) -> str:
    """Run the one-shot full test flow on a dev board: auto power-on → transport (TFTP/Ymodem) → execute (go/source/booti)
    → output assertions → auto power-off. repeat>1 is a multi-round stress run.

    Note: really controls the hardware power; each round takes ~15-60 seconds.
    Returns per-round PASS/FAIL, assertion details and the tail of serial output."""
    result = runner.run_collect(load_board(board), target, repeat)
    if 'error' in result:
        return (f"error: {result['error']}\n"
                f"available targets: {', '.join(result.get('available', [])) or '(none)'}")
    summary = (f"summary: {result['passed']}/{result['repeat']} rounds PASS"
               + (' ✅' if result['all_pass'] else ' ❌'))
    shown = '\n\n'.join(_format_round(r) for r in result['rounds'][:MAX_SHOW_ROUNDS])
    extra = (f"\n\n(showing the first {MAX_SHOW_ROUNDS} of {result['repeat']} rounds)"
             if result['repeat'] > MAX_SHOW_ROUNDS else '')
    return f'{summary}\n\n{shown}{extra}'


def main():
    mcp.run()   # stdio transport


if __name__ == '__main__':
    main()
