# 🤖 企业级 AI Agent 知识库问答系统

![Python](https://img.shields.io/badge/Python-3.12-blue)
![LangChain](https://img.shields.io/badge/LangChain-Latest-green)
![LangGraph](https://img.shields.io/badge/LangGraph-Latest-orange)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-teal)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

> 基于 LangChain + LangGraph + 通义千问 构建的智能知识库问答系统。
> 支持多轮对话、混合检索、FastAPI 服务化与 Docker 容器化部署。

---

## 🧭 架构图

```mermaid
graph TB
    subgraph 用户层
        U1["Streamlit UI"]
        U2["Swagger /docs"]
        U3["curl / HTTP"]
    end
    subgraph API层
        A1["POST /api/chat SSE流式"]
        A2["POST /api/upload"]
        A3["GET /api/sessions"]
    end
    subgraph Agent编排层
        B1["LangGraph ReAct 状态机"]
        B2["ToolRegistry 工具注册表"]
        B3["SessionManager 会话管理"]
    end
    subgraph 知识处理层
        C1["HybridSearch 混合检索"]
        C2["ChromaDB 向量库"]
        C3["DocumentLoader 文档解析"]
    end
    U1 --> A1
    U2 --> A1
    U3 --> A1
    A1 --> B1
    A2 --> B2
    A3 --> B3
    B1 --> C1
    B1 --> B3
    C1 --> C2
    C1 --> C3
```

---

## ✨ 核心功能

- **RAG 混合检索** — BM25 关键词 + 语义向量 + RRF 融合排序，兼顾术语精确匹配与语义理解
- **多轮对话** — Session 会话管理，SQLite 持久化，服务重启后对话不丢失
- **Agent 智能编排** — LangGraph ReAct 循环（思考→工具调用→观察→回答）
- **文档自动导入** — 支持 txt / pdf / docx / csv / 图片，自动分块向量化
- **API 服务化** — FastAPI + SSE 流式输出，Swagger 自动文档
- **Docker 部署** — 多阶段构建，docker-compose 一键启动

---

## ⚡ 快速启动

### 1. 环境准备

- Python 3.12+
- 阿里云通义千问 API 密钥（[获取地址](https://help.aliyun.com/zh/model-studio/developer-reference/get-api-key)）

### 2. 安装

```bash
git clone https://github.com/refreedome/ai-agent-knowledge-system.git
cd ai-agent-knowledge-system

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置密钥

```bash
# Windows PowerShell
$env:DASHSCOPE_API_KEY="sk-你的密钥"

# macOS / Linux
export DASHSCOPE_API_KEY="sk-你的密钥"
```

### 4. 加载知识库

```bash
python -c "from rag.vector_store import VectorStoreService; vs = VectorStoreService(); vs.load_document()"
```

### 5. 运行

```bash
# 方式一：终端交互
python agent/react_agent.py

# 方式二：FastAPI 服务
python -m api.main
# 浏览器打开 http://localhost:8000/docs

# 方式三：Docker
docker compose up --build -d
```

### 6. 前端界面（React + Vite）

```bash
cd frontend
npm install
npm run dev
# 浏览器打开 http://localhost:5173
```

> 开发模式下 Vite 已把 `/api` 代理到 `http://127.0.0.1:8000`（见 `frontend/vite.config.ts`），
> 需先启动 FastAPI 后端（方式二）。前端支持流式对话、会话管理、文档上传。
> 另外 `app.py` 提供了一个 Streamlit 原型界面：`streamlit run app.py`。

---

## 📡 API 文档

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| `GET` | `/api/health` | 健康检查 | - |
| `GET` | `/api/users` | 用户列表（含角色与权限，供切换用户） | - |
| `POST` | `/api/chat` | 流式对话（SSE） | `{"query": "...", "session_id": "可选", "user_id": "可选"}` |
| `POST` | `/api/upload` | 上传文档（服务端路径，需 admin） | `{"file_path": "绝对路径"}` |
| `POST` | `/api/upload/file` | 上传文档（multipart 表单，需 admin） | `file` 字段（txt/pdf/docx/csv/图片） |
| `GET` | `/api/sessions` | 会话列表（按用户隔离，admin 可查全部） | - |
| `GET` | `/api/sessions/{id}/messages` | 会话历史消息 | - |
| `DELETE` | `/api/sessions/{id}` | 清理会话 | - |
| `GET` | `/api/metrics` | 性能指标（P50/P95、Token、成功率） | - |

> 身份通过请求头 `X-User-Id` 传入（见 `config/users.yml` 的用户与角色配置）；
> 普通用户越权查询他人会话或上传文档会返回 403。

### 测试与评测

单元测试、检索评测（Hit Rate@5）、生成质量评测（RAGAS）与权限回归的说明见 **[TESTING.md](TESTING.md)**；
最新评测报告见 `evaluation/评测报告-HitRate@5.md`。

### 测试示例

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "小户型适合哪些扫地机器人？"}'
```

---

## 📂 项目结构

```
├── agent/               # Agent 编排层
│   ├── tools/           #   工具集（知识检索/文档上传）
│   ├── middleware.py    #   全流程日志中间件
│   └── react_agent.py   #   ReAct Agent 主入口
├── api/                 # API 服务层
│   ├── main.py          #   FastAPI 路由 + SSE
│   └── schemas.py       #   Pydantic 数据模型
├── rag/                 # 知识处理层
│   ├── hybrid_search.py #   BM25 + 语义 + RRF
│   ├── vector_store.py  #   ChromaDB 封装
│   └── rag_service.py   #   总结服务
├── database/            # 持久化层
│   └── session_manager.py  # 会话管理（SQLite）
├── model/               # 模型层
│   └── factory.py       #   通义千问封装
├── config/              # 配置层（YAML）
├── utils/               # 工具层
├── document/            # 文档处理器
├── Dockerfile           # 容器镜像
├── docker-compose.yml   # 容器编排
└── requirements.txt     # Python 依赖
```

---

## 🛠️ 技术栈

| 分类 | 技术 | 用途 |
|------|------|------|
| AI 框架 | LangChain + LangGraph | Agent 编排、ReAct 循环 |
| 大语言模型 | 通义千问 qwen-plus | 对话生成、工具调用 |
| 向量数据库 | ChromaDB | 知识库向量存储 |
| 混合检索 | BM25Okapi + jieba + RRF | 关键词+语义融合检索 |
| Web 框架 | FastAPI + Uvicorn | HTTP 服务、SSE 流式 |
| 文档解析 | pypdf / python-docx / pytesseract | 多格式文档导入 |
| 数据持久化 | SQLite | 会话历史存储 |
| 容器化 | Docker + docker-compose | 构建部署 |

---




## 📄 许可证

MIT License © 2025
