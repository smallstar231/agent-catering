# 🚀 项目启动指南

> LangChain ReAct Agent + 苍穹外卖（SkyTakeOut）Spring Boot + Vue 前端
>
> 三端 Monorepo 一键启动参考

---

## 📋 启动前准备

### 依赖检查

| 依赖 | 用途 | 检查命令 |
|------|------|---------|
| **Java 8+** | 运行 Spring Boot 后端 | `java -version` |
| **Maven 3.6+** | 构建 Spring Boot | `mvn --version` |
| **Node.js 22+** | 运行 Vue 前端 | `node -v` |
| **Yarn** | 安装前端依赖 | `yarn --version` |
| **Python 3.12** | 运行 Agent 服务 | `python --version` |
| **MySQL 8.0+** | 后端数据库 | `netstat -an \| grep 3306` |
| **Redis 3.x+** | 后端缓存 | `netstat -an \| grep 6379` |

### 环境变量

确保已设置阿里云百炼 API Key（Agent 调用 LLM 所需）：

```bash
# Windows CMD
set DASHSCOPE_API_KEY=sk-xxxxx

# Windows PowerShell
$env:DASHSCOPE_API_KEY="sk-xxxxx"

# 或写入 .env 文件（项目根目录）
echo DASHSCOPE_API_KEY=sk-xxxxx > .env
```

> 如未设置，Agent 服务会启动失败。

---

## 🏁 启动顺序

> **重要**：必须按顺序启动，因为后端依赖数据库和 Redis，前端和后端依赖 Agent。

```
① Redis → ② MySQL → ③ Python Agent → ④ Spring Boot → ⑤ Vue 前端
```

---

### 第 0 步：确认系统服务

**Redis**

```bash
# 检查 Redis 是否运行
netstat -an | grep 6379

# 若未运行，启动 Redis 服务
net start Redis

# 或直接启动 Redis 可执行文件
"D:\Redis\Redis-x64-3.2.100\redis-server.exe" --port 6379
```

**MySQL**

```bash
# 检查 MySQL 是否运行
netstat -an | grep 3306
```

> MySQL 应在 3306 端口监听。如果未启动，请在 Windows 服务中启动 MySQL 或使用 XAMPP/WAMP 等工具。

---

### 第 1 步：启动 Python Agent 服务

```bash
# 进入项目根目录
cd C:\Users\26716\PycharmProjects\LangChain-ReAct-Agent

# 使用虚拟环境启动（推荐）
.venv\Scripts\uvicorn api_service:app --host 0.0.0.0 --port 8000
```

Agent 将在 `http://localhost:8000` 监听。

**验证**：

```bash
# 请求 Agent 同步接口
curl -X POST http://localhost:8000/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"hello\"}"

# 应返回：{"response":"您好！..."}
```

> 作为参考：Agent 加载 Chroma 向量库需要约 5-10 秒。

---

### 第 2 步：启动 Spring Boot 后端

#### 方式 A：spring-boot:run（推荐，更快）

```bash
cd C:\Users\26716\PycharmProjects\LangChain-ReAct-Agent\sky-take-out

:: 使用 JDK 8
set JAVA_HOME=C:\Users\26716\.jdks\corretto-1.8.0_492

:: 编译并启动（不打包 JAR，省 ~30s）
C:\Users\26716\.m2\wrapper\dists\apache-maven-3.9.15-bin\4rlcemksed9vjmkvgss0jpc4po\apache-maven-3.9.15\bin\mvn.cmd spring-boot:run -pl sky-server -am
```

#### 方式 B：打包运行（传统方式）

```bash
cd C:\Users\26716\PycharmProjects\LangChain-ReAct-Agent\sky-take-out

:: 先编译打包
C:\Users\26716\.m2\wrapper\dists\apache-maven-3.9.15-bin\4rlcemksed9vjmkvgss0jpc4po\apache-maven-3.9.15\bin\mvn.cmd clean install -DskipTests

:: 再启动 JAR
C:\Users\26716\.jdks\corretto-1.8.0_492\bin\java.exe -jar sky-server\target\sky-server-1.0-SNAPSHOT.jar --spring.profiles.active=dev
```

Spring Boot 将在 `http://localhost:8080` 监听。

**验证**：

```bash
:: 登录接口（不需要 Token）
curl -X POST http://localhost:8080/admin/employee/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"123456\"}"

:: 应返回包含 token 的 JSON
```

---

### 第 3 步：启动 Vue 前端

```bash
cd C:\Users\26716\PycharmProjects\LangChain-ReAct-Agent\sky-admin-front

:: 安装依赖（仅首次或 package.json 变更时需要）
yarn install

:: 启动开发服务器（Node.js 22 需加 OpenSSL 兼容参数）
set NODE_OPTIONS=--openssl-legacy-provider
node ./node_modules/@vue/cli-service/bin/vue-cli-service.js serve
```

Vue 前端将在 `http://localhost:8888` 提供服务。

