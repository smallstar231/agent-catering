# FastAPI 服务：将 ReactAgent 包装为 HTTP API
# 被苍穹外卖 Java 后端调用，作为 AI 客服接口
# 运行：uvicorn api_service:app --host 0.0.0.0 --port 8000

import json, os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from agent.react_agent import ReactAgent
from utils.file_handler import save_session_to_disk, load_saved_sessions, load_session_messages
from utils.config_handler import agent_conf
from utils.path_tool import get_abs_path

# 创建 FastAPI 服务实例
app = FastAPI(title="AI客服Agent服务")

# 允许跨域（苍穹外卖前端直接连 SSE 端点）

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8888", "http://127.0.0.1:8888"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    格式：
        data: {"token": "文本片段"}\n\n
        data: [DONE]\n\n

    注意：必须是 sync 函数——async generator 包裹 sync generator
    会导致 FastAPI 在线程池中攒满整个响应再释放（即"先空白，再瞬间加载"）。
    sync generator 直接传给 StreamingResponse 才能逐 chunk flush。
    """
    def event_generator():
        history = req.history or []
        for token in agent.execute_stream(req.query, history=history):
            yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
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


# ========== 会话管理 API ==========

class SaveSessionRequest(BaseModel):
    messages: list
    round_count: int = 0
    session_id: str | None = None


class DeleteSessionRequest(BaseModel):
    session_id: str


SESSION_DIR = agent_conf.get("session_save_dir", "data/sessions")


def _session_path(session_id: str) -> str:
    return os.path.join(get_abs_path(SESSION_DIR), f"{session_id}.json")


@app.get("/sessions")
def list_sessions():
    """获取所有存档会话的元数据列表（不含消息内容）"""
    return {"sessions": load_saved_sessions()}


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    """获取指定会话的完整消息内容"""
    filepath = _session_path(session_id)
    messages = load_session_messages(filepath)
    if messages is None:
        return {"error": "会话不存在"}, 404
    return {"messages": messages}


@app.post("/sessions/save")
def save_session(req: SaveSessionRequest):
    """保存或更新当前会话"""
    filepath, sid = save_session_to_disk(
        req.messages,
        req.round_count,
        session_id=req.session_id,
    )
    if filepath is None:
        return {"error": "保存失败"}, 500
    return {"session_id": sid}


@app.post("/sessions/delete")
def delete_session(req: DeleteSessionRequest):
    """删除指定会话"""
    filepath = _session_path(req.session_id)
    if os.path.exists(filepath):
        os.remove(filepath)
        return {"status": "deleted"}
    return {"error": "会话不存在"}, 404


# ---- 健康检查接口 ----
@app.get("/")
def health():
    """Java 后端用来检测 Python 服务是否存活"""
    return {"status": "ok", "service": "AI Agent"}
