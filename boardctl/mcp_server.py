"""boardctl MCP server:把 ls / run / 电源状态暴露为 MCP 工具,供 Claude 等客户端调用。

安装(pip install 'boardctl[mcp]')后注册:
  claude mcp add boardctl -- boardctl-mcp
工具会真实控制硬件电源(自动开关机),docstring 已注明。
"""
import functools

from . import power, runner
from .config import available_boards, load_board

try:
    try:
        from mcp.server.mcpserver import MCPServer as FastMCP   # mcp 2.x(FastMCP 更名)
    except ImportError:
        from mcp.server.fastmcp import FastMCP                  # mcp 1.x
except ImportError as e:  # pragma: no cover
    raise SystemExit('缺少 MCP 依赖,请安装 extras: pip install "boardctl[mcp]"') from e

mcp = FastMCP('boardctl')

MAX_SHOW_ROUNDS = 3   # run_target 结果最多展示的轮数(全量 output_tail 见返回)


def _tool_guard(fn):
    """底层 API 大量使用 sys.exit 报错;SystemExit 是 BaseException,
    逃进 MCP 2.x 的工具协程会拖垮整个 server——统一转为错误文本。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SystemExit as e:
            msg = e.code if isinstance(e.code, str) else f'exit {e.code}'
            return f'错误: {msg}'
    return wrapper


def _format_round(r):
    head = f"第 {r['round']} 轮: {'PASS' if r['pass'] else 'FAIL'}" \
           + (f"({r['error']})" if r.get('error') else '')
    return head + '\n' + r.get('output_tail', '')


@mcp.tool()
@_tool_guard
def ls_boards() -> str:
    """列出已配置的开发板(来自 ~/.config/boardctl/boards/)及各自的启动目标。"""
    lines = []
    for name in sorted(available_boards()):
        cfg = load_board(name)
        lines.append(f"{name} — {cfg.get('description', '')}")
        for k, t in cfg.get('run', {}).items():
            lines.append(f"  目标 {k}: {t.get('desc', '')} "
                         f"(exec={t.get('exec', 'none')}, method={t.get('method', 'tftp')})")
    return '\n'.join(lines) or '(没有配置任何板卡;模板见包内置 example.toml)'


@mcp.tool()
@_tool_guard
def power_status(board: str) -> str:
    """查询开发板电源状态(开/关);command 电源插件无法解析时返回"未知"。只读,无副作用。"""
    val = power.power_status(load_board(board))
    return '未知(该板的电源插件无法解析状态)' if val is None else ('开' if val else '关')


@mcp.tool()
@_tool_guard
def run_target(board: str, target: str, repeat: int = 1) -> str:
    """在开发板上执行一键全流程测试:自动开机→传输(TFTP/Ymodem)→执行(go/source/booti)
    →输出断言→自动关机。repeat>1 为多轮压测。

    注意:会真实控制硬件电源;每轮约 15-60 秒。
    返回每轮 PASS/FAIL、断言详情与串口输出尾部。"""
    result = runner.run_collect(load_board(board), target, repeat)
    if 'error' in result:
        return (f"错误: {result['error']}\n"
                f"可用目标: {', '.join(result.get('available', [])) or '(无)'}")
    summary = (f"汇总: {result['passed']}/{result['repeat']} 轮 PASS"
               + (' ✅' if result['all_pass'] else ' ❌'))
    shown = '\n\n'.join(_format_round(r) for r in result['rounds'][:MAX_SHOW_ROUNDS])
    extra = (f"\n\n(仅展示前 {MAX_SHOW_ROUNDS} 轮,共 {result['repeat']} 轮)"
             if result['repeat'] > MAX_SHOW_ROUNDS else '')
    return f'{summary}\n\n{shown}{extra}'


def main():
    mcp.run()   # stdio 传输


if __name__ == '__main__':
    main()
