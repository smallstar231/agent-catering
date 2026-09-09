# FastAPI 服务：将 ReactAgent 包装为 HTTP API
# 被苍穹外卖 Java 后端调用，作为 AI 客服接口
# 运行：uvicorn api_service:app --host 0.0.0.0 --port 8000

import os
import json
import uuid
from fastapi import FastAPI, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agent.react_agent import ReactAgent
from utils.path_tool import get_abs_path
# 会话存储改用 SQLite（替代旧 JSON 文件实现，函数签名一致，前端 API 不变）
from utils.session_store import save_session_to_disk, load_saved_sessions, get_session_messages, delete_session as sqlite_delete_session

# 创建 FastAPI 服务实例
app = FastAPI(title="AI客服Agent服务")

# 上传文件落盘目录：data/uploads（图片 + txt/pdf 附件输入用），并静态挂载 /files 供 Agent/前端读取
UPLOAD_DIR = get_abs_path("data/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
# 允许上传的文件扩展名白名单（图片 + txt/pdf 纯文本类）
# 注：图片原走 Spring OSS（Key 曾失效致上传静默失败），现统一改走本服务本地存储 + /files 托管
ALLOWED_UPLOAD_EXTS = {".txt", ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# 允许跨域（苍穹外卖前端直接连 SSE 端点）

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8888", "http://127.0.0.1:8888"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# AI 管理后台 API（/ai/*）：配置查看/修改、知识库统计、FAQ、会话管理、评估触发
from ai_admin import router as ai_admin_router
app.include_router(ai_admin_router)

# 静态托管上传文件：http://host:8000/files/<name>（供 Agent read_file 工具与前端下载读取）
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

# 创建 Agent 实例（全局单例，只初始化一次）
agent = ReactAgent()


# ---- 请求体结构（对应 Java 端的 DTO）----
class ChatRequest(BaseModel):
    query: str            # 用户消息
    history: list | None = None  # 历史消息，默认为空


# ---- 聊天接口（同步/兼容，攒完一次性返回）----
@app.post("/chat")
def chat(req: ChatRequest):
    """接收用户消息，返回 AI 回复（兼容旧接口）"""
    full_response = ""
    history = req.history or []
    for chunk in agent.execute_stream(req.query, history=history):
        full_response += chunk
    return {"response": full_response.strip()}


# ---- 聊天接口（SSE 流式，逐 token 推送）----
@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """
    接收用户消息，通过 SSE（Server-Sent Events）逐 token 流式返回 AI 回复
    格式（向后兼容：旧前端只读 token 字段，会自动忽略新增的 tool/reasoning）：
        data: {"token": "文本片段"}             # 正文（打字机）
        data: {"tool": {"name":..., ...}}       # 工具调用事件（新前端做"正在调用XX"气泡）
        data: {"reasoning": "思考片段"}          # 思考链片段（新前端可折叠显示）
        data: [DONE]

    注意：必须是 sync 函数——async generator 包裹 sync generator
    会导致 FastAPI 在线程池中攒满整个响应再释放（即"先空白，再瞬间加载"）。
    sync generator 直接传给 StreamingResponse 才能逐 chunk flush。
    """
    def event_generator():
        history = req.history or []
        for event, payload in agent.execute_stream_events(req.query, history=history):
            if event == "text":
                yield f"data: {json.dumps({'token': payload}, ensure_ascii=False)}\n\n"
            elif event == "tool":
                yield f"data: {json.dumps({'tool': payload}, ensure_ascii=False)}\n\n"
            elif event == "reasoning":
                yield f"data: {json.dumps({'reasoning': payload}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ---- 图片 / txt/pdf 附件上传（统一走本地存储）----
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB

# 各类型的文件魔数校验（防伪造扩展名）：jpg/png/gif/webp/bmp/pdf/txt
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_PDF_MAGIC = {b"%PDF-"}
_IMG_MAGIC = {
    b"\x89PNG\r\n\x1a\n": (".png",),
    b"\xff\xd8\xff": (".jpg", ".jpeg"),
    b"GIF8": (".gif",),
    b"RIFF": (".webp",),   # webp 以 RIFF....WEBP 开头
    b"BM": (".bmp",),
}


def _content_matches_ext(data: bytes, ext: str) -> bool:
    """按文件头 magic 校验内容是否与扩展名一致（粗校验，尽力而为）"""
    head = data[:16]
    if ext == ".txt":
        # 文本：前 1024 字节不含 NUL（非二进制）即视为可
        return b"\x00" not in data[:1024]
    if ext == ".pdf":
        return any(head.startswith(m) for m in _PDF_MAGIC)
    for magic, exts in _IMG_MAGIC.items():
        if head.startswith(magic):
            return ext in exts
    # 无匹配 magic → 拒绝（宁可错杀，不放非图片伪装进图片通道）
    return False


@app.post("/upload/file")
def upload_file(file: UploadFile = File(...)):
    """接收 图片 / txt/pdf 附件 → uuid 落盘 data/uploads → 返回可访问的本地 URL + 原文件名。
    前端把返回拼成 [图片:绝对URL] / [文件:绝对URL|原文件名] 标记注入，Agent 见标记自动调 describe_image / read_file。"""
    orig_name = (file.filename or "").strip()
    ext = os.path.splitext(orig_name)[1].lower()
    if not orig_name or ext not in ALLOWED_UPLOAD_EXTS:
        raise HTTPException(status_code=400, detail=f"仅支持 {'/'.join(sorted(ALLOWED_UPLOAD_EXTS))} 文件")

    data = file.file.read()
    try:
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="文件需小于 10MB")
        if not data:
            raise HTTPException(status_code=400, detail="文件内容为空")
        # 内容与扩展名一致性校验（拒绝伪装扩展名）
        if not _content_matches_ext(data, ext):
            raise HTTPException(status_code=400, detail=f"文件内容与扩展名 {ext} 不符，请检查文件是否损坏或类型是否选对")
    finally:
        file.file.close()

    object_name = uuid.uuid4().hex + ext
    out_path = os.path.join(UPLOAD_DIR, object_name)
    with open(out_path, "wb") as f:
        f.write(data)

    # 前端据此拼 [图片:绝对URL] / [文件:绝对URL|原文件名]
    url = f"/files/{object_name}"
    return {"url": url, "name": orig_name, "size": len(data)}


# ========== 会话管理 API ==========

# 用户标识：从请求头 X-User-Id 读取；未传回退 "default"（兼容旧前端）。
# 实现"用户级会话隔离"——每个用户的会话列表/详情/删除互不可见，为接真实登录态留好接口。

def _uid(x_user_id: str | None = None) -> str:
    """解析用户标识：空或 'default' 原样返回，否则截断防注入（只允许字母数字_-）"""
    uid = (x_user_id or "default").strip()
    if not uid or uid.lower() == "default":
        return "default"
    # 安全过滤：仅保留字母数字_-
    import re
    uid = re.sub(r"[^A-Za-z0-9_\-]", "", uid)
    return uid or "default"


class SaveSessionRequest(BaseModel):
    messages: list
    round_count: int = 0
    session_id: str | None = None
    user_id: str | None = None


class DeleteSessionRequest(BaseModel):
    session_id: str


@app.get("/sessions")
def list_sessions(x_user_id: str | None = Header(default=None)):
    """获取指定用户的会话元数据列表——SQLite 持久化，按用户隔离"""
    return {"sessions": load_saved_sessions(user_id=_uid(x_user_id))}


@app.get("/sessions/{session_id}")
def get_session(session_id: str, x_user_id: str | None = Header(default=None)):
    """获取指定会话的完整消息内容（校验归属用户）"""
    messages = get_session_messages(session_id, user_id=_uid(x_user_id))
    if messages is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"messages": messages}


@app.post("/sessions/save")
def save_session(req: SaveSessionRequest, x_user_id: str | None = Header(default=None)):
    """保存或更新当前会话（SQLite，按用户隔离）"""
    filepath, sid = save_session_to_disk(
        req.messages,
        req.round_count,
        session_id=req.session_id,
        user_id=_uid(req.user_id or x_user_id),
    )
    if filepath is None:
        raise HTTPException(status_code=500, detail="保存失败")
    return {"session_id": sid}


@app.post("/sessions/delete")
def delete_session(req: DeleteSessionRequest, x_user_id: str | None = Header(default=None)):
    """删除指定会话（SQLite，校验归属用户）"""
    ok = sqlite_delete_session(req.session_id, user_id=_uid(x_user_id))
    if ok:
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="会话不存在")


# ---- 健康检查接口 ----
@app.get("/")
def health():
    """Java 后端用来检测 Python 服务是否存活"""
    return {"status": "ok", "service": "AI Agent"}
