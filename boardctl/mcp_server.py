"""boardctl MCP server: exposes ls / run / power status as MCP tools for
clients like Claude. After installing (pip install 'boardctl[mcp]'),
register: claude mcp add boardctl -- boardctl-mcp."""
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


def _tool_guard(fn):
    """The underlying APIs lean on sys.exit; SystemExit would drag the tool
    coroutine down — uniformly converted to error text."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SystemExit as e:
            msg = e.code if isinstance(e.code, str) else f'exit {e.code}'
            return f'error: {msg}'
    return wrapper


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
def run_target(board: str, target: str) -> str:
    """Run the one-shot full test flow on a dev board: auto power-on → transport (TFTP/Ymodem) → execute (go/source/booti)
    → output assertions → auto power-off.

    Note: really controls the hardware power; a run takes ~15-60 seconds.
    Returns PASS/FAIL, assertion details and the tail of serial output.
    For multi-round stress runs, call this tool repeatedly."""
    result = runner.run_collect(load_board(board), target)
    if 'error' in result:
        return (f"error: {result['error']}\n"
                f"available targets: {', '.join(result.get('available', [])) or '(none)'}")
    head = (('PASS' if result['pass'] else 'FAIL')
            + (f", end={result['ended']}" if result['ended'] else '')
            + (f"({result['error']})" if result['error'] else ''))
    return head + '\n\n' + result['output_tail']


def main():
    mcp.run()   # stdio transport


if __name__ == '__main__':
    main()
