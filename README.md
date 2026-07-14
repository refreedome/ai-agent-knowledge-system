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

---

## 📡 API 文档

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| `GET` | `/api/health` | 健康检查 | - |
| `POST` | `/api/chat` | 流式对话（SSE） | `{"query": "...", "session_id": "可选"}` |
| `POST` | `/api/upload` | 上传文档 | `{"file_path": "绝对路径"}` |
| `GET` | `/api/sessions` | 会话列表 | - |
| `DELETE` | `/api/sessions/{id}` | 清理会话 | - |

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

## 📊 简历描述（STAR 法则）

**项目名称**：企业级 AI Agent 知识库问答系统
**技术栈**：LangChain / LangGraph / 通义千问 / ChromaDB / FastAPI / Docker

| 维度 | 内容 |
|------|------|
| **Situation 背景** | 传统客服依赖人工查询知识库，知识更新后需手动同步，效率低、响应慢 |
| **Task 任务** | 构建基于 RAG 的企业级智能问答系统，实现文档自动导入 → 向量化 → 多轮对话 → 精准回答的完整链路 |
| **Action 行动** | ① 基于 LangGraph ReAct 架构设计 Agent 编排状态机，封装知识检索、文档上传等工具，实现工具注册表统一管理；② 实现 BM25 关键词 + 语义向量 + RRF 融合的混合检索，解决专业术语语义偏移问题；③ 通过 FastAPI + SSE 对外提供流式对话 API，docker-compose 容器化部署 |
| **Result 结果** | ✅ 多格式文档导入 → 自动分块 → 向量化入库全流程；✅ Agent 多轮对话自动决策调工具；✅ 混合检索准确匹配产品术语与用户意图；✅ 服务重启对话历史不丢失 |

---

## 📄 许可证

MIT License © 2025
