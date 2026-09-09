# Rerank 精排模块
# 功能：用 DashScope text-rerank API 对"向量检索召回的高候选"做交叉精排，返回相关性最高的前 top_n 条
# 被 rag/rag_service.py 调用
# 说明：
#   - 向量检索（召回）只保证"大概相关"，召回 k 调高后会夹带噪声；
#   - rerank 用 query 与每个候选做精排，能显著提升喂给 LLM 的资料质量。
# 异常安全：rerank 失败（网络/模型名/超限）一律捕获并回退到原召回的前 top_n，绝不让上层报错。

import os
from utils.config_handler import rag_conf  # RAG 配置（rerank 参数）
from utils.logger_handler import logger      # 日志记录器
from langchain_core.documents import Document  # LangChain 文档对象

# ---- 模块级重排客户端（懒初始化，避免 import 时即触发）----
_rerank_client = None


def _get_key() -> str | None:
    """取 DashScope API key（与主模型同一把 key），缺省返回 None"""
    return os.getenv("DASHSCOPE_API_KEY") or None


def _cfg(key: str, default):
    """从 rag_conf['rerank'] 读取配置项，容错缺键"""
    try:
        rr = rag_conf.get("rerank", {}) or {}
        val = rr.get(key, default)
        return default if val is None else val
    except Exception:
        return default


def rerank_enabled() -> bool:
    """rerank 功能是否开启（config/rag.yml -> rerank.enabled）"""
    try:
        return bool((rag_conf.get("rerank") or {}).get("enabled", True))
    except Exception:
        return False


def rerank_docs(query: str, documents: list[Document], top_n: int | None = None) -> list[Document] | None:
    """
    用 DashScope text-rerank 对 documents 精排，返回按相关性降序的前 top_n 条 Document。
    入参：
        query      - 用户查询
        documents  - 召回候选 Document 列表（page_content 为被排序文本）
        top_n      - 返回条数；None 时用 config 的 rerank.top_n
    返回：
        精排后的 Document 列表；rerank 不可用/失败时返回 None（调用方应回退原候选）。
    """
    if not query or not documents:
        return None
    if top_n is None:
        top_n = _cfg("top_n", 3)

    api_key = _get_key()
    if not api_key:
        logger.warning("[rerank]未配置 DASHSCOPE_API_KEY，跳过 rerank（回退向量召回）")
        return None

    # DashScope 不接受空文档：过滤空文本
    docs = [d for d in documents if (d.page_content or "").strip()]
    if len(docs) < 2:
        return docs  # 太少无需精排
    if not docs:
        return None

    texts = [d.page_content for d in docs]

    for model in (_cfg("model", "gte-rerank-v2"), _cfg("fallback_model", "qwen3-rerank")):
        try:
            import dashscope
            resp = dashscope.TextReRank.call(
                model=model,
                query=query,
                documents=texts,
                top_n=min(top_n, len(texts)),
                return_documents=True,
                api_key=api_key,
            )
            if resp is None or resp.status_code != 200:
                logger.warning(f"[rerank]{model} 返回异常 status={getattr(resp, 'status_code', None)}，试下一个模型")
                continue

            # 解析结果：resp.output.results = [{index, relevance_score, document:{text}},...]
            results = resp.output.get("results", []) if hasattr(resp, "output") else []
            if not results:
                logger.warning(f"[rerank]{model} 无有效结果，试下一个模型")
                continue

            ordered: list[Document] = []
            for item in results:
                idx = item.get("index")
                if idx is None or idx >= len(docs):
                    continue
                ordered.append(docs[idx])
            if not ordered:
                logger.warning(f"[rerank]{model} 排序结果为空")
                continue

            logger.info(f"[rerank]{model} 精排 {len(texts)} 条 → 取 {len(ordered)} 条")
            return ordered
        except Exception as e:
            logger.warning(f"[rerank]{model} 调用失败：{str(e)[:150]}，试下一个模型（或回退）")
            continue

    # 全部模型都失败：回退
    logger.error("[rerank]所有 rerank 模型均失败，回退到向量召回前 %s 条", top_n)
    return None


if __name__ == '__main__':
    # 直接运行此文件时，测试 rerank
    _docs = [
        Document(page_content="退款审核通过后，款项将在1-3个工作日内原路返回支付账户。"),
        Document(page_content="宫保鸡丁是一道经典川菜，主料为鸡丁、花生米、干辣椒。"),
        Document(page_content="会员享受免配送费、专属折扣、积分加倍等权益。"),
        Document(page_content="申请退款需在订单详情页点击按钮，提交原因后客服24小时内审核。"),
    ]
    _top = rerank_docs("退款多久到账", _docs, top_n=2)
    print("rerank_enabled:", rerank_enabled())
    if _top is None:
        print("rerank 不可用或失败（返回 None，调用方将回退）")
    else:
        for d in _top:
            print(" -", d.page_content[:40])
