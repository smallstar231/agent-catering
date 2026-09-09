# 多模态图文向量存储服务
# 功能：管理独立的"图文向量集合"（与文本向量库 agent/agent_sky 隔离）。
# 用 qwen3-vl-embedding 产 2560 维向量，通过底层 chromadb.Collection 直插/直查
# （langchain_chroma.add_documents 不接受显式向量，只能走原生 collection）。
# 被 rag/multimodal_ingest.py（入库）与 rag/rag_service.py（检索合并）调用。
#
# 注意：本集合内所有向量必须同维(2560)。集合由本类首建，无默认 embedding 函数；
# 检索用"文字 query 向量"去命中"图文/图融合向量"——同一语义空间，实现以文搜图。

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from langchain_core.documents import Document
from utils.config_handler import chroma_conf, rag_conf
from utils.path_tool import get_abs_path
from utils.logger_handler import logger
from rag.multimodal_embedding import MultimodalDashscopeEmbedding, MultimodalEmbeddingError


def _mm_model_name() -> str:
    """从 rag.yml -> multimodal.model 读取图文向量模型；读不到用默认 qwen3-vl-embedding。"""
    try:
        return (rag_conf.get("multimodal") or {}).get("model") or "qwen3-vl-embedding"
    except Exception:
        return "qwen3-vl-embedding"


class MultimodalVectorStore:
    """多模态图文集合（robot/sky 各一个独立持久化目录）。

    对外：
      add_entry(entry_id, text, image_data_url, source, kind, image_url, page=None)
      query_text(text_query, top_k) -> list[tuple[Document, float]]  # (doc, score)
      clear(), count()
    全部异常安全：embedding 失败会抛，由调用方(ingest 逐条 try / rag_service 整体 try)处理。
    """

    def __init__(self, scene: str = "robot", embedding: MultimodalDashscopeEmbedding | None = None):
        if scene == "sky":
            self._collection_name = chroma_conf["collection_name_mm_sky"]
            self._persist_dir = chroma_conf["persist_directory_mm_sky"]
        else:
            self._collection_name = chroma_conf["collection_name_mm"]
            self._persist_dir = chroma_conf["persist_directory_mm"]
        self.scene = scene
        # 图文向量模型从 rag.yml 读（multimodal.model）；默认 qwen3-vl-embedding
        self.embed = embedding or MultimodalDashscopeEmbedding(model_name=_mm_model_name())

        abs_persist = get_abs_path(self._persist_dir)
        os.makedirs(abs_persist, exist_ok=True)
        # PersistentClient 一个根目录对应一套集合；用 get_or_create 且不设 embedding 函数
        self._client = chromadb.PersistentClient(path=abs_persist)
        self._col = self._client.get_or_create_collection(
            name=self._collection_name, metadata={"hnsw:space": "cosine"}
        )

    @property
    def collection(self):
        return self._col

    # ---------- 入库 ----------
    def add_entry(
        self,
        entry_id: str,
        text: str,
        image_data_url: str,
        source: str,
        kind: str,
        image_url: str,
        page: int | None = None,
    ) -> bool:
        """把一条图文(或图)融合向量写入集合。
        text 是图的关键锚点文本：独立图为 caption；PDF 图为 caption + 所在页上下文。
        image_data_url 是喂给 embedding 的 data-url；image_url 是落盘后对外展示的 /files URL。
        """
        vec = self.embed.embed_media(text, image_data_url)
        meta: dict = {
            "source": str(source)[:200],
            "kind": kind,            # 'image'=独立图 / 'pdf_image'=PDF内嵌图
            "image_url": str(image_url),
        }
        if page is not None:
            meta["page"] = int(page)
        self._col.upsert(
            ids=[entry_id],
            embeddings=[vec],
            documents=[text or ""],   # document 留检索/展示用文本（也可留空）
            metadatas=[meta],
        )
        return True

    # ---------- 检索（文字查询 → 跨模态命中） ----------
    def query_text(self, text_query: str, top_k: int = 4) -> list[tuple[Document, float]]:
        qv = self.embed.embed_query(text_query)
        res = self._col.query(query_embeddings=[qv], n_results=max(1, top_k))
        out: list[tuple[Document, float]] = []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i in range(len(ids)):
            meta = metas[i] if i < len(metas) else {}
            meta = meta if isinstance(meta, dict) else {}
            score = dists[i] if i < len(dists) else 0.0
            out.append((
                Document(page_content=docs[i] if i < len(docs) else "", metadata=dict(meta)),
                float(score),
            ))
        return out

    def clear(self):
        try:
            self._client.delete_collection(self._collection_name)
        except Exception:
            pass
        self._col = self._client.get_or_create_collection(
            name=self._collection_name, metadata={"hnsw:space": "cosine"}
        )

    def count(self) -> int:
        try:
            return self._col.count()
        except Exception:
            return 0

    def all_entries(self) -> list[dict]:
        """调试/展示用：把集合里全部条目列出来（不含向量）。"""
        res = self._col.get(include=["documents", "metadatas"])
        out = []
        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        for i in range(len(ids)):
            out.append({
                "id": ids[i],
                "document": docs[i] if i < len(docs) else "",
                "metadata": (metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}),
            })
        return out


if __name__ == "__main__":
    # 自测：插入一条 caption 图文 → 用文字 query 命中
    import base64
    store = MultimodalVectorStore(scene="robot")
    tiny = ("data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    store.clear()
    ok = store.add_entry("t1", "菜单：宫保鸡丁 28元", tiny,
                         "测试菜单图.png", "image", "http://localhost:8000/files/t1.png")
    print("added:", ok, "| count:", store.count())
    hits = store.query_text("宫保鸡丁价格", top_k=2)
    for d, s in hits:
        print("  hit score=", round(s, 4), "| meta=", d.metadata, "| text=", d.page_content[:30])
    store.clear()
    print("cleared, count=", store.count())
