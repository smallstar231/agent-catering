# 模型工厂模块
# 功能：初始化 LLM（对话模型）和 Embedding（向量化模型），供 Agent 和 RAG 使用
# 被 agent/react_agent.py（LLM）、rag/vector_store.py（Embedding）、rag/rag_service.py（LLM）调用
# 设计模式：工厂模式——通过工厂类统一创建模型对象，解耦模型的创建和使用

import os
from abc import ABC, abstractmethod  # 抽象基类：定义接口规范
from typing import Optional           # 类型标注：表示返回值可能为 None
from langchain_core.embeddings import Embeddings  # LangChain Embedding 基类
from langchain_core.language_models import BaseChatModel  # LangChain ChatModel 基类
from langchain_community.embeddings import DashScopeEmbeddings    # 阿里云 DashScope 的 Embedding 实现
from langchain_openai import ChatOpenAI     # 阿里云百炼 OpenAI 兼容接口
from utils.config_handler import rag_conf  # RAG 配置（包含模型名称）


class BaseModelFactory(ABC):
    """
    抽象工厂基类
    定义了工厂类必须实现的 generator() 方法接口
    ABC = Abstract Base Class，不能直接实例化，只能被继承
    """

    @abstractmethod
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """
        抽象方法：子类必须实现这个方法
        返回值：Embeddings 或 BaseChatModel 对象，或 None
        @abstractmethod 标记后，子类如果不实现这个方法，实例化时会报错
        """
        pass


class ChatModelFactory(BaseModelFactory):
    """
    对话模型工厂
    负责创建 ChatTongyi（通义千问）实例，用于 Agent 推理和 RAG 总结
    """

    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """
        创建并返回通义千问对话模型实例
        model 参数从 YAML 配置中读取（rag_conf["chat_model_name"] = "qwen3.5-plus"）
        使用阿里云百炼 OpenAI 兼容接口（langchain_openai.ChatOpenAI）
        """
        return ChatOpenAI(
            model=rag_conf["chat_model_name"],
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            streaming=True,
        )


class EmbeddingsFactory(BaseModelFactory):
    """
    Embedding 模型工厂
    负责创建 DashScopeEmbeddings 实例，用于将文本转为向量（供 Chroma 存储和检索）
    """

    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """
        创建并返回 DashScope Embedding 模型实例
        model 参数从 YAML 配置中读取（rag_conf["embedding_model_name"] = "text-embedding-v4"）
        """
        return DashScopeEmbeddings(model=rag_conf["embedding_model_name"])


# ---- 模块级变量：import 时自动创建模型实例，全局共享 ----
# chat_model：通义千问对话模型，被 react_agent.py 和 rag_service.py 使用
chat_model = ChatModelFactory().generator()

# embed_model：DashScope Embedding 模型，被 vector_store.py 使用
embed_model = EmbeddingsFactory().generator()
