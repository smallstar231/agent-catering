# RAG 总结服务模块
# 功能：接收用户提问 → 从向量库检索相关文档 → 拼接参考资料 → 交给 LLM 总结 → 返回总结文本
# 被 agent/tools/agent_tools.py 的 rag_summarize 工具调用
# RAG = Retrieval Augmented Generation（检索增强生成）

from langchain_core.documents import Document       # 文档对象
from langchain_core.output_parsers import StrOutputParser  # 输出解析器：将 LLM 输出转为纯字符串

from rag.vector_store import VectorStoreService      # 向量存储服务
from utils.prompt_loader import load_rag_prompts     # 加载 RAG 提示词模板
from langchain_core.prompts import PromptTemplate    # 提示词模板
from model.factory import chat_model                 # LLM 对话模型


class RagSummarizeService:
    """
    RAG 总结服务
    职责：检索 + 总结——从向量库找到相关文档，交给 LLM 生成总结
    这个类把"检索"和"总结"串成一条链（Chain）
    支持场景隔离：robot（扫地机器人）| sky（苍穹外卖）
    """

    def __init__(self, prompt_loader=None, scene: str = "robot"):
        """
        初始化：创建向量库服务、检索器、提示词模板、LLM，组装成链
        入参：prompt_loader - 可选的提示词加载函数，不传时使用默认的 load_rag_prompts()
              scene - 场景名称，"robot"（默认）或 "sky"
        """
        # 创建向量存储服务实例（根据场景选择对应集合）
        self.vector_store = VectorStoreService(scene=scene)
        # 获取检索器（从向量库中检索最相关的文档）
        self.retriever = self.vector_store.get_retriever()
        # 加载 RAG 提示词模板：使用传入的加载器或默认加载器
        if prompt_loader is not None:
            self.prompt_text = prompt_loader()
        else:
            self.prompt_text = load_rag_prompts()
        # 将文本转为 PromptTemplate 对象（支持 {input} 和 {context} 变量替换）
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        # LLM 模型（通义千问）
        self.model = chat_model
        # 组装链（Chain）
        self.chain = self._init_chain()

    def _init_chain(self):
        """
        组装 RAG 链：提示词模板 → LLM → 输出解析器
        用 LangChain 的 | 运算符（管道语法）串联各组件
        返回：可调用的链对象
        """
        # prompt_template | model | StrOutputParser()
        # 等价于：先填模板 → 再调 LLM → 再解析输出
        return self.prompt_template | self.model | StrOutputParser()

    def retriever_docs(self, query: str) -> list[Document]:
        """
        从向量库检索与 query 最相关的文档
        入参：query - 检索词
        返回：list[Document]，最相关的 k 个文档
        """
        return self.retriever.invoke(query)

    def rag_summarize(self, query: str) -> str:
        """
        RAG 总结的完整流程：检索 → 拼接 → 总结
        入参：query - 用户提问
        返回：LLM 基于参考资料生成的总结文本
        """
        # Step 1：从向量库检索相关文档
        context_docs = self.retriever_docs(query)

        # Step 2：将检索到的文档拼接成参考资料字符串
        context = ""
        counter = 0
        for doc in context_docs:
            counter += 1
            # 每个文档格式：【参考资料1】: 内容 | 元数据
            context += f"【参考资料{counter}】: 参考资料：{doc.page_content} | 参考元数据：{doc.metadata}\n"

        # Step 3：调用链（填模板 → LLM 总结 → 解析输出）
        return self.chain.invoke(
            {
                "input": query,       # 用户提问（填入模板的 {input}）
                "context": context,   # 参考资料（填入模板的 {context}）
            }
        )


if __name__ == '__main__':
    # 直接运行此文件时，测试 RAG 总结
    rag = RagSummarizeService()

    print(rag.rag_summarize("小户型适合哪些扫地机器人"))