**验证**：浏览器打开 `http://localhost:8888`

> 首次编译约需 30-45 秒，之后修改代码会热更新。

---

## ✅ 启动后验证清单

| 服务 | 地址 | 验证方法 |
|------|------|---------|
| Agent | `http://localhost:8000` | `curl localhost:8000/chat -d "{\"query\":\"hi\"}"` |
| 后端 | `http://localhost:8080` | 登录接口返回 Token |
| Swagger 文档 | `http://localhost:8080/doc.html` | 浏览器打开（仅 dev 环境） |
| 前端 | `http://localhost:8888` | 浏览器打开，能登录进入后台 |
| 全链路 | 前端 → 后端 → Agent | 在后台使用 AI 客服功能 |

---

## 🛠 常见问题

### 1. Node.js 22 兼容问题

```
Error: error:0308010C:digital envelope routines::unsupported
```

**原因**：Node.js 17+ 默认 OpenSSL 3.0 不兼容 Webpack 4。

**解决**：启动前设置环境变量 `set NODE_OPTIONS=--openssl-legacy-provider`

### 2. Maven 构建失败

```
[ERROR] 不再支持源选项 5。请使用 7 或更高版本。
```

**原因**：JDK 版本与 Maven 编译器插件不匹配。

**解决**：确保 `JAVA_HOME` 指向 JDK 8+，并且 `pom.xml` 中 `<java.version>` 正确。

### 3. Agent 启动后返回 422

```
{"detail": "Input should be a valid list"}
```

**原因**：Java 后端发送的 `history` 字段为 `null`，Python Pydantic 校验不通过。

**解决**：已修复——`api_service.py` 中 ChatRequest 的 `history` 字段类型改为 `list | None = None`，并在函数中做 `req.history or []`。

### 4. Redis 连接失败

```
Redis连接失败：java.net.ConnectException: Connection refused
```

**解决**：确保 Redis 服务已启动（`netstat -an | grep 6379`）。

### 5. MySQL 连接失败

```
com.mysql.cj.jdbc.exceptions.CommunicationsException: Communications link failure
```

**解决**：确保 MySQL 服务已启动，且 `application-dev.yml` 中的连接信息正确。

### 6. Vue 前端代理 404

```
访问 /api/xxx 时返回 404
```

**原因**：`vue.config.js` 中 proxy 的 `pathRewrite` 将 `/api` 前缀去掉了，后端路由不带 `/api`。

**解决**：不需要解决——这是设计如此，检查后端路由是否匹配即可。

---

## 📌 一键启动（Windows Bat）

保存为 `start-all.bat` 到项目根目录：

```bat
@echo off
chcp 65001 >nul
echo ========================================
echo  LangChain ReAct Agent - 一键启动
echo ========================================

set PROJECT_DIR=C:\Users\26716\PycharmProjects\LangChain-ReAct-Agent
set JAVA_HOME=C:\Users\26716\.jdks\corretto-1.8.0_492
set M2_HOME=C:\Users\26716\.m2\wrapper\dists\apache-maven-3.9.15-bin\4rlcemksed9vjmkvgss0jpc4po\apache-maven-3.9.15
set NODE_OPTIONS=--openssl-legacy-provider

:: 1. 启动 Agent
echo [1/3] 启动 Python Agent...
start "Agent" cmd /c "%PROJECT_DIR%\.venv\Scripts\uvicorn api_service:app --host 0.0.0.0 --port 8000"
timeout /t 8 /nobreak >nul

:: 2. 启动 Spring Boot
echo [2/3] 启动 Spring Boot 后端...
start "SpringBoot" cmd /c "cd /d %PROJECT_DIR%\sky-take-out && %M2_HOME%\bin\mvn.cmd spring-boot:run -pl sky-server -am"
timeout /t 30 /nobreak >nul

:: 3. 启动 Vue 前端
echo [3/3] 启动 Vue 前端...
start "VueFrontend" cmd /c "cd /d %PROJECT_DIR%\sky-admin-front && node .\node_modules\@vue\cli-service\bin\vue-cli-service.js serve"

echo ========================================
echo  ✅ 所有服务启动命令已执行
echo  Agent:     http://localhost:8000
echo  后端:      http://localhost:8080
echo  前端:      http://localhost:8888
echo ========================================
pause
```

---

## 🔧 开发热重启

### Java 后端修改代码后

推荐装 `spring-boot-devtools` 实现自动热重启，修改 Java 代码后约 3-5 秒自动重启。

### Vue 前端修改代码后

Vue CLI 默认支持热模块替换（HMR），修改后页面自动刷新。

### Python Agent 修改代码后

需要手动重启 uvicorn 进程（Ctrl+C 停止，重新运行 `uvicorn` 命令）。

---

> **最后更新**：2026-06-11
>
> **项目地址**：`C:\Users\26716\PycharmProjects\LangChain-ReAct-Agent`
