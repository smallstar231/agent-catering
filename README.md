<div align="center">

# LangChain ReAct Agent · 苍穹外卖智能客服

**基于 LangChain + ReAct + RAG 的智能客服系统，集成苍穹外卖（SkyTakeOut）全栈业务与多模态图文知识库**

</div>

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-1.0-green)](https://www.langchain.com/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-2.7.3-brightgreen)](https://spring.io/projects/spring-boot)
[![Vue](https://img.shields.io/badge/Vue-2.6-4fc08d)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-teal)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](./LICENSE)

---

## 📖 项目简介

**智能客服全栈系统**（Monorepo），三大端协同；Python Agent 侧已从纯文本 RAG 演进为 **多模态图文检索 + 工具型 Agent + AI 管理后台**：

| 端 | 技术栈 | 职责 |
|---|--------|------|
| **🤖 Python Agent** | FastAPI + LangChain + Chroma + DashScope | AI 引擎：ReAct 推理、19 个工具、双路 RAG（文本 + 多模态图文）、SSE 流式、上传识图/文件 |
| **☕ Spring Boot 后端** | Java 8 + Spring Boot 2.7 + MyBatis | 苍穹外卖业务 REST API（admin/user 双端） |
| **🖥️ Vue 前端** | Vue 2.6 + TypeScript + Element UI | 管理后台 + **AI 智能客服对话页** + **AI 配置/运维管理页** |

### 核心架构

```
用户 (Vue 前端 :8888)
   │  SSE 流式 (/chat/stream)      ← 附件拖拽/粘贴 → :8000 /upload/file
   ▼
Python Agent (:8000)  ────────────────────────────────┐
   │                                                   │
   ├─ ReAct Agent：Thought→Action→Observation 循环      │
   │   19 工具（RAG/菜品/订单/报表/联网/读图/文件/代码沙箱…）│
   ├─ RAG 双路检索：                                    │
   │   · 文本库  text-embedding-v4（Chroma）            │
   │   · 图文库  qwen3-vl-embedding 2560维（Chroma）     │
   │     （以文搜图 + PDF 抽图 + 图回显）                │
   ├─ Rerank 精排（gte-rerank-v2 交叉排序）             │
   ├─ 会话管理（SQLite 持久化，按用户隔离）              │
   └─ AI 管理 API（/ai/*：配置/模型/知识库/FAQ/评测/会话）│
         ▲                                              │
   Spring Boot 后端 (:8080)   ← 苍穹外卖业务（登录/菜品/订单/报表）
   (Vue :8888 也直连 Agent :8000 做对话，绕过 Java 转发)
```

---

## ✨ 核心特性

### 🤖 AI Agent
| 特性 | 说明 |
|---|---|
| **ReAct 推理** | Thought→Action→Observation 循环，自主选工具；支持思考链(reasoning)回流 |
| **19 个工具** | RAG 检索、菜品/套餐/分类/订单查询、报表生成、天气、**真实联网搜索**、**网页正文**、**读图**、**FAQ 精确命中**、**txt/pdf 解析**、**代码沙箱**、外部数据拉取 |
| **双场景** | `scene` 切换「苍穹外卖(sky)」/「机器人(robot)」，各配独立提示词 + 知识库 |
| **多模态图文 RAG** | qwen3-vl-embedding 融合向量，**以文搜图**；PDF 内嵌图自动抽取入库；命中图由后端保证回显 |
| **Rerank 精排** | 高召回 → gte-rerank-v2 交叉精排 → Top-K 喂 LLM（可开关、带 fallback） |
| **工具透明** | 前端实时展示"正在调用 XX"气泡；图/附件命中自动展示 |
| **流式输出** | SSE 逐 token 推送（文本 / 工具事件 / 思考链三类事件） |
| **历史压缩** | 超字符预算自动裁剪旧轮，保护最近 N 轮语义 |
| **可选 MCP 工具** | `enable_mcp_tools` 挂载外部 MCP server（faq / kb / web_search） |

### 🖥️ AI 管理后台（/ai 页，前端 ai-config）
| 能力 | 说明 |
|---|---|
| **AI 能力开关** | 联网搜索、Rerank、MCP、视觉读图模型、会话压缩预算、FAQ 统计 |
| **模型配置** | 对话 LLM / 文本向量 / **多模态向量** / Rerank / 视觉 五类模型下拉（可自填） |
| **知识库控制台** | 双场景文本/图文集合统计、源文件列表、**页面上传入库**（txt/pdf/图片 → 自动进文本库或图文库） |
| **FAQ 管理** | 问答对折叠展示 |
| **离线评估** | 批量跑 Agent + exact_match & LLM-judge 打分 |
| **会话历史** | 跨用户查看 / 删除（SQLite） |

> AI 管理接口默认本地零配置可用；可设 `AI_ADMIN_TOKEN` 开启 opt-in 鉴权（见下"安全"）。

### ☕ 苍穹外卖后端 + 🖥️ Vue 前端
- 管理端：员工 / 分类 / 菜品 / 套餐 / 订单 / 营业状态 / 数据统计
- JWT 双 Token（admin + user）、Redis 缓存、阿里云 OSS（历史；附件现主要走 Agent 本地）
- AI 聊天页支持：流式对话、图片/文件**拖拽或 Ctrl+V 粘贴上传**、会话侧栏持久化

---

## 🗂️ 项目结构（Python Agent 为主）

```
LangChain-ReAct-Agent/
│
├── api_service.py               # FastAPI :8000 入口：/chat /chat/stream /upload/file /sessions /files(静态) 挂 /ai
├── ai_admin.py                  # AI 管理后台 API（/ai/config · /ai/kb · /ai/kb/upload · /ai/faq · /ai/sessions · /ai/eval）
├── app.py                       # 独立 Streamlit 对话入口（备选）
├── mcp_server.py                # 可选 MCP server（stdio，暴露 faq/kb/web_search）
├── start_all_services.py        # 一键启动 Python + Spring Boot + Vue
│
├── agent/
│   ├── react_agent.py           #   ReAct Agent：组装模型+提示词+19工具+3中间件，SSE 事件流
│   └── tools/
│       ├── agent_tools.py       #   通用/苍穹外卖业务工具 + sky 登录(读.env)
│       ├── middleware.py        #   工具监控 / 模型日志 / 动态提示词切换
│       ├── web_search.py        #   真实联网（Tavily）
│       ├── page_reader.py       #   网页正文（含 SSRF 防护）
│       ├── describe_image/vision.py # 读图（qwen-vl）
│       ├── file_reader.py       #   txt/pdf 附件解析
│       ├── faq_tool.py          #   FAQ 精确命中
│       ├── code_sandbox.py      #   受限 Python 沙箱（子进程+黑名单+超时）
│       ├── mcp_client_tool.py   #   外部 MCP 工具挂载
│       └── ...（get_weather 等通用小工具）
│
├── rag/
│   ├── vector_store.py          #   文本向量库：Chroma + text-embedding-v4 + MD5 去重
│   ├── rag_service.py           #   双路召回（文本+图文）→ 合并 → 总结
│   ├── rerank.py                #   DashScope text-rerank 精排
│   ├── multimodal_embedding.py  #   qwen3-vl-embedding 适配器（2560维，图/文/融合）
│   ├── multimodal_store.py      #   图文集合直插直查（agent_mm/agent_sky_mm）
│   ├── multimodal_ingest.py     #   图文入库脚本（--scene --rebuild）
│   └── pdf_image_extractor.py   #   PyMuPDF 抽 PDF 内嵌图
│
├── model/factory.py             # ChatOpenAI + DashScopeEmbedding 单例
├── config/*.yml                 # agent / rag / chroma / conv / prompts 配置
├── prompts/                     # 普通/RAG/报表 提示词 × 双场景
├── utils/
│   ├── config_handler.py        # YAML 加载 → 全局单例（*_conf）
│   ├── session_store.py         # SQLite 会话库（save/load/delete）
│   ├── history_compressor.py    # 会话历史压缩
│   ├── admin_auth.py            # /ai/* opt-in token 鉴权依赖
│   ├── file_handler.py          # 文件加载 / MD5
│   ├── prompt_loader.py         # 提示词读取
│   └── ...
│
├── evaluation/                  # 离线评测（dataset / evaluators / run_eval）
├── data/                        # 知识库源 + 运行时（uploads/ kb/ sessions/ 向量库均 gitignore）
├── sky-take-out/                # ☕ Spring Boot（sky-common / pojo / server）
├── sky-admin-front/             # 🖥️ Vue（views/ai-chat, views/ai-config, api/ai.ts）
├── requirements.txt
├── STARTUP.md                   # 完整启动指南
└── README.md
```

---

## 🚀 快速启动

> 完整细节见 [STARTUP.md](./STARTUP.md)

### 依赖
| 依赖 | 版本 | 用途 |
|---|---|---|
| Python | ≥ 3.10（建议 3.12） | Agent 服务 |
| Java + Maven | ≥ 8 / ≥ 3.6 | Spring Boot |
| Node.js | ≥ 16 | Vue 前端 |
| MySQL / Redis | 8.0 / 3.x | 苍穹外卖业务 |

### 环境变量（根 `.env`，从 `.env.example` 复制）
```bash
DASHSCOPE_API_KEY=xxx            # 必须：对话/向量/Rerank/读图共用
TAVILY_API_KEY=xxx               # 可选：真实联网搜索
SKY_ADMIN_USERNAME=admin         # 苍穹外卖管理端登录（Agent 调业务 API 用）
SKY_ADMIN_PASSWORD=xxx           # 必填（不设则 Agent 不尝试登录）
AI_ADMIN_TOKEN=xxx               # 可选：开启 /ai/* 管理接口鉴权
```
> ⚠️ `.env` 与 `**/application-dev.yml` 已 gitignore，切勿提交。

### 一键启动（顺序：Redis → MySQL → Agent → Spring → Vue）
```bash
python start_all_services.py       # 用项目 .venv 的 python 运行
# 或分别：
# ① Python Agent
.venv\Scripts\uvicorn api_service:app --host 0.0.0.0 --port 8000
# ② Spring Boot
java -jar sky-take-out/sky-server/target/sky-server-1.0-SNAPSHOT.jar --spring.profiles.active=dev
# ③ Vue 前端
cd sky-admin-front && npx vue-cli-service serve   # :8888
```

### 多模态图文库初始化（可选）
```bash
# 苍穹外卖场景：独立图 + PDF 内嵌图入库到图文集合
.venv\Scripts\python -m rag.multimodal_ingest --scene sky
# 清空重建
.venv\Scripts\python -m rag.multimodal_ingest --scene sky --rebuild
```

### 验证
| 服务 | 地址 | 验证 |
|---|---|---|
| Agent | `http://localhost:8000/` | `{"status":"ok"}` 健康检查 |
| 对话 SSE | `POST /chat/stream` | `{"query":"宫保鸡丁多少钱"}` |
| Swagger | `http://localhost:8000/docs` | FastAPI 交互文档 |
| 后端 | `http://localhost:8080/admin/employee/login` | 登录取 JWT |
| 前端 | `http://localhost:8888` | 登录 → **AI 客服** / **AI 配置** |

---

## 🧠 模型与场景

### 对话模型
阿里云百炼 OpenAI 兼容接口（`base_url=…/compatible-mode/v1`）。`config/rag.yml`：
```yaml
chat_model_name: deepseek-v4-flash   # 默认（思考型）
# chat_model_name: qwen3.7-max       # 更强
# chat_model_name: qwen3.7-plus      # 中档
embedding_model_name: text-embedding-v4   # 文本向量
vision_model_name: qwen-vl-plus           # 读图
multimodal:
  enabled: true
  model: qwen3-vl-embedding              # 图文向量（2560维；换模型需 --rebuild）
```

### 场景切换（`config/agent.yml`）
```yaml
scene: sky     # 苍穹外卖客服（默认）
# scene: robot  # 扫地机器人问答
```
> 场景决定基础提示词、知识库加载范围（sky 只收"苍穹外卖*"文档）与业务工具集合。

---

## 🔐 安全

| 项 | 说明 |
|---|---|
| **文件上传** | 扩展名白名单 + 文件头魔数校验 + uuid 落盘；kb 上传对文件名 basename 白名单防路径穿越 |
| **SSRF 防护** | `page_reader`/`file_reader` 拒内网/环回/保留地址，可配置白名单主机 |
| **代码沙箱** | 子进程 + 15s 超时 + import 黑名单 + 受限 builtins，非完全隔离 |
| **管理接口鉴权** | `/ai/*` 支持 `AI_ADMIN_TOKEN` opt-in 强制校验（`X-AI-Admin-Token` 头，常量时间比较）；未配置则放行 |
| **凭据不入库** | `.env`、`application-dev.yml` 已 gitignore；苍穹外卖登录密码从 env 读取，无硬编码兜底 |

---

## 🛠️ 技术栈总览

| 层级 | 技术 |
|---|---|
| **LLM** | 通义千问系 / deepseek-v4-flash（DashScope OpenAI 兼容） |
| **Agent 框架** | LangChain + LangGraph + ReAct 中间件 |
| **向量库** | Chroma（文本 + 多模态图文双集合） |
| **AI 服务** | FastAPI + Uvicorn + SSE |
| **搜索/RAG** | Tavily、DashScope text-rerank、qwen3-vl-embedding、PyMuPDF |
| **后端** | Spring Boot 2.7.3 + MyBatis |
| **存储** | MySQL 8 + Redis + SQLite（会话） |
| **前端** | Vue 2.6 + TypeScript + Element UI |
| **构建** | Maven + Vue CLI |

---

## 📝 License

MIT © [smallstar231](https://github.com/smallstar231)
