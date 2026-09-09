# AI 管理后台 API（配置查看/修改、知识库统计、FAQ、会话管理、离线评估触发）
# 挂到 api_service.py： from ai_admin import router as ai_router; app.include_router(ai_router)
# 前端（sky-admin-front /ai 页）直连本服务 :8000 调这些接口。
# 说明：配置修改写回 config/*.yml（写前自动备份 .bak），"重启 Agent 生效"。

import os
import shutil
import tempfile
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional

import yaml

from fastapi import Depends  # 管理鉴权依赖

from utils.path_tool import get_abs_path
from utils.logger_handler import logger
from utils import config_handler
from utils.admin_auth import require_admin_token  # opt-in 管理 token 校验

router = APIRouter(prefix="/ai", tags=["ai-admin"])

# ---- 允许被前端查看/修改的配置映射：{端点语义key: (yml路径, yml内路径dotted)} ----
# 值一律走内存 dict，写时按 dotted path 回写
_CONFIG_SOURCES = {
    "agent": ("config/agent.yml", config_handler.agent_conf),
    "rag": ("config/rag.yml", config_handler.rag_conf),
    "conv": ("config/conv.yml", config_handler.conv_conf),
    "chroma": ("config/chroma.yml", config_handler.chroma_conf),
}


def _read_yml(rel: str) -> dict:
    with open(get_abs_path(rel), "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=yaml.FullLoader) or {}


def _write_yml_backup(rel: str, data: dict) -> None:
    """写 yml 前先备份为 .bak，再原子写回（防写坏导致 Agent 起不来）"""
    abs_path = get_abs_path(rel)
    # 备份
    try:
        shutil.copy(abs_path, abs_path + ".bak")
    except Exception as e:
        logger.warning(f"[ai_admin]备份 {rel} 失败（继续）：{e}")
    # 原子写
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(abs_path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    os.replace(tmp, abs_path)
    logger.info(f"[ai_admin]已写回 {rel}")


def _dget(d: dict, path: str):
    """按 dotted path 取嵌套值，如 'rerank.enabled'"""
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _dset(d: dict, path: str, value):
    """按 dotted path 设嵌套值，自动建中间 dict"""
    keys = path.split(".")
    cur = d
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


# ================= GET /ai/config =================
@router.get("/config", dependencies=[Depends(require_admin_token)])
def get_ai_config():
    """汇总返回当前可配置能力（供前端展示与编辑）"""
    return {
        "scene": _dget(config_handler.agent_conf, "scene"),
        "web_search": {
            "enabled": bool(os.getenv("TAVILY_API_KEY")),  # 由 key 是否配置决定
            "key_set": bool(os.getenv("TAVILY_API_KEY")),
            "note": "由 .env 的 TAVILY_API_KEY 控制（填了即启用）",
        },
        "rerank": {
            "enabled": bool(_dget(config_handler.rag_conf, "rerank.enabled")),
            "model": _dget(config_handler.rag_conf, "rerank.model"),
            "top_n": _dget(config_handler.rag_conf, "rerank.top_n"),
            "fallback_model": _dget(config_handler.rag_conf, "rerank.fallback_model"),
        },
        "vision_model": _dget(config_handler.rag_conf, "vision_model_name"),
        "models": {
            "chat_model_name": _dget(config_handler.rag_conf, "chat_model_name"),
            "embedding_model_name": _dget(config_handler.rag_conf, "embedding_model_name"),
            "rerank_model": _dget(config_handler.rag_conf, "rerank.model"),
            "rerank_fallback_model": _dget(config_handler.rag_conf, "rerank.fallback_model"),
            "vision_model_name": _dget(config_handler.rag_conf, "vision_model_name"),
        },
        "faq": {
            "path": _dget(config_handler.agent_conf, "faq_path"),
            "count": _faq_count(),
        },
        "mcp": {
            "enabled": bool(_dget(config_handler.agent_conf, "enable_mcp_tools")),
            "transport": _dget(config_handler.agent_conf, "mcp_server.transport"),
        },
        "conv": {
            "budget": _dget(config_handler.conv_conf, "history_char_budget"),
            "protected_rounds": _dget(config_handler.conv_conf, "protected_rounds"),
        },
        "session_db": os.path.basename(config_handler.agent_conf.get("session_save_dir", "")),
    }


# ================= GET /ai/model-options =================
# 每类模型的候选清单（可自行输入不在清单里的模型）。基于阿里云百炼常见模型。
_MODEL_OPTIONS = {
    # 对话 LLM 只留 3 个：默认 deepseek-v4-flash + qwen 强力(qwen3.7-max) + 中档(qwen3.7-plus)
    "chat_model_name": ["deepseek-v4-flash", "qwen3.7-max", "qwen3.7-plus"],
    "embedding_model_name": ["text-embedding-v4", "text-embedding-v3", "text-embedding-v2",
                             "text-embedding-v1"],
    # 多模态图文向量模型：走专用多模态向量端点，2560 维（换模型后需重建图文库 agent_*_mm）
    "multimodal_embedding_model_name": ["qwen3-vl-embedding", "qwen2.5-vl-embedding"],
    "rerank_model": ["gte-rerank-v2", "qwen3-rerank"],
    "rerank_fallback_model": ["qwen3-rerank", "gte-rerank-v2"],
    "vision_model_name": ["qwen-vl-plus", "qwen-vl-max", "qwen-vl-ocr"],
}

_MODEL_LABELS = {
    "chat_model_name": "对话 LLM（Agent 推理 / RAG 总结 / 评估裁判）",
    "embedding_model_name": "文本向量模型（文本知识库入库 + 检索）",
    "multimodal_embedding_model_name": "多模态向量模型（图文知识库 agent_*_mm，2560维）",
    "rerank_model": "Rerank 精排（主）",
    "rerank_fallback_model": "Rerank 精排（备选回退）",
    "vision_model_name": "视觉读图（图片理解工具）",
}


@router.get("/model-options", dependencies=[Depends(require_admin_token)])
def get_model_options():
    """返回 4 类模型的当前值 + 可选候选，供前端下拉配置"""
    from utils.config_handler import rag_conf as _rc
    current = {
        "chat_model_name": _rc.get("chat_model_name", ""),
        "embedding_model_name": _rc.get("embedding_model_name", ""),
        "multimodal_embedding_model_name": (_rc.get("multimodal") or {}).get("model", ""),
        "rerank_model": (_rc.get("rerank") or {}).get("model", ""),
        "rerank_fallback_model": (_rc.get("rerank") or {}).get("fallback_model", ""),
        "vision_model_name": _rc.get("vision_model_name", ""),
    }
    return {
        "current": current,
        "options": _MODEL_OPTIONS,
        "labels": _MODEL_LABELS,
        # 模型配置项在 yml 的落点（PUT 用它，避免前端硬编码文件/路径）
        "targets": {
            "chat_model_name": {"file": "rag", "path": "chat_model_name"},
            "embedding_model_name": {"file": "rag", "path": "embedding_model_name"},
            "multimodal_embedding_model_name": {"file": "rag", "path": "multimodal.model"},
            "rerank_model": {"file": "rag", "path": "rerank.model"},
            "rerank_fallback_model": {"file": "rag", "path": "rerank.fallback_model"},
            "vision_model_name": {"file": "rag", "path": "vision_model_name"},
        },
    }


def _faq_count() -> int:
    try:
        from agent.tools.faq_tool import load_faq
        return len(load_faq())
    except Exception:
        return 0


# ================= PUT /ai/config =================
class ConfigItem(BaseModel):
    file: str            # agent | rag | conv | chroma
    path: str            # dotted path，如 rerank.enabled / scene / history_char_budget
    value: object = None


class AiConfigUpdate(BaseModel):
    items: list[ConfigItem]


@router.put("/config", dependencies=[Depends(require_admin_token)])
def put_ai_config(req: AiConfigUpdate):
    """按 dotted path 批量写回 config yml。请求体：{"items":[{"file":"rag","path":"rerank.enabled","value":false}]}
    写前自动备份 .bak。
    与旧行为差异：除写磁盘外，**同步更新内存配置字典**（config_handler.<file>_conf），使
    GET /ai/config 与正在运行的 Agent 立即读到新值——大部分开关(rerank/mcp/vision/预算)即时生效；
    但模型类(chat_model_name 等)由 model/factory 在启动时构造单例 LLM，需重启才真正切换模型（响应中说明）。"""
    allowed = {"agent", "rag", "conv", "chroma"}
    if not req.items:
        raise HTTPException(status_code=400, detail="需要 items:[{file,path,value}]")

    # 分文件段收集修改，先读磁盘最新再改再写回（避免并发覆盖整文件）
    per_file: dict[str, dict] = {}
    for it in req.items:
        if it.file not in allowed or not it.path:
            raise HTTPException(status_code=400, detail="file/path 不合法")
        if it.file not in per_file:
            per_file[it.file] = _read_yml(_CONFIG_SOURCES[it.file][0])
        _dset(per_file[it.file], it.path, it.value)

    for f, data in per_file.items():
        _write_yml_backup(_CONFIG_SOURCES[f][0], data)
        # ★ 同步内存字典：让 GET /ai/config 及运行中 Agent 立即读到新值（不回显旧值）
        mem = _CONFIG_SOURCES[f][1]
        for it in req.items:
            if it.file == f:
                _dset(mem, it.path, it.value)

    # 判断是否涉及"启动时构造单例"的模型项（这类仍需重启才真正生效）
    model_paths = {"chat_model_name", "embedding_model_name", "rerank.model",
                   "rerank.fallback_model", "vision_model_name"}
    needs_restart = any(it.file == "rag" and it.path in model_paths for it in req.items)
    msg = ("已保存并即时生效。" if not needs_restart
           else "已保存并更新内存配置；但模型项由启动时构造的 LLM 单例使用，切换模型需重启 Agent 服务。")
    return {"ok": True, "msg": msg, "written": list(per_file.keys())}


# ================= GET /ai/kb =================
@router.get("/kb", dependencies=[Depends(require_admin_token)])
def get_ai_kb():
    """两场景向量库信息 + 源文件列表"""
    result = {}
    try:
        from rag.vector_store import VectorStoreService
        for scene in ("sky", "robot"):
            vs = VectorStoreService(scene=scene)
            try:
                count = vs.vector_store._collection.count()
            except Exception as e:
                count = -1
                logger.warning(f"[ai_admin]读 {scene} collection 失败：{e}")
            result[scene] = {
                "collection": vs.vector_store._collection.name if hasattr(vs.vector_store, "_collection") else "?",
                "chunks": count,
            }
            # 多模态图文集合（agent_mm / agent_sky_mm）
            try:
                from rag.multimodal_store import MultimodalVectorStore
                mm = MultimodalVectorStore(scene=scene)
                result[scene]["collection_mm"] = mm.collection.name
                result[scene]["mm_images"] = mm.count()
            except Exception as e:
                result[scene]["collection_mm"] = "-"
                result[scene]["mm_images"] = -1
                logger.warning(f"[ai_admin]读 {scene} 多模态集合失败：{e}")
    except Exception as e:
        logger.error(f"[ai_admin]kb 读取失败：{e}")

    # 源文件：data/ 下 txt/pdf + data/kb/{scene} 页面上传 + md5 记录行数
    from utils.file_handler import listdir_with_allowed_type, get_abs_path as _g
    files = list(listdir_with_allowed_type(get_abs_path("data"), (".txt", ".pdf")))
    for sc in ("sky", "robot"):
        kb_dir = get_abs_path(os.path.join("data", "kb", sc))
        if os.path.isdir(kb_dir):
            files += list(listdir_with_allowed_type(kb_dir, (".txt", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")))
    file_names = sorted(os.path.basename(x) for x in files)
    return {"vector": result, "source_files": file_names}


# ================= POST /ai/kb/upload =================
# 页面上传知识文件入库（登录后的 AI 管理后台使用）。
# 流程：文件落到 data/kb/<scene>/（场景隔离，文本库/多模态扫描都会纳入）→
#       触发对应场景的现有入库（文本 load_document / 多模态 multimodal_ingest），md5 去重、可重复跑。
_MAX_KB_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB（文本/单图足够）


@router.post("/kb/upload", dependencies=[Depends(require_admin_token)])
def upload_kb_file(
    scene: str = Form(...),          # robot | sky
    kind: str = Form("auto"),        # text | image | pdf | auto
    file: UploadFile = File(...),
):
    if scene not in ("robot", "sky"):
        raise HTTPException(status_code=400, detail="scene 需为 robot 或 sky")
    orig_name = (file.filename or "").strip()
    # NEM-002：防路径穿越——只取纯文件名（剥掉任意目录成分），并拒绝隐藏/保留名
    orig_name = os.path.basename(orig_name.replace("\\", "/"))
    ext = os.path.splitext(orig_name)[1].lower()
    if not orig_name or orig_name.startswith(".") or orig_name in (".", ".."):
        raise HTTPException(status_code=400, detail="文件名不合法")

    data = file.file.read()
    try:
        if len(data) > _MAX_KB_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="文件需小于 20MB")
        if not data:
            raise HTTPException(status_code=400, detail="文件内容为空")
    finally:
        file.file.close()

    # 保存到 data/kb/<scene>/；保留原文件名（避免同名冲突：冲突时追加时间戳）
    kb_dir = get_abs_path(os.path.join("data", "kb", scene))
    os.makedirs(kb_dir, exist_ok=True)
    save_name = orig_name
    if os.path.exists(os.path.join(kb_dir, save_name)):
        stem, e = os.path.splitext(save_name)
        save_name = f"{stem}_{int(__import__('time').time())}{e}"
    with open(os.path.join(kb_dir, save_name), "wb") as f:
        f.write(data)
    rel_path = f"data/kb/{scene}/{save_name}"

    # 触发入库（同步；现有函数按 md5 去重，可安全全量跑）
    ingested = {"text": False, "multimodal": False}
    try:
        # 文本：txt/pdf 由 VectorStoreService.load_document 统一处理
        if ext in (".txt", ".pdf"):
            from rag.vector_store import VectorStoreService
            VectorStoreService(scene=scene).load_document()
            ingested["text"] = True
        # 多模态：图片 / 含图 PDF 由 multimodal_ingest 处理
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf"):
            from rag.multimodal_ingest import ingest_independent_images, ingest_pdf_images, _media_store
            store = _media_store(scene)
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                ingest_independent_images(store, scene, "data")
            else:
                ingest_pdf_images(store, scene, "data")
            ingested["multimodal"] = True
    except Exception as e:
        logger.error(f"[ai_admin]上传后入库失败 {rel_path}：{str(e)[:200]}", exc_info=True)
        return {"ok": True, "saved": rel_path, "ingested": ingested,
                "warning": f"文件已保存但入库出错：{str(e)[:150]}（可稍后重跑重建）"}
    return {"ok": True, "saved": rel_path, "ingested": ingested}


# ================= GET /ai/faq =================
@router.get("/faq", dependencies=[Depends(require_admin_token)])
def get_ai_faq():
    """FAQ 问答列表"""
    try:
        from agent.tools.faq_tool import load_faq
        faqs = load_faq()
        return {"total": len(faqs), "items": faqs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取 FAQ 失败：{e}")


# ================= GET /ai/sessions =================
@router.get("/sessions", dependencies=[Depends(require_admin_token)])
def list_all_sessions(user_id: Optional[str] = None):
    """会话管理：列出某用户（或全部主要用户）会话。user_id 为空列出全部主要用户。"""
    import utils.session_store as ss
    if user_id:
        rows = ss.load_saved_sessions(user_id=user_id)
        return {"sessions": rows}
    # 列出 default + 常见用户的并集（这里简单列 default 便于管理页展示）
    # 更通用：读库按 user_id 分组
    sessions = ss.load_saved_sessions(user_id="default")
    return {"sessions": sessions, "note": "默认展示 default 用户会话；可按 ?user_id 过滤"}


@router.delete("/sessions/{session_id}", dependencies=[Depends(require_admin_token)])
def delete_one_session(session_id: str, user_id: Optional[str] = None):
    """删除任意用户会话（管理用，需归属校验一致）"""
    import utils.session_store as ss
    ok = ss.delete_session(session_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在或不属于该用户")
    return {"status": "deleted"}


# ================= GET /ai/eval/sample & POST /ai/eval =================
@router.get("/eval/sample", dependencies=[Depends(require_admin_token)])
def eval_sample():
    from evaluation.dataset import sample_dataset
    return {"samples": sample_dataset()}


class EvalRequest(BaseModel):
    dataset_path: Optional[str] = None
    category: Optional[str] = None
    limit: Optional[int] = 2  # 默认小 limit，避免同步请求过久


@router.post("/eval", dependencies=[Depends(require_admin_token)])
def run_ai_eval(req: EvalRequest):
    """触发离线评估（同步；前端请控制 limit 以免超时）"""
    try:
        from evaluation.run_eval import run_evaluation
        report = run_evaluation(
            dataset_path=req.dataset_path,
            category=req.category,
            limit=req.limit,
        )
        return report
    except Exception as e:
        logger.error(f"[ai_admin]eval 失败：{e}")
        raise HTTPException(status_code=500, detail=f"评估失败：{str(e)[:200]}")
