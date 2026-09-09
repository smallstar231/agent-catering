# 中间件模块
# 功能：在 Agent 执行过程中插入自定义逻辑——工具监控、模型调用日志、动态提示词切换
# 被 agent/react_agent.py 导入，注册到 ReAct Agent 中
# 中间件 = 在"请求→处理→响应"的流程中插入额外逻辑（类似拦截器/钩子）

from typing import Callable  # 类型标注：可调用对象（函数）
from utils.prompt_loader import (load_system_prompts, load_report_prompts,
                                 load_system_prompts_sky, load_report_prompts_sky)  # 提示词加载器
from utils.config_handler import agent_conf  # Agent 配置（读取 scene 场景字段）
from langchain.agents import AgentState  # Agent 状态对象（包含消息历史等）
from langchain.agents.middleware import wrap_tool_call, before_model, dynamic_prompt, ModelRequest  # LangChain 中间件装饰器
from langchain.tools.tool_node import ToolCallRequest  # 工具调用请求对象（包含工具名、参数等）
from langchain_core.messages import ToolMessage  # 工具返回的消息对象
from langgraph.runtime import Runtime  # LangGraph 运行时上下文（包含 runtime.context）
from langgraph.types import Command  # LangGraph 命令类型
from utils.logger_handler import logger  # 日志记录器


# ---- 中间件 1：工具调用监控 ----
@wrap_tool_call  # 装饰器：将此函数包装为工具调用的中间件
def monitor_tool(
        # 请求的数据封装：包含工具名、参数、运行时上下文等
        request: ToolCallRequest,
        # 执行的函数本身：即原始工具函数的调用入口
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """
    工具调用的监控中间件
    作用：在工具执行前后插入日志记录，并检测 fill_context_for_report 的调用
    流程：记录日志 → 执行工具 → 记录结果 → 检测报告触发器
    """
    # 工具执行前：记录工具名称和参数
    logger.info(f"[tool monitor]执行工具：{request.tool_call['name']}")
    logger.info(f"[tool monitor]传入参数：{request.tool_call['args']}")

    try:
        # 执行原始工具函数（handler 就是实际的工具函数）
        result = handler(request)
        # 工具执行后：记录成功日志
        logger.info(f"[tool monitor]工具{request.tool_call['name']}调用成功")

        # 关键逻辑：如果被调用的工具是 fill_context_for_report
        # 就在运行时上下文中设置 report=True 标记
        # 这个标记会被 report_prompt_switch 检测到，触发提示词切换
        if request.tool_call['name'] == "fill_context_for_report":
            request.runtime.context["report"] = True

        # 记录工具调用事件（供 execute_stream_events 流式回传前端做"工具透明"）
        # 结构：{name, args(截断), result_preview(截断), ok}
        context = request.runtime.context
        if "tool_events" not in context:
            context["tool_events"] = []
        result_str = result.content if hasattr(result, "content") else str(result)
        context["tool_events"].append(_tool_event(
            request.tool_call['name'],
            request.tool_call.get('args'),
            result_str,
            ok=True,
        ))

        # 关键逻辑：RAG 工具返回若带"相关图片 [图片:url]"行 → 抽取图 URL 进 context，
        # 供 execute_stream_events 在流结束把图回显到回答末尾（不依赖模型转发标记）。
        name = request.tool_call['name']
        if name in ("rag_summarize", "sky_rag_summarize"):
            _collect_rag_images(result_str, context)

        return result
    except Exception as e:
        # 工具执行失败：记录错误日志并重新抛出异常
        context = request.runtime.context
        if "tool_events" not in context:
            context["tool_events"] = []
        context["tool_events"].append(_tool_event(
            request.tool_call['name'],
            request.tool_call.get('args'),
            f"调用失败：{str(e)}",
            ok=False,
        ))
        logger.error(f"工具{request.tool_call['name']}调用失败，原因：{str(e)}")
        raise e


def _tool_event(name: str, args, result_str: str, ok: bool) -> dict:
    """构造一条工具调用事件（入参/结果各截断，避免把大段 JSON 全量回传前端）"""
    args_str = str(args)[:200] if args is not None else ""
    result_str = str(result_str)
    # 结果可能很长（RAG 检索、报表 JSON 等），仅回传摘要给前端做过程提示
    result_preview = result_str[:200] + ("..." if len(result_str) > 200 else "")
    return {
        "name": name,
        "args": args_str,
        "result_preview": result_preview,
        "ok": ok,
    }


# RAG 返回里的相关图片标记形如：
#   相关图片：
#   [图片:http://...]
# 抽取其中 [图片:url] 的 url 存入 context["rag_images"]（去重、保序）。
_IMG_MARK_RE = __import__("re").compile(r"\[图片:([^\]]+)\]")


def _collect_rag_images(result_str: str, context: dict) -> None:
    try:
        urls = [m for m in _IMG_MARK_RE.findall(str(result_str)) if m]
        if not urls:
            return
        seen = set(context.get("rag_images", []))
        cur = list(context.get("rag_images", []))
        for u in urls:
            if u not in seen:
                seen.add(u)
                cur.append(u)
        context["rag_images"] = cur
    except Exception as e:
        logger.warning(f"[tool monitor]解析 RAG 图片失败：{str(e)[:100]}")


# ---- 中间件 2：模型调用前日志 ----
@before_model  # 装饰器：在 LLM 调用之前执行此函数
def log_before_model(
        state: AgentState,   # Agent 状态：包含完整的消息历史
        runtime: Runtime,    # 运行时上下文：包含 context 等运行时信息
):
    """
    模型调用前的日志中间件
    作用：在每次 LLM 调用前，记录当前消息数量和最后一条消息内容
    """
    # 记录消息总数
    logger.info(f"[log_before_model]即将调用模型，带有{len(state['messages'])}条消息。")

    # 记录最后一条消息的类型和内容（DEBUG 级别，控制台不显示，文件中记录）
    # state['messages'][-1] 是最后一条消息
    # type(...).__name__ 获取类名，如 "HumanMessage"、"AIMessage"、"ToolMessage"
    logger.debug(f"[log_before_model]{type(state['messages'][-1]).__name__} | {state['messages'][-1].content.strip()}")

    # 返回 None 表示不修改状态，继续正常执行
    return None


# ---- 中间件 3：动态提示词切换 ----
@dynamic_prompt  # 装饰器：在每次生成提示词之前调用此函数
def report_prompt_switch(request: ModelRequest):
    """
    动态提示词切换中间件
    作用：根据 runtime.context["report"] 的值 + config/agent.yml 的 scene 字段，
          决定使用哪套 System Prompt
    返回值：提示词文本字符串，LangChain 会用它替换默认的 System Prompt
    """
    # 从运行时上下文中读取 report 标记（默认 False）
    is_report = request.runtime.context.get("report", False)

    scene = agent_conf.get("scene", "robot")

    if is_report:
        # 报告场景 → 切换到报表提示词
        if scene == "sky":
            return load_report_prompts_sky()
        return load_report_prompts()

    # 普通问答 → 返回当前场景的基础提示词
    if scene == "sky":
        return load_system_prompts_sky()
    return load_system_prompts()
