<div align="center">

# LangChain ReAct Agent · 苍穹外卖智能客服

**基于 LangChain + ReAct 范式 + RAG 检索增强的智能客服系统，集成苍穹外卖（SkyTakeOut）全栈业务**

</div>

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-1.0-green)](https://www.langchain.com/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-2.7.3-brightgreen)](https://spring.io/projects/spring-boot)
[![Vue](https://img.shields.io/badge/Vue-2.6-4fc08d)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](./LICENSE)

---

## 📖 项目简介

本项目是一个 **智能客服全栈系统**，采用 Monorepo 架构整合三大端：

| 端 | 技术栈 | 职责 |
|---|--------|------|
| **🤖 Python Agent** | LangChain + ReAct + RAG | AI 对话推理引擎，负责理解用户意图、检索知识库、调用工具、生成回复 |
| **☕ Spring Boot 后端** | Java 8 + Spring Boot 2.7 + MyBatis | 苍穹外卖业务后端，提供 REST API 并转发 AI 请求到 Agent |
| **🖥️ Vue 前端** | Vue 2.6 + TypeScript + Element UI | 苍穹外卖管理后台，含 AI 智能客服对话页面 |

### 核心流程

```
用户 (Vue 前端 :8888)
   │  HTTP / SSE
   ▼
Spring Boot 后端 (:8080)   ←── 苍穹外卖 CRUD 业务
   │  HTTP 转发
   ▼
Python Agent (:8000)       ←── AI 推理
   │
   ├── 通义千问 LLM (DashScope)
   ├── Chroma 向量库 (RAG 检索)
   ├── 13 个工具函数 (天气/订单/菜品/报表等)
   └── 3 个中间件 (监控/日志/动态提示词)
```

---

## 🏗️ 项目结构

```
LangChain-ReAct-Agent/
│
├── agent/                          # Python Agent 核心
│   ├── react_agent.py              #   ReAct Agent 主逻辑（流式执行）
│   └── tools/
│       ├── agent_tools.py          #   13 个工具函数（通用 + 苍穹外卖）
│       └── middleware.py           #   中间件（工具监控/动态提示词切换）
│
├── rag/                            # RAG 检索增强
│   ├── vector_store.py             #   Chroma 向量库 · 文档加载 · MD5 去重
│   └── rag_service.py              #   RAG 检索 → LLM 总结服务
│
├── model/
│   └── factory.py                  # 模型工厂（ChatTongyi + DashScopeEmbedding）
│
├── config/                         # YAML 配置文件
│   ├── agent.yml                   #   Agent 行为与工具配置（scene 场景切换）
│   ├── chroma.yml                  #   向量库与检索参数
│   ├── prompts.yml                 #   提示词模板路径
│   └── rag.yml                     #   RAG 模型与参数
│
├── prompts/                        # 提示词模板
│   ├── main_prompt.txt             #   默认场景 System Prompt
│   ├── main_prompt_sky.txt         #   苍穹外卖场景 System Prompt
│   ├── rag_summarize.txt           #   RAG 总结 Prompt
│   └── rag_summarize_sky.txt       #   苍穹外卖 RAG 总结 Prompt
│
├── utils/                          # 工具函数
│   ├── config_handler.py           #   YAML 配置加载
│   ├── file_handler.py             #   文件解析 / Session 管理
│   └── ...
│
├── data/                           # 知识库文档
│   ├── chroma_db/                  #   Chroma 向量数据持久化
│   └── chroma_db_sky/              #   苍穹外卖场景向量库
│
├── sky-take-out/                   # ☕ Spring Boot 后端（苍穹外卖）
│   ├── sky-common/                 #   通用模块（工具类、异常处理）
│   ├── sky-pojo/                   #   实体 / DTO / VO
│   └── sky-server/                 #   业务逻辑 + API 端点
│       ├── controller/             #     admin/ + user/ 两层控制器
│       ├── service/                #     业务逻辑层
│       ├── mapper/                 #     MyBatis 数据访问层
│       └── interceptor/            #     JWT 认证拦截器
│
├── sky-admin-front/                # 🖥️ Vue 前端（苍穹外卖管理后台）
│   ├── src/
│   │   ├── api/                    #    API 请求封装
│   │   ├── views/                  #    页面组件
│   │   │   └── ai-chat/           #     AI 智能客服对话页面
│   │   ├── store/                  #    Vuex 状态管理
│   │   └── utils/                  #    工具函数
│   ├── vue.config.js               #    代理配置（转发到 :8080）
│   └── package.json
│
├── api_service.py                  # FastAPI 服务入口（将 Agent 包装为 HTTP API）
├── app.py                          # Streamlit 应用入口（独立对话界面）
├── requirements.txt                # Python 依赖
├── STARTUP.md                      # 🚀 完整启动指南
└── README.md                       # 本文件
```

---

## ✨ 核心特性

### 🤖 AI Agent

| 特性 | 说明 |
|---|---|
| **ReAct 推理范式** | Thought → Action → Observation 循环，自主推理并选择工具 |
| **RAG 检索增强** | Chroma 向量库 + DashScope Embedding，支持知识库问答 |
| **多工具调用** | 13 个工具：天气查询、用户数据、菜品查询、订单查询、报表生成等 |
| **双场景切换** | 通过 `scene` 配置切换「通用问答」与「苍穹外卖」两套提示词和知识库 |
| **动态提示词** | Middleware 根据上下文自动切换 System Prompt |
| **流式输出** | SSE 协议逐 token 推送，前端实时显示 |

### ☕ 苍穹外卖后端 (Spring Boot)

| 特性 | 说明 |
|---|---|
| **双端 API** | admin（管理端）+ user（用户端）两层 REST 接口 |
| **JWT 认证** | 管理员 + 普通用户两套 Token 体系 |
| **Redis 缓存** | 店铺状态、套餐缓存 |
| **阿里云 OSS** | 文件上传存储 |
| **Swagger 文档** | Knife4j 接口文档（dev 环境可用） |
| **AI 客服桥接** | 转发前端请求到 Python Agent 服务 |

### 🖥️ 苍穹外卖前端 (Vue)

| 特性 | 说明 |
|---|---|
| **管理后台** | 员工管理、分类管理、菜品/套餐管理、订单管理 |
| **AI 聊天页面** | 智能客服对话界面，支持流式 SSE 展示 |
| **权限路由** | 登录 Token 鉴权 + 路由守卫 |
| **营业状态** | Redis 实时控制店铺营业/打烊 |
| **数据统计** | 营业额、销量 Top10 等经营报表 |

---

## 🚀 快速启动

> 完整详细启动步骤见 [STARTUP.md](./STARTUP.md)

### 依赖概览

| 依赖 | 版本要求 | 用途 |
|------|---------|------|
| Python | ≥ 3.10 | 运行 Agent 服务 |
| Java | ≥ 8 | 运行 Spring Boot 后端 |
| Maven | ≥ 3.6 | 构建后端 |
| Node.js | ≥ 16 | 运行前端 |
| MySQL | 8.0+ | 业务数据库 |
| Redis | 3.x+ | 缓存 |

### 启动顺序

```
① Redis → ② MySQL → ③ Python Agent (:8000) → ④ Spring Boot (:8080) → ⑤ Vue 前端 (:8888)
```

### 环境变量

```bash
# 必须：阿里云百炼 API Key（Agent 调用 LLM）
export DASHSCOPE_API_KEY="sk-xxxxx"   # Linux/macOS
set DASHSCOPE_API_KEY=sk-xxxxx        # Windows
```

### 一键启动

```bash
# 终端 1：Python Agent
.venv\Scripts\uvicorn api_service:app --host 0.0.0.0 --port 8000

# 终端 2：Spring Boot 后端（先编译打包，再启动 JAR）
mvn clean install -DskipTests -pl sky-server -am
java -jar sky-server/target/sky-server-1.0-SNAPSHOT.jar --spring.profiles.active=dev

# 终端 3：Vue 前端
set NODE_OPTIONS=--openssl-legacy-provider
npx vue-cli-service serve
```

### 验证

| 服务 | 地址 | 验证 |
|------|------|------|
| Agent | `http://localhost:8000/chat` | `POST {"query":"你好"}` → 返回回复 |
| 后端 | `http://localhost:8080/admin/employee/login` | 登录 → 获取 JWT Token |
| Swagger | `http://localhost:8080/doc.html` | 接口文档（dev 环境） |
| 前端 | `http://localhost:8888` | 管理后台登录 |

---

## ⚙️ 配置说明

### Python Agent 配置

| 文件 | 配置项 | 说明 |
|------|--------|------|
| `config/rag.yml` | `chat_model_name` | LLM 模型（如 qwen3.5-plus） |
| `config/chroma.yml` | `persist_directory` | 向量库存储路径 |
| `config/agent.yml` | `scene` | 场景切换：`robot` 或 `sky` |

### Spring Boot 配置

| 文件 | 配置项 | 说明 |
|------|--------|------|
| `application.yml` | JWT 密钥、Redis、MySQL 连接 | 基础配置 |
| `application-dev.yml` | 阿里云 OSS、微信小程序凭据 | 开发环境配置（勿提交到公开仓库） |

---

## 🧠 场景切换

Agent 支持双场景，通过 `config/agent.yml` 中的 `scene` 字段切换：

```yaml
scene: sky    # 苍穹外卖客服模式（默认）
# scene: robot  # 扫地机器人问答模式（原始）
```

不同场景加载不同的提示词模板、知识库和工具描述。

---

## 🛠️ 技术栈总览

| 层级 | 技术 |
|------|------|
| **LLM** | 通义千问（DashScope / ChatTongyi） |
| **Agent 框架** | LangChain + LangGraph |
| **向量数据库** | Chroma |
| **AI 服务框架** | FastAPI + Uvicorn |
| **后端框架** | Spring Boot 2.7.3 + MyBatis |
| **数据库** | MySQL 8.0 + Druid 连接池 |
| **缓存** | Redis 3.x |
| **前端框架** | Vue 2.6 + TypeScript |
| **UI 组件** | Element UI |
| **构建工具** | Maven + Vue CLI 3 |

---

## 📝 License

MIT © [smallstar231](https://github.com/smallstar231)
