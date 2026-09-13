# AI 管理后台鉴权依赖
#
# ┌─【本文件速览】─────────────────────────────────────────────────────┐
# │ 项目位置：应用层（管理接口的安全守卫）                               │
# │ 上游：.env（AI_ADMIN_TOKEN）、logger                                 │
# │ 下游：ai_admin.py 的 10 个路由（dependencies=[Depends(require_admin_token)]）│
# │ 核心概念：FastAPI 依赖注入（Depends）——把鉴权做成"可复用的函数依赖"   │
# │ opt-in 策略（为什么这样设计）：                                      │
# │   · .env 未配 AI_ADMIN_TOKEN → 放行（本地开发零配置可用）            │
# │   · 配了 → 强制要求请求头 X-AI-Admin-Token 匹配                      │
# │ 安全要点：用 secrets.compare_digest 做常量时间比较，防时序侧信道攻击  │
# │ 前端配合：ai.ts 从 VUE_APP_AI_ADMIN_TOKEN 读取并注入请求头          │
# │ 设计取舍：这是"opt-in 自选强度"——默认不打扰开发，需要时一键加固      │
# └────────────────────────────────────────────────────────────────────┘
#
# 策略（opt-in 强制校验）：
#   - 根 .env 配置 AI_ADMIN_TOKEN 后，/ai/* 及 /sessions 管理接口强制要求请求头携带 X-AI-Admin-Token 匹配；
#   - 未配置该 env 时放行（保持现有本地部署零配置可用）。
#   - 用 secrets.compare_digest 做常量时间比较，防时序侧信道。
import os
import secrets
from fastapi import Header, HTTPException
from utils.logger_handler import logger


def _configured_token() -> str | None:
    tok = os.getenv("AI_ADMIN_TOKEN", "").strip()
    return tok or None


def require_admin_token(x_ai_admin_token: str | None = Header(default=None)) -> None:
    """FastAPI 依赖：未配置 token 放行；已配置则校验 X-AI-Admin-Token 头。"""
    tok = _configured_token()
    if tok is None:
        return  # opt-in：未启用鉴权
    provided = (x_ai_admin_token or "").strip()
    if not provided or not secrets.compare_digest(provided, tok):
        # 避免在日志里回显 token
        logger.warning("[admin_auth]管理接口鉴权失败（token 缺失或不匹配）")
        raise HTTPException(status_code=401, detail="AI 管理接口需要有效 token（X-AI-Admin-Token）")
