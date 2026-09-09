# 多模态向量模型适配器（qwen3-vl-embedding）
# 功能：调用阿里云百炼 DashScope 多模态向量端点，把"文本 / 图片 / 图文融合"统一映射到同一向量空间（2560 维）。
# 被 rag/multimodal_store.py 调用，用于图文知识库的入库(embed_media)与文字查询(embed_query)。
# 端点/参数参考 PAI-RAG--STUDY backend/rag/embedding/multimodal_dashscope_embedding.py，但本项目用同步 httpx。
# 设计：惰性读取 DASHSCOPE_API_KEY；纯文本→type=vl；图+文本(enable_fusion)→type=fusion；均 2560 维，可跨模态检索。

import os
import sys
# 允许 `python -m rag.multimodal_embedding` / `python rag/multimodal_embedding.py` 直接运行（把项目根加入 path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from utils.config_handler import load_dotenv  # 确保 .env 已加载
from utils.path_tool import get_abs_path
from utils.logger_handler import logger

load_dotenv(get_abs_path(".env"))

# DashScope 多模态向量端点（OpenAI 之外的专用服务端点）
MM_EMBED_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)
# 默认模型：支持 enable_fusion 融合向量（图+文本 → 1 个向量）
DEFAULT_MODEL = "qwen3-vl-embedding"
TIMEOUT = 60


class MultimodalEmbeddingError(RuntimeError):
    """多模态向量调用失败（供上层 try/except 降级）"""


class MultimodalDashscopeEmbedding:
    """DashScope qwen3-vl-embedding 同步客户端。

    对外两个方法：
      embed_query(text)                       -> 纯文本查询向量（type=vl）
      embed_media(text, image_data_url)       -> 图(+可选文本)融合向量（type=fusion）
    两者都在同一 2560 维空间，因此文字查询可命中"以图为主"的条目。
    未配置 key 或调用失败抛 MultimodalEmbeddingError（调用方负责降级，不 crash）。
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, api_key: str | None = None):
        self.model_name = model_name
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            logger.warning("[mm_embed]未配置 DASHSCOPE_API_KEY，多模态向量不可用")

    # ---- 内部 HTTP ----
    def _post(self, contents: list[dict], *, fusion: bool) -> list[float]:
        if not self.api_key:
            raise MultimodalEmbeddingError("未配置 DASHSCOPE_API_KEY")
        payload: dict = {"model": self.model_name, "input": {"contents": contents}}
        if fusion:
            # qwen3-vl-embedding 默认返回独立向量；显式融合可把图+文本合成 1 个向量
            payload["parameters"] = {"enable_fusion": True}
        try:
            resp = httpx.post(
                MM_EMBED_ENDPOINT,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as e:
            raise MultimodalEmbeddingError(f"网络请求失败：{e}") from e
        if resp.status_code != 200:
            raise MultimodalEmbeddingError(
                f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except Exception as e:
            raise MultimodalEmbeddingError(f"响应解析失败：{e}") from e
        if data.get("code"):
            raise MultimodalEmbeddingError(
                f"{data.get('message', 'unknown')} (code: {data['code']})"
            )
        embeddings = (data.get("output") or {}).get("embeddings") or []
        if not embeddings:
            raise MultimodalEmbeddingError("多模态向量返回空")
        # 取向量：融合模式优先 fusion/fused，否则回退到首个；返回其 embedding 列表
        vec = None
        if fusion:
            for e in embeddings:
                if e.get("type") in ("fusion", "fused"):
                    vec = e.get("embedding")
                    break
        if vec is None:
            vec = embeddings[0].get("embedding")
        if not vec:
            raise MultimodalEmbeddingError("多模态向量为空（无 embedding 字段）")
        return list(vec)

    # ---- 文本查询向量（以文搜图/搜图文）----
    def embed_query(self, text: str) -> list[float]:
        text = (text or "").strip()
        if not text:
            raise MultimodalEmbeddingError("embed_query 需要非空文本")
        return self._post([{"text": text}], fusion=False)

    # ---- 图(+可选文本)融合向量（入库用）----
    def embed_media(self, text: str | None, image_data_url: str) -> list[float]:
        image_data_url = (image_data_url or "").strip()
        if not image_data_url:
            raise MultimodalEmbeddingError("embed_media 需要 image data-url")
        contents: list[dict] = []
        if text and (text := text.strip()):
            contents.append({"text": text})
        contents.append({"image": image_data_url})
        return self._post(contents, fusion=True)


if __name__ == "__main__":
    # 自测：文本 + 一张 1x1 png data-url 各出 2560 维
    mm = MultimodalDashscopeEmbedding()
    tv = mm.embed_query("宫保鸡丁")
    tiny = ("data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    fv = mm.embed_media("红色方块", tiny)
    print("text dim:", len(tv), "| media dim:", len(fv))
