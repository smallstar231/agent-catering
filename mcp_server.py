# MCP 服务端（把本项目的知识库/FAQ/搜索能力暴露为 MCP 工具，供外部 AI Agent 调用）
# 运行（stdio 模式，供本地 MCP 客户端 / 支持 MCP 的客户端连接）：
#   .venv/Scripts/python -m mcp_server
# 或 SSE 模式：
#   .venv/Scripts/python -m mcp_server --transport sse --port 8765
#
# 例：任何 MCP 客户端（Claude Desktop / Cursor / 自写客户端）连上来后，
#     会看到 faq_lookup / kb_search / web_search 三个工具，可直接调用你的苍穹外卖知识。

import argparse
import sys

from mcp.server.fastmcp import FastMCP

# 创建 MCP 服务实例（工具名前缀 kb_ 避免与客户端自带工具冲突）
mcp = FastMCP("sky-takeout-agent")


# ---- 工具 1：FAQ 精确问答（复用 agent/tools/faq_tool 的现成逻辑）----
@mcp.tool()
def faq_lookup(question: str) -> str:
    """从苍穹外卖 FAQ 库精确查找答案。当询问下单/支付/配送/退款/会员等高频问题时返回准确 Q&A；未命中返回空串。"""
    from agent.tools.faq_tool import faq_lookup as _f
    return _f(question)


# ---- 工具 2：知识库语义检索（复用 RAG）----
@mcp.tool()
def kb_search(query: str) -> str:
    """从苍穹外卖知识库做语义检索并总结。适合菜品介绍、运营规则、政策等非 FAQ 型知识问题。"""
    from agent.tools.agent_tools import rag_sky
    return rag_sky.rag_summarize(query, with_cite=True)


# ---- 工具 3：联网搜索（复用 web_search）----
@mcp.tool()
def web_search(query: str) -> str:
    """联网搜索实时信息（Tavily）。未配置 TAVILY_API_KEY 时返回"联网未启用"提示。"""
    from agent.tools.web_search import web_search as _w
    return _w(query)


def main():
    parser = argparse.ArgumentParser(description="苍穹外卖 MCP 服务端")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8765, help="SSE 模式端口")
    args = parser.parse_args()

    if args.transport == "sse":
        # SSE 模式：FastMCP 走 sse-starlette，监听指定端口
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Mount
        from mcp.server.sse import SseServerTransport
        # mcp 1.x 的 SSE 挂载方式：
        from starlette.applications import Starlette as _SA
        # 简便路径：直接 run
        print(f"[MCP] SSE 模式启动 :{args.port}（{mcp.name}）")
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        print(f"[MCP] stdio 模式启动（{mcp.name}），等待客户端连接...")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
