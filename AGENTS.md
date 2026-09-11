# AGENTS.md — 企业级 AI Agent 知识库问答系统

> 本文件是 AI Coding 助手与协作者的「结构化上下文入口」。
> 改动架构、新增模块前先读本文件；设计决策变更时同步更新本文件。

## 项目是什么

扫地/扫拖机器人领域的智能客服系统：RAG 混合检索 + ReAct Agent 工具调用 + FastAPI 服务化 + Docker 部署。

## 六层架构

| 层 | 目录 | 职责 |
|---|---|---|
| 接入层 | `api/` | FastAPI 路由、SSE 流式、Pydantic 校验 |
| 编排层 | `agent/` | LangGraph ReAct Agent、中间件 |
| 工具层 | `agent/tools/` | 工具注册表（角色权限）+ 各工具实现 |
| 知识层 | `rag/` | BM25+向量混合检索、RRF 融合、文档解析入库 |
| 记忆层 | `database/` | 短期窗口（两道闸）+ **Compaction 压缩** + 长期记忆（JSON 持久化） |
| 可观测层 | `infrastructure/` | Trace 链路 + Metrics（P50/P95/Token） |

## 关键约定（违者 CI/评审阻断）

1. **配置外置**：所有参数走 `config/*.yml`，密钥只从环境变量读（`DASHSCOPE_API_KEY`），严禁硬编码进代码/镜像。
2. **新增工具**：继承 `BaseTool` 或用 `@tool` 装饰器，并在 `agent/tools/__init__.py` 的 `init_all_tools()` 注册；同时更新 `prompts/main_prompt.txt` 中的工具描述，**保持 Prompt 与注册表一致**。
3. **改检索必回归**：任何检索策略/切分/融合参数改动后，必须跑 `python evaluation/evaluate_retrieval.py --source local` 对比 Hit Rate。
4. **改代码必测试**：核心模块改动配套单测（Mock 隔离 LLM/向量库等外部依赖），`pytest tests/ -q` 全绿才提交。

## 常用命令

```bash
# 后端（先设 DASHSCOPE_API_KEY）
python -m api.main

# 前端
cd frontend && npm install && npm run dev   # http://localhost:5173

# 单元测试（无 key 离线可跑）
pytest tests/ -q

# 知识库入库
python -c "from rag.vector_store import VectorStoreService; VectorStoreService().load_document()"

# 离线检索评测（Hit Rate@5，无 key 可跑）
python evaluation/evaluate_retrieval.py --source local

# RAGAS 生成质量评测（需真实 key + pip install -r requirements-eval.txt）
python evaluation/evaluate_ragas.py --sample 10

# Docker（一键起「后端 API + 前端 nginx」两个容器）
docker compose up -d --build
#   前端（nginx 托管 SPA + /api 反代）→ http://localhost:8090
#   后端 Swagger（可直接调接口）      → http://localhost:8000/docs
#   密钥放 .env（模板见 .env.example）

# 依赖审计（新增依赖前先跑：查出「代码 import 了、但 requirements 没写」的包）
python evaluation/check_requirements.py

# 容器化后验证 SSE 没被代理缓冲（经 nginx 打流式接口）
python evaluation/verify_nginx_sse.py
```

## 记忆设计（四层 + 多用户隔离）

- **窗口层**：`SessionManager` 滑动窗口（`max_rounds` 轮）+ 字符级裁剪（`max_history_chars`）——决定什么能进模型。
- **压缩层（Compaction）**：被挤出窗口的历史**不再硬丢**，交给 `database/compaction.py` 做**增量摘要**（`summary` + `compacted_count` 游标，只压新掉出去的部分并合并上一版摘要）；LLM 失败时降级为规则生成的「结构化笔记」；摘要以 system 消息插在窗口之前。存储层 `max_stored_rounds=100` 保证「有得压」。
- **长期记忆**：`LongTermMemory` 跨会话持久化用户偏好事实（JSON），启发式抽取，回答时注入上下文。
- **持久化层**：SQLite（`sessions` 表），服务重启可恢复。
- **多用户隔离**：`sessions` 表带 `user_id` 列（含旧库 ALTER 迁移 + `(user_id, last_active)` 索引）；`/api/sessions?user_id=` 按用户过滤；长期记忆按 `user_id` 分桶；前端侧栏可切换用户。
  - 现状是**轻量标识隔离**（无鉴权）；生产环境需接 JWT/SSO 并把 user_id 与身份体系绑定。

## 前端（React 19 + Vite）

- 结构：侧栏（用户切换 / 会话列表）+ 主区（消息流 / Markdown 渲染 / 输入区）。
- 关键实现：`fetch` + `ReadableStream` 解析 SSE 逐字渲染；会话历史走 `GET /api/sessions/{id}/messages`；消息级操作（复制 / 重新生成）。
- 设计规范见 `frontend/src/App.css` 顶部注释（规避通用 AI 默认样式：衬线标题 + 暖色调 + 背景层次 + 固定尺寸卡片 + 微交互）。

## 多用户与权限

- **配置**：`config/users.yml`（用户、角色、权限映射）；实现：`utils/permission.py`（单例服务）。
- **角色**：`admin`（对话 + 上传文档 + 查看全部会话）/ `user`（仅对话 + 查看自己的会话）。
- **接口约束**：请求头 `X-User-Id` 作为身份；越权查询他人会话、非管理员上传 → **403**；`/api/users` 返回用户与角色供前端切换。
- **前端**：侧栏用户列表可切换（会话与记忆随之隔离）；非管理员上传按钮为锁定态。
- ⚠️ **现状是演示级身份**（user_id 由前端声明）。生产必须接 JWT/SSO 签名校验 + 审计日志。

