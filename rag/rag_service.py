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
        # 图文命中相关度阈值（cosine distance 上限）。None=不过滤(旧行为)。
        self.mm_max_distance: float | None = None
        # 视觉精判三段式：
        #   strong_distance  → distance ≤ 此值视为强相关，直接回显（不调视觉省钱）
        #   max_distance     → distance > 此值直接丢弃（粗筛线）
        #   visual_verify    → 中间模糊带是否送 qwen-vl 视觉精判（看图判定是否与 query 相关）
        self.mm_strong_distance: float | None = None
        self.mm_visual_verify = False
        try:
            mm = rag_conf.get("multimodal") or {}
            if mm.get("enabled", False):
                self.mm_recall_k = int(mm.get("mm_recall_k", 4) or 4)
                self.mm_echo_limit = int(mm.get("mm_echo_limit", 2) or 2)
                md = mm.get("mm_max_distance")
                self.mm_max_distance = float(md) if md not in (None, "", 0) else None
                sd = mm.get("mm_strong_distance")
                self.mm_strong_distance = float(sd) if sd not in (None, "", 0) else None
                self.mm_visual_verify = bool(mm.get("mm_visual_verify", False))
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

    # ------------------------------------------------------------------
    # 图文命中三段式过滤：
    #   strong_distance  → ≤该值：强相关，直接保留（不送视觉，省调用费）
    #   max_distance     → >该值：粗筛线，直接丢弃（明显无关，不送视觉）
    #   中间模糊带        → 若 mm_visual_verify 开启，送 qwen-vl 看图精判
    #                      （看图像像素本身，绕开可能很差的 caption 锚点）
    # ------------------------------------------------------------------
    def _filter_mm_hits(self, query: str, hits: list[tuple[Document, float]]) -> list[tuple[Document, float]]:
        if not hits:
            return []
        kept: list[tuple[Document, float]] = []
        fuzzy: list[tuple[Document, float]] = []   # 中间带候选（待视觉精判）
        for d, s in hits:
            s = float(s)
            # 强相关线
            if self.mm_strong_distance is not None and s <= self.mm_strong_distance:
                kept.append((d, s))
                continue
            # 粗筛丢弃线
            if self.mm_max_distance is not None and s > self.mm_max_distance:
                _src = (d.metadata or {}).get("source", "")
                logger.info(f"[RAG]图文命中 distance={s:.3f} > {self.mm_max_distance}，丢弃（{str(_src)[:40]}）")
                continue
            # 模糊带
            fuzzy.append((d, s))
        # 视觉精判（仅模糊带；失败/未开启则按旧逻辑保留模糊带前若干）
        if fuzzy and self.mm_visual_verify:
            verified = self._visual_verify_images(query, fuzzy)
            kept.extend(verified)
        else:
            kept.extend(fuzzy)
        # 保持按 distance 升序（最相关在前）
        kept.sort(key=lambda x: x[1])
        return kept

    def _visual_verify_images(self, query: str, fuzzy: list[tuple[Document, float]]) -> list[tuple[Document, float]]:
        """把模糊带候选图一次发给 qwen-vl，让它看图判断每张是否与用户 query 相关。
        返回判定"相关"的条目；视觉调用失败则全部保留（不因视觉故障误删用户可能有用的图）。
        image_url 形如 http://localhost:8000/files/xxx.png（本服务文件）。
        """
        try:
            from agent.tools.vision import _get_client, _local_file_to_data_url, MAX_IMAGE_BYTES
            from langchain_core.messages import HumanMessage
        except Exception as e:
            logger.warning(f"[RAG]视觉精判模块不可用（{str(e)[:80]}），模糊带按向量相关度保留")
            return fuzzy

        # 组装图片块：逐图 → data-url（读本地磁盘，避免公网不可达）；失败那张跳过
        img_blocks: list[dict] = []
        idx_by_img: dict[int, tuple[Document, float]] = {}
        order: list[int] = []   # 图片在 prompt 中的顺序 → 原 hits 索引
        for d, s in fuzzy:
            url = (d.metadata or {}).get("image_url", "")
            if not url:
                continue
            data_url = _local_file_to_data_url(url)
            if not data_url or data_url == "__TOO_LARGE__":
                logger.info(f"[RAG]视觉精判跳过不可读图 {url.split('/')[-1]}")
                continue
            i = len(img_blocks)
            img_blocks.append({"type": "image_url", "image_url": {"url": data_url}})
            idx_by_img[i] = (d, s)
            order.append(i)

        if not img_blocks:
            logger.warning("[RAG]视觉精判：无可读图，模糊带全部保留")
            return fuzzy

        # 指令：让模型逐张回答是否与 query 主题相关（只看图本身）
        # 按图片顺序逐行输出"是/否"，每行对应一张图（第1行=第1张…）
        n = len(img_blocks)
        instruction = (
            f"下面有 {n} 张图片，按顺序编号 1~{n}。用户问：『{query}』。\n"
            "请逐张看图判断：图片的实际内容是否与用户问题主题相关（例如用户找某菜品图，图里是否真的有该菜）。\n"
            f"严格只输出 {n} 行，第 i 行只写「是」或「否」，代表第 i 张图是否相关。\n"
            "示例（n=2 时）：\n是\n否\n不要输出序号、解释或任何其它文字。"
        )
        try:
            client = _get_client()
            resp = client.invoke([HumanMessage(content=[{"type": "text", "text": instruction}, *img_blocks])])
            raw = str(getattr(resp, "content", "") or "")
        except Exception as e:
            logger.warning(f"[RAG]视觉精判调用失败（{str(e)[:100]}），模糊带全部保留")
            return fuzzy

        # 解析模型输出，兼容两种格式：
        #   A) 纯按行序：第 i 行是「是/否」 → 对应第 i 张图
        #   B) 有序号：  "1:是 / 2:否"      → 按序号对应
        keep_set: set[int] = set()
        import re as _re
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        # B) 先试 "数字:是/否"
        numbered = [(int(m.group(1)) - 1, m.group(2).lower())
                    for ln in lines
                    for m in [_re.match(r"^\s*(\d+)\s*[:：]\s*(是|否|yes|no)\s*$", ln, _re.I)] if m]
        if numbered and len(numbered) >= 1:
            for idx, verdict in numbered:
                if 0 <= idx < len(img_blocks) and verdict.lower() in ("是", "yes"):
                    keep_set.add(idx)
        else:
            # A) 纯"是/否"逐行，按顺序对应图
            pure = [ln.lower() for ln in lines if ln.lower() in ("是", "否", "yes", "no")]
            for i, verdict in enumerate(pure):
                if i >= len(img_blocks):
                    break
                if verdict in ("是", "yes"):
                    keep_set.add(i)
        if not keep_set:
            logger.info(f"[RAG]视觉精判：全部判定与『{query}』无关（模型输出节选：{raw[:80]!r}）")
            # 极端保守：全部否时也至少保留最相关一张，避免"明明有图却一张不给"
            if fuzzy:
                keep_set.add(0)
        verified = [idx_by_img[i] for i in order if i in keep_set]
        logger.info(f"[RAG]视觉精判：{len(fuzzy)} 张候选 → 判定相关 {len(verified)} 张")
        return verified

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
            mm_hits = self._filter_mm_hits(query, mm_hits)

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
