# Agent 核心模块
# 功能：创建 ReAct Agent 并提供流式执行接口
# 被 app.py 调用，是整个项目的"大脑中枢"
# 这个文件把模型、工具、中间件、提示词组装在一起，形成完整的 Agent

from langchain.agents import create_agent  # LangChain 的 Agent 创建函数
from model.factory import chat_model       # LLM 对话模型（通义千问）
from utils.prompt_loader import load_system_prompts  # 加载系统提示词
from utils.config_handler import agent_conf          # Agent 配置（读取 scene 场景字段）
from utils.logger_handler import logger              # 日志记录器

# 导入 7 个通用工具函数
from agent.tools.agent_tools import (rag_summarize, get_weather, get_user_location, get_user_id,
                                     get_current_month, fetch_external_data, fill_context_for_report)
# 导入 6 个苍穹外卖工具函数
from agent.tools.agent_tools import (sky_rag_summarize, sky_query_dish, sky_query_category,
                                     sky_query_setmeal, sky_query_order, sky_generate_report)
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
        # 读取当前场景配置
        self.scene = agent_conf.get("scene", "robot")
        logger.info(f"[ReactAgent]初始化 Agent，当前场景：{self.scene}")

        # create_agent 是 LangChain 提供的工厂函数
        # 它接收四个参数，将它们组装成一个完整的 ReAct Agent
        # system_prompt 会被 middleware 的 dynamic_prompt 动态覆盖
        self.agent = create_agent(
            model=chat_model,                          # LLM 模型（通义千问）
            system_prompt=load_system_prompts(),       # 默认系统提示词（被 middleware 动态覆盖）
            tools=[rag_summarize, get_weather,         # 工具列表：7 个通用工具 + 6 个苍穹外卖工具
                   get_user_location, get_user_id,
                   get_current_month, fetch_external_data, fill_context_for_report,
                   sky_rag_summarize, sky_query_dish, sky_query_category,
                   sky_query_setmeal, sky_query_order, sky_generate_report],
            middleware=[monitor_tool, log_before_model, # 中间件列表：3 个中间件
                        report_prompt_switch],
        )

    def execute_stream(self, query: str, history: list | None = None):
        """
        流式执行 Agent（支持多轮对话记忆）
        入参：
            query - 用户当前输入文本
            history - 之前的对话历史列表（每条含 role 和 content）
        产出：通过 yield 逐 token 返回 Agent 的最终回答（生成器函数），前端产生打字机效果

        流式原理：
            使用 stream_mode=["messages", "values"] + subgraphs=True 模式，
            让 LangGraph 子图内部的逐 token 输出透传到外层。
            这是 LangGraph 0.4.0+ 的官方方案。
        """
        # 构造输入消息列表
        messages = []

        # 填充历史消息
        if history:
            messages.extend(history)

        # 追加当前用户消息
        messages.append({"role": "user", "content": query})

        input_dict = {"messages": messages}

        # 流式执行 Agent（真正的逐 token 流式）
        # subgraphs=True 让 create_agent 内部子图的 token 级输出透传出来
        for chunk in self.agent.stream(
            input_dict,
            stream_mode=["messages", "values"],
            subgraphs=True,
            version="v2",
            context={"report": False}
        ):
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
                    #（第一轮模型调用的 tool_call_chunks chunk，不含最终回答内容）
                    if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
                        continue

                    # 剩下的就是纯内容 token → 逐 chunk yield
                    content = str(getattr(msg, "content", ""))
                    if content:
                        yield content

if __name__ == '__main__':
    # 直接运行此文件时，测试 Agent 执行
    agent = ReactAgent()

    # 测试报告生成场景
    for chunk in agent.execute_stream("给我生成我的使用报告"):
        print(chunk, end="", flush=True)