## 测试与评测文档

- **`TESTING.md`**：测试分层（单测 / 检索评测 / 生成评测 / 权限回归）、指标定义、复现命令、已知局限。
- **`evaluation/评测报告-HitRate@5.md`**：由 `evaluate_retrieval.py --report` 自动生成，含三模式对比与逐题未命中明细（实测：语义基线 96% → 混合 98%）。

## 已知权衡（演进方向）

- BM25 索引常驻内存：小知识库零依赖够用；文档量级上升后迁移 Elasticsearch/OpenSearch。
- 会话存储为单机 SQLite + 内存缓存：多实例部署时需换集中式存储（Redis/Postgres）。
- 工具参数校验在工具内实现：规模化后可上 Pydantic 结构化工具声明。

## 常见问题（排障笔记）

1. **前端改了代码但界面没变化 / 发了消息没反应**
   现象：磁盘上的 `App.tsx` 已经是新版，但浏览器行为还是旧的。
   原因：Vite dev server 的**模块转换缓存没失效**（短时间内连续多次写同一文件时，它的 mtime 缓存可能漏掉最后一次）。
   排查：直接请求 dev server 的模块源码看是不是新版，例如
   `curl http://localhost:5173/src/App.tsx | findstr thinkbox`
   解决：**重启 dev server**，或用 `npm run dev -- --force` 强制清缓存；浏览器再 Ctrl+F5 硬刷新。

2. **流式看起来是「整块蹦出来」而不是逐字**
   排查：`python evaluation/stream_check.py`（打印每个 chunk 的到达时刻与间隔）。
   若 chunk 数 ≤ 6、间隔数秒 → 检查两处：① `stream_mode` 是否包含 `"messages"`；② 模型是否 `streaming=True`。

3. **思考过程混进了答案**
   排查：确认 SSE 事件里有 `{"type":"tool","turn":N}`；前端据此把第 N 轮归入折叠区。

4. **多 worker 部署后上下文丢失**
   原因：会话与记忆是「进程内内存 + SQLite」，多进程各存各的。
   解决：迁 Redis 集中存储（见「已知权衡」）。

5. **AI 回答的文字被居中显示（或整体样式被莫名污染）**
   现象：气泡本身在左侧，但**气泡里的文字是居中的**；表头/标题等样式也和设计稿不一致。
   原因：`src/index.css` **保留了 Vite 官方模板的样式**，其中
   `#root { width: 1126px; text-align: center; }` 会被所有后代**继承**——`.turn-bubble` / `.answer` 都没显式声明 `text-align`，于是回答正文被居中。同一文件里的 `h1 { font-size: 56px }`、`code { padding: 4px 8px }`、紫色 `--accent` 也在与 `App.css` 抢样式（模板的 `prefers-color-scheme: dark` 块还会覆盖 App.css 的 `--text` 变量）。
   排查手法：`text-align` 是**可继承属性**，怀疑它时要在 DevTools 里看 **Computed → text-align** 的继承链，而不是只看自己的选择器；也可以用
   `Select-String -Path src\*.css -Pattern "text-align"` 全局扫一遍。
   解决：`index.css` 只保留极简 reset（`box-sizing` / `margin` / `#root{min-height}`），**所有布局与主题一律写 `App.css`**；同时给 `.turn-body` 显式加 `text-align: left` 兜底，防止再被全局样式污染。
   教训：**脚手架模板的全局样式是隐性 bug 源**——`<div id="root">` 上的 `text-align` 一行就能让整个应用的文字对齐出错，而且它不在你写的 CSS 文件里，很容易查半天。

6. **容器起来了但应用崩溃：`ImportError` / `ModuleNotFoundError`**
   现象：本地 `python -m api.main` 一切正常，`docker compose up -d --build` 后容器反复重启，日志报缺包（实例：`Could not import dashscope`、`Form data requires "python-multipart"`）。
   原因：**`requirements.txt` 漏写依赖，而本地环境有历史包袱**。三类最容易漏：
   ① 可选依赖（`dashscope` 是 `langchain-community` 的可选件，只在真正初始化 ChatTongyi 时才校验）；
   ② **不被代码直接 import 的包**（`python-multipart` 由 FastAPI 内部使用，import 扫描查不出来）；
   ③ 一直靠别的包间接带进来的（`PyYAML`）。
   解决：跑 `python evaluation/check_requirements.py`——AST 扫全项目 import → 反查发行版 → 与 requirements 比对，一次列出所有缺失项。**新增依赖后请先跑它。**

7. **`docker compose ps` 里容器一直是 `unhealthy`**
   现象：服务其实能正常访问，但状态显示 unhealthy（并连带 `depends_on: service_healthy` 的下游服务起不来）。
   原因：健康检查命令在镜像里不存在。经典案例是 `test: ["CMD", "curl", "-f", ...]`——**运行镜像基于 `python:3.12-slim`，根本没装 curl**，执行直接报 `exec: "curl": executable file not found`。
   解决：用镜像里已有的东西探活（我们改成 `python -c "import urllib.request..."`）；另外给 `start_period`（本地设了 60s），因为启动要加载向量库、构建 BM25 索引。
   排查：`docker inspect <容器> --format '{{json .State.Health}}'` 看最近几次探测的输出，一眼就能看出是命令不存在还是接口没起来。