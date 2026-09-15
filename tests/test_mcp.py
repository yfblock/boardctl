#!/usr/bin/env python3
"""MCP server 协议级冒烟(无需硬件):起 server、列工具、调用只读工具与错误路径。
用法:uv run --extra mcp python tests/test_mcp.py
"""
import asyncio
import os
import sys

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print('skip: 未安装 mcp extra')
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


async def main():
    params = StdioServerParameters(
        command=PY, args=['-m', 'boardctl.mcp_server'],
        cwd=ROOT, env={**os.environ, 'PYTHONPATH': ROOT})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {'ls_boards', 'power_status', 'run_target'} <= names, names

            r = await session.call_tool('ls_boards', {})
            text = r.content[0].text if r.content else ''
            assert 'example' in text or 'sg2002' in text, text  # 包内置示例或用户板

            # 错误路径(不触碰硬件)
            r = await session.call_tool('run_target', {'board': 'no-such', 'target': 'x'})
            ok = getattr(r, 'isError', False) or any(
                '未知开发板' in getattr(c, 'text', '') for c in (r.content or []))
            assert ok, r

            print('mcp tests: OK')


asyncio.run(main())
