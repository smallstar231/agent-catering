# Agent 核心模块
# 功能：创建 ReAct Agent 并提供流式执行接口
# 被 app.py 调用，是整个项目的"大脑中枢"
# 这个文件把模型、工具、中间件、提示词组装在一起，形成完整的 Agent

from langchain.agents import create_agent  # LangChain 的 Agent 创建函数
from model.factory import chat_model       # LLM 对话模型（通义千问）
from utils.prompt_loader import load_system_prompts, load_system_prompts_sky  # 加载系统提示词
from utils.config_handler import agent_conf          # Agent 配置（读取 scene 场景字段）
from utils.logger_handler import logger              # 日志记录器
from utils.history_compressor import compress_history  # 会话历史压缩（长对话防爆窗）

# 导入 7 个通用工具函数
from agent.tools.agent_tools import (rag_summarize, get_weather, get_user_location, get_user_id,
                                     get_current_month, fetch_external_data, fill_context_for_report)
# 导入 6 个苍穹外卖工具函数
from agent.tools.agent_tools import (sky_rag_summarize, sky_query_dish, sky_query_category,
                                     sky_query_setmeal, sky_query_order, sky_generate_report)
# 导入 5 个新增增强工具（真实联网 / 网页正文 / 读图 / FAQ 精确问答 / 上传文件解析）+ 安全代码沙箱
from agent.tools.agent_tools import web_search, page_read, describe_image, faq_lookup, read_file, run_python
# 导入 3 个中间件
from agent.tools.middleware import monitor_tool, log_before_model, report_prompt_switch


