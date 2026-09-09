# MCP 客户端 → LangChain 工具适配器
# 功能：连接一个 MCP 服务器（stdio 或 http(s) SSE），把它的工具动态转成本项目 Agent 可调用的 LangChain @tool
# 用法：
#   from agent.tools.mcp_client_tool import build_mcp_tools
#   extra_tools = build_mcp_tools()   # 连 config 里配置的 MCP server
# 说明：
#   - 默认 stdio 模式启动本仓库的 mcp_server.py（见 config/agent.yml 的 mcp_server 段）；
#   - 也可配置成远程 SSE 地址，连接任意 MCP 服务商工具。
#   - 连接失败/未配置时返回 []，不影响主 Agent 启动。

import os
from utils.logger_handler import logger
from utils.config_handler import agent_conf


def _server_command() -> list[str]:
    """返回启动本地 MCP server 的命令（python -m mcp_server）"""
    # 用当前 venv 的解释器
    import sys
    return [sys.executable, "-m", "mcp_server"]


def _remote_url() -> str | None:
    """配置的远程 MCP SSE 地址；未配置返回 None"""
    try:
        return (agent_conf.get("mcp_server") or {}).get("url") or None
    except Exception:
        return None


async def _connect_and_list(session) -> list:
    """列出一个已初始化 session 的工具"""
    tools = await session.list_tools()
    return list(tools.tools)


def build_mcp_tools(remote_url: str | None = None) -> list:
    """
    连接 MCP server 并把其工具封装为 LangChain 可调用函数列表。
    本地 stdio：remote_url=None 时启动 mcp_server.py。
    远程 SSE：remote_url 形如 http://host:port/mcp（mcp 1.x sse 端点）。
    返回：list[callable]，每个是同步函数 (str)->str；失败返回 []。
    注意：Agent 调用是同步的，这里用 asyncio.run 包一层做同步桥接（每个工具调用一次连接）。
    """
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client

    if remote_url is None:
        remote_url = _remote_url()

    tools_registry: list[dict] = []

    async def _fetch_tools():
        if remote_url:
            async with sse_client(remote_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ts = await session.list_tools()
                    return ts.tools
        else:
            import sys
            params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"], env=None)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ts = await session.list_tools()
                    return ts.tools

    try:
        tools = asyncio.run(_fetch_tools())
    except Exception as e:
        logger.warning(f"[mcp_client]连接 MCP server 失败：{str(e)[:150]}，跳过（返回空工具）")
        return []

    # 把每个 MCP 工具包成同步闭包
    langchain_tools = []

    def _make(name: str, description: str):
        def _call(*, question: str = ""):
            # 通用调用：工具大多单字符串入参；复杂结构在此退化为 json 字符串透传
            import asyncio, json

            async def _invoke():
                if remote_url:
                    async with sse_client(remote_url) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            return await session.call_tool(name, {"question": question})
                else:
                    import sys
                    from mcp import StdioServerParameters
                    from mcp.client.stdio import stdio_client
                    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"], env=None)
                    async with stdio_client(params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            return await session.call_tool(name, {"question": question})

            try:
                resp = asyncio.run(_invoke())
                if resp.content:
                    # 拼接文本结果
                    parts = []
                    for c in resp.content:
                        if hasattr(c, "text"):
                            parts.append(c.text)
                        else:
                            parts.append(str(c))
                    return "\n".join(parts)
                return f"[{name}] 无返回内容"
            except Exception as e:
                logger.error(f"[mcp_client]调用 {name} 失败：{str(e)[:150]}")
                return f"[{name}] 调用失败：{str(e)[:120]}"
        return _call

    for t in tools:
        # 描述避免与内置工具重名/冲突
        desc = (t.description or f"MCP 工具 {t.name}")
        fn = _make(t.name, desc)
        # 用 StructuredTool 显式命名并绑定入参 question（用显式签名函数而非 lambda，保证 schema 字段名正确）
        from langchain_core.tools import StructuredTool
        def _bound(question: str = "", _fn=fn) -> str:
            """调用外部 MCP 工具（入参统一为 question 字符串）"""
            return _fn(question=question)
        wrapper = StructuredTool.from_function(
            name=f"mcp_{t.name}",
            description=f"MCP 工具（来自外部 MCP 服务）：{desc}。入参 question 为问题/关键词字符串。",
            func=_bound,
        )
        langchain_tools.append(wrapper)
        logger.info(f"[mcp_client]已挂载外部 MCP 工具：mcp_{t.name}")

    return langchain_tools


if __name__ == '__main__':
    # 测试：列出并调用本地 MCP server 的 faq_lookup
    tools = build_mcp_tools()
    print("挂载工具数:", len(tools))
    for t in tools:
        print("  -", t.name)
    if tools:
        for t in tools:
            if t.name == "mcp_faq_lookup":
                print(t.invoke({"question": "配送要多久"}))
