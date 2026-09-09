# RAG 总结服务模块
# 功能：接收用户提问 → 从向量库检索相关文档 → 拼接参考资料 → 交给 LLM 总结 → 返回总结文本
# 被 agent/tools/agent_tools.py 的 rag_summarize 工具调用
# RAG = Retrieval Augmented Generation（检索增强生成）

from langchain_core.documents import Document       # 文档对象
from langchain_core.output_parsers import StrOutputParser  # 输出解析器：将 LLM 输出转为纯字符串

from rag.vector_store import VectorStoreService      # 向量存储服务
from rag.rerank import rerank_docs, rerank_enabled   # Rerank 精排（高召回 → 精排 → top_n）
from utils.prompt_loader import load_rag_prompts     # 加载 RAG 提示词模板
from langchain_core.prompts import PromptTemplate    # 提示词模板
from model.factory import chat_model                 # LLM 对话模型
from utils.config_handler import chroma_conf, rag_conf         # 向量库配置（recall_k / k）+ RAG配置(multimodal)
from utils.logger_handler import logger              # 日志记录器


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
        # 召回检索器：高召回（recall_k），供"召回→rerank→取top_n"精排使用
        try:
            recall_k = chroma_conf.get("recall_k", 10) or 10
        except Exception:
            recall_k = 10
        self.retriever = self.vector_store.get_retriever(k=recall_k)
        self.recall_k = recall_k
        # 最终喂给 LLM 的条数（chroma.yml 的 k，精排后取这么多）
        try:
            self.final_k = chroma_conf.get("k", 3) or 3
        except Exception:
            self.final_k = 3
        # 多模态图文检索配置（可选；关闭或缺依赖时优雅降级为纯文本）
        self.mm_enabled = False
        self.mm_store = None
        self.mm_recall_k = 4
        self.mm_echo_limit = 2
        try:
            mm = rag_conf.get("multimodal") or {}
            if mm.get("enabled", False):
                self.mm_recall_k = int(mm.get("mm_recall_k", 4) or 4)
                self.mm_echo_limit = int(mm.get("mm_echo_limit", 2) or 2)
                from rag.multimodal_store import MultimodalVectorStore
                self.mm_store = MultimodalVectorStore(scene=scene)
                self.mm_enabled = True
        except Exception as e:
            logger.warning(f"[RAG]多模态图文检索未启用：{str(e)[:120]}")
            self.mm_enabled = False
            self.mm_store = None
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
        召回：从向量库检索与 query 最相关的文档（高召回 recall_k 个候选）
        入参：query - 检索词
        返回：list[Document]，最相关的 recall_k 个候选
        """
        return self.retriever.invoke(query)

    def _final_docs(self, query: str) -> list[Document]:
        """
        取"最终喂给 LLM"的参考资料：召回 recall_k →（可选）rerank 精排 → 取 top final_k
        入参：query - 用户提问
        返回：按相关性降序的 final_k 个 Document
        降级：rerank 关闭或失败时，直接用召回结果的前 final_k 条（不调 API）。
        """
        recalled = self.retriever_docs(query)  # recall_k 条

        if rerank_enabled() and len(recalled) > self.final_k:
            # 高召回候选太多 → 用 rerank 精排；失败返回 None 则回退
            ranked = rerank_docs(query, recalled, top_n=self.final_k)
            if ranked is not None:
                return ranked[: self.final_k]

        # 回退：取召回前 final_k（保持旧行为）
        return recalled[: self.final_k]

    @staticmethod
    def _doc_source(doc: Document) -> str:
        """取一条 Document 的来源文件名（用于引用回显），取不到给占位"""
        src = (doc.metadata or {}).get("source", "")
        return str(src) if src else "知识库"

    def _multimodal_hits(self, query: str, top_n: int) -> list[tuple[Document, float]]:
        """从多模态图文集合检索文字 query 相关条目；失败返回空（优雅降级）。"""
        try:
            if self.mm_store is not None:
                return self.mm_store.query_text(query, top_k=top_n)
        except Exception as e:
            logger.warning(f"[RAG]多模态检索失败（忽略）：{str(e)[:120]}")
        return []

    def rag_summarize(self, query: str, with_cite: bool = True) -> str:
        """
        RAG 总结的完整流程：
          文本库召回 →(可选 rerank)→ topK 文本 + 图文集合召回 → 拼接(带来源)→ 总结 → 来源行 →(命中图)追加 [图片:url]
        入参：query - 用户提问
        返回：LLM 基于参考资料生成的总结文本；with_cite=True 时末尾带来源行；命中图文库时再追加"相关图片"
        """
        # Step 1：文本库召回（召回 → rerank → top final_k）；多模态图文召回（若启用）
        text_docs = self._final_docs(query)
        mm_hits: list[tuple[Document, float]] = []
        if self.mm_enabled and self.mm_store is not None:
            mm_hits = self._multimodal_hits(query, top_n=self.mm_recall_k)

        # 合并：给图文项保留 mm_echo_limit 个槽位，其余填文本；文本靠前、图文靠后
        mm_used = min(self.mm_echo_limit, len(mm_hits))
        context_docs = list(text_docs[: max(1, self.final_k - mm_used)])
        context_docs += [d for d, _ in mm_hits[:mm_used]]
        # 收集命中图文（去重，供回答末尾回显图片 URL）
        echo_images: list[str] = []
        seen_img = set()
        for d, _ in mm_hits[:mm_used]:
            u = (d.metadata or {}).get("image_url", "")
            if u and u not in seen_img:
                seen_img.add(u)
                echo_images.append(u)

        # Step 2：将参考资料拼接成字符串（带来源标注，供引用回显）
        context = ""
        sources: list[str] = []
        seen_src = set()
        for i, doc in enumerate(context_docs):
            src = self._doc_source(doc)
            context += (
                f"【参考资料{i + 1}】: 参考资料：{doc.page_content}"
                f" | 参考元数据：{doc.metadata}\n"
            )
            if with_cite and src not in seen_src:
                seen_src.add(src)
                sources.append(src)

        # Step 3：调用链（填模板 → LLM 总结 → 解析输出）
        answer = self.chain.invoke(
            {
                "input": query,       # 用户提问（填入模板的 {input}）
                "context": context,   # 参考资料（填入模板的 {context}）
            }
        )

        # Step 4：追加引用来源行（只在明确取到来源时追加）
        if with_cite and sources:
            cite_line = "来源: " + " · ".join(f"[{i + 1}] {s}" for i, s in enumerate(sources))
            answer = answer.rstrip() + f"\n\n{cite_line}"

        # Step 5：命中图文 → 在末尾回显图片（[图片:url] 由前端渲染成缩略图）
        if echo_images:
            answer = answer.rstrip() + "\n\n相关图片：\n" + "\n".join(f"[图片:{u}]" for u in echo_images)

        return answer


if __name__ == '__main__':
    # 直接运行此文件时，测试 RAG 总结
    rag = RagSummarizeService()

    print(rag.rag_summarize("小户型适合哪些扫地机器人"))