class ReactAgent:
    """
    ReAct Agent 类
    封装了 Agent 的创建和执行逻辑
    创建时：组装模型 + 提示词 + 工具 + 中间件
    执行时：接收用户输入，流式返回 Agent 的推理和回答
    """

    def __init__(self):
        """
        初始化 Agent：将所有组件组装成一个可执行的 Agent
        """
        # 读取当前场景配置（直接取，无默认值——必须在 agent.yml 中配置）
        self.scene = agent_conf["scene"]
        logger.info(f"[ReactAgent]初始化 Agent，当前场景：{self.scene}")

        # 启动时根据 scene 直接选对基础提示词，不再靠 middleware 运行时覆盖
        if self.scene == "sky":
            base_prompt = load_system_prompts_sky()
        else:
            base_prompt = load_system_prompts()

        # 基础工具列表：7 个通用工具 + 6 个苍穹外卖工具 + 5 个增强工具
        tools = [rag_summarize, get_weather, get_user_location, get_user_id,
                 get_current_month, fetch_external_data, fill_context_for_report,
                 sky_rag_summarize, sky_query_dish, sky_query_category,
                 sky_query_setmeal, sky_query_order, sky_generate_report,
                 web_search, page_read, describe_image, read_file, faq_lookup, run_python]

        # 可选：挂载外部 MCP 工具（config/agent.yml -> enable_mcp_tools）
        # 默认关闭，避免每次启动额外拉起 MCP server 拖慢；需要时置 true 并在 config 配好
        try:
            if agent_conf.get("enable_mcp_tools", False):
                from agent.tools.mcp_client_tool import build_mcp_tools
                _mcp = build_mcp_tools()
                if _mcp:
                    tools.extend(_mcp)
                    logger.info(f"[ReactAgent]已挂载 {len(_mcp)} 个外部 MCP 工具")
        except Exception as e:
            logger.warning(f"[ReactAgent]挂载 MCP 工具失败（忽略）：{str(e)[:120]}")

        # create_agent 是 LangChain 提供的工厂函数
        # 它接收四个参数，将它们组装成一个完整的 ReAct Agent
        # system_prompt 在普通问答场景下直接生效（middleware 只处理 report 切换）
        self.agent = create_agent(
            model=chat_model,                          # LLM 模型（通义千问）
            system_prompt=base_prompt,                 # 启动时按 scene 选好基础提示词
            tools=tools,
            middleware=[monitor_tool, log_before_model, # 中间件列表：3 个中间件
                        report_prompt_switch],
        )

    # ---- 执行上下文 ----
    def _build_context(self) -> dict:
        """构造一次执行共享的 runtime.context：
        - report: report_prompt_switch 中间件用来切报表提示词的标记
        - tool_events: monitor_tool 中间件写入的工具调用事件列表（供 execute_stream_events 回传前端）
        - rag_images: RAG 工具返回里"相关图片"的 URL（由 monitor_tool 抽取，流结束回显到回答末尾）
        同一个 dict 对象被传入 agent.stream(context=...)，中间件通过 request.runtime.context 原地修改，
        因此执行结束后 / 过程中我们都能读到已产生的工具事件。
        """
        return {"report": False, "tool_events": [], "rag_images": []}

    def _yield_new_tool_events(self, context: dict, sent_count: int):
        """把 context["tool_events"] 中比 sent_count 新的条目逐一产出（增量消费）"""
        tool_events = context.get("tool_events", [])
        while sent_count < len(tool_events):
            ev = tool_events[sent_count]
            sent_count += 1
            yield ("tool", ev)

    # ---- 主入口（纯文本，向后兼容）----
    def execute_stream(self, query: str, history: list | None = None):
        """
        流式执行 Agent（兼容旧接口）：逐 token yield 纯文本。
        新功能会带工具事件/推理过程，如需使用请调用 execute_stream_events。
        """
        for event, payload in self.execute_stream_events(query, history=history):
            if event == "text":
                yield payload
            # tool / reasoning 事件在纯文本模式下丢弃（保持旧行为）

    # ---- 事件版执行入口 ----
    def execute_stream_events(self, query: str, history: list | None = None):
        """
        流式执行 Agent（事件版本，支持"工具透明"与"推理过程"回传）
        入参：
            query - 用户当前输入文本
            history - 之前的对话历史列表（每条含 role 和 content）
        产出：通过 yield 返回事件二元组 (event_type, payload)：
            ("text", str)          - 正文 token 片段（打字机效果）
            ("tool", dict)         - 一次工具调用：{name, args, result_preview, ok}
            ("reasoning", str)     - 思考模型输出片段（若模型支持；不支持则不出此事件）

        说明：
            - 入口会对 history 做字符预算压缩，长对话不爆窗。
            - 工具事件来自 middleware.monitor_tool 写入 context["tool_events"]，
              本生成器在每个 chunk 前增量排空，从而把"工具调用过程"穿插到文本流中回传前端。
        """
        # 历史消息清洗：丢弃非 dict / 缺 role / content 非文本的条目，并强制转 str
        # （避免 langchain 因 {role:'user'} 无 content 之类畸形消息抛 ValueError 导致 500）
        clean_history: list[dict] = []
        if history:
            for m in history:
                if not isinstance(m, dict):
                    continue
                role = m.get("role")
                if role not in ("user", "assistant", "system"):
                    continue
                content = m.get("content")
                if content is None:
                    content = ""
                clean_history.append({"role": role, "content": str(content)})

        # 历史压缩（仅当超预算时缩短；不影响语义与末轮完整性）
        if clean_history:
            clean_history = compress_history(clean_history)

        # 构造输入消息列表
        messages = []
        if clean_history:
            messages.extend(clean_history)
        # 追加当前用户消息（query 非文本时给空串，避免 langchain 崩溃）
        query = query if isinstance(query, str) else (str(query) if query is not None else "")
        messages.append({"role": "user", "content": query})

        input_dict = {"messages": messages}
        context = self._build_context()
        sent_tool_count = 0
        emitted_text: list[str] = []   # 累积已产出的正文字符（供末尾"相关图片"去重判断）

        # 流式执行 Agent（真正的逐 token 流式）
        for chunk in self.agent.stream(
            input_dict,
            stream_mode=["messages", "values"],
            subgraphs=True,
            version="v2",
            context=context,  # report=False + tool_events=[]，中间件可原地修改
        ):
            # 先增量排空工具事件（中间件可能在 tools 节点执行时已写入）
            for ev in self._yield_new_tool_events(context, sent_tool_count):
                sent_tool_count += 1
                yield ev

            if isinstance(chunk, dict) and chunk.get("type") == "messages":
                data = chunk["data"]
                if isinstance(data, tuple) and len(data) >= 1:
                    msg = data[0]               # AIMessageChunk / ToolMessage
                    meta = data[1] if len(data) > 1 else {}

                    # 跳过"__start__"和"tools"节点的输出
                    node = meta.get("langgraph_node", "")
                    if node in ("__start__", "tools"):
                        continue

                    # 跳过中间推理步骤中的 tool_call 碎片
                    if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
                        continue

                    # 尝试提取"思维链/推理过程"（qwen3 等思考模型的 reasoning_content）
                    # 若模型无思考输出，则不产生 reasoning 事件（安全降级）
                    reasoning = ""
                    try:
                        if hasattr(msg, "additional_kwargs"):
                            reasoning = str(msg.additional_kwargs.get("reasoning_content", "") or "")
                    except Exception:
                        reasoning = ""
                    if reasoning:
                        yield ("reasoning", reasoning)

                    # 剩下的就是纯内容 token → 逐 chunk yield 文本事件
                    content = str(getattr(msg, "content", ""))
                    if content:
                        emitted_text.append(content)
                        yield ("text", content)

        # 流结束后排空残余工具事件（兜底）
        for ev in self._yield_new_tool_events(context, sent_tool_count):
            sent_tool_count += 1
            yield ev

        # 关键：本轮 RAG 若命中"相关图片"，把它们回显到回答末尾（后端保证，不依赖模型转发标记）。
        # 累积已产出文本并 join，只补"模型未带出的"图 URL，避免重复。
        rag_imgs = context.get("rag_images") or []
        if rag_imgs and emitted_text:
            full_text = "".join(emitted_text)
            need = [u for u in rag_imgs if f"[图片:{u}]" not in full_text]
            if need:
                yield ("text", "\n\n相关图片：\n")
                for u in need:
                    yield ("text", f"[图片:{u}]\n")

    def execute_stream_with_events(self, query: str, history: list | None = None):
        """别名：语义更清晰的命名（供 api_service 使用）"""
        return self.execute_stream_events(query, history=history)


if __name__ == '__main__':
    # 直接运行此文件时，测试 Agent 执行
    agent = ReactAgent()

    # 测试报告生成场景（事件版，打印事件类型）
    for event, payload in agent.execute_stream_events("给我生成我的使用报告"):
        if event == "text":
            print(payload, end="", flush=True)
        elif event == "tool":
            print(f"\n[调用工具] {payload['name']} args={payload['args']}", flush=True)
        elif event == "reasoning":
            pass  # 思考过程过长，这里不打印
