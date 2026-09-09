# 真实联网搜索工具
# 功能：通过 Tavily API 搜索网络实时信息，返回标题/链接/摘要
# 被 agent/react_agent.py 注册为工具，替代原来的"模拟天气/位置"等假工具覆盖不到的实时问题
# 设计：
#   - 用 httpx 直连 Tavily，不引入额外 SDK；
#   - 未配置 TAVILY_API_KEY 时返回友好提示（不抛错），Agent 可据此向用户说明"联网未开启"；
#   - 任一环节失败都返回错误文案字符串，绝不向 Agent 抛异常。

import os
import httpx
import utils.config_handler  # 副作用：触发 load_dotenv()，保证 .env 里的 key 先注入环境（本文件不读 config 但要读 TAVILY_API_KEY）
from utils.logger_handler import logger

TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_MAX_RESULTS = 5


def _get_key() -> str | None:
    """取 Tavily API key，缺省返回 None"""
    key = os.getenv("TAVILY_API_KEY", "").strip()
    return key or None


def web_search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> str:
    """
    联网搜索，返回格式化的文本结果（标题+链接+摘要）
    入参：query - 搜索关键词
    返回：字符串。未配置 key/失败时返回说明文本；成功时返回多条结果。
    """
    # 空/None 入参直接友好提示，避免打到 API 返回 400/422
    if not query or not str(query).strip():
        return "【联网搜索】请提供要搜索的关键词（query 不能为空）。"
    if max_results is None or int(max_results) <= 0:
        max_results = DEFAULT_MAX_RESULTS

    key = _get_key()
    if not key:
        return (
            "【联网搜索未启用】未配置 TAVILY_API_KEY，无法进行真实联网搜索。"
            "如需要实时信息，请在 .env 中配置 TAVILY_API_KEY 后重试。"
        )

    try:
        resp = httpx.post(
            TAVILY_ENDPOINT,
            json={
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": False,
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=20.0,
        )
        if resp.status_code != 200:
            logger.warning(f"[web_search]Tavily HTTP {resp.status_code}: {resp.text[:200]}")
            return f"【联网搜索失败】服务返回状态码 {resp.status_code}，请稍后重试。"

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return "【联网搜索】未找到与「" + query + "」相关的实时信息。"

        lines = [f"联网搜索「{query}」共找到 {len(results)} 条结果：", "-" * 50]
        for i, r in enumerate(results[:max_results], 1):
            title = r.get("title", "无标题")
            url = r.get("url", "")
            content = (r.get("content") or "").strip()
            lines.append(f"{i}. {title}")
            lines.append(f"   链接: {url}")
            if content:
                lines.append(f"   摘要: {content[:200]}")
        logger.info(f"[web_search]「{query}」返回 {len(results)} 条")
        return "\n".join(lines)
    except httpx.HTTPError as e:
        logger.error(f"[web_search]网络错误：{str(e)[:200]}")
        return f"【联网搜索失败】网络错误：{str(e)[:120]}"
    except Exception as e:
        logger.error(f"[web_search]未知错误：{str(e)[:200]}")
        return f"【联网搜索失败】{str(e)[:120]}"


if __name__ == '__main__':
    print(web_search("台风对外卖配送的影响"))
