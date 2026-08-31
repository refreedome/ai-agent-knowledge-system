"""
FastAPI 服务入口

提供 RESTful API 将 Agent 能力暴露为 HTTP 服务。
支持流式对话（SSE）、文档上传、会话管理。
"""

import json
import os
import time
import uvicorn
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent.react_agent import ReactAgent
from agent.tools.registry import registry
from agent.tools.knowledge_tools import DocumentUploadTool
from database.session_manager import session_manager
from utils.qa_cache import qa_cache
from utils.logger_handler import logger

from api.schemas import (
    ChatRequest, UploadRequest, UploadResponse,
    SessionInfo, HealthResponse, MetricsResponse,
)


# ────────────── 全局单例 ──────────────

# 应用启动时初始化，全局复用
react_agent: Optional[ReactAgent] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化 Agent"""
    global react_agent
    logger.info("[API] 正在初始化 ReactAgent...")
    react_agent = ReactAgent()
    logger.info("[API] ReactAgent 初始化完成")
    yield
    # 关闭时清理
    logger.info("[API] 服务关闭")


# ────────────── FastAPI 应用 ──────────────

app = FastAPI(
    title="企业级 AI Agent 知识库问答系统",
    description="基于 LangChain/LangGraph + 通义千问的智能客服 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS —— 允许前端（Streamlit / Vue / React）跨域调用
# 默认仅允许本机；生产环境用 ALLOWED_ORIGINS 环境变量收紧为真实域名/IP（见 .env.example）
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8501,http://127.0.0.1:8501,http://localhost:8000,http://127.0.0.1:8000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ────────────── 路由 ──────────────

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="ok",
        session_count=session_manager.session_count,
    )


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    对话接口（SSE 流式响应）

    以 Server-Sent Events 格式逐字返回 LLM 输出。
    用法：
        curl -N -X POST http://localhost:8000/api/chat \\
            -H "Content-Type: application/json" \\
            -d '{"query": "小户型适合哪些扫地机器人？"}'
    """
    session_id = request.session_id

    async def event_stream():
        """异步生成 SSE 事件流"""
        try:
            async for chunk in _async_stream(react_agent.execute_stream(request.query, session_id)):
                # SSE 格式：data: <content>\n\n
                yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"

            # 流结束标记
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            logger.error(f"[API] 流式输出异常: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁止 Nginx 缓冲
        }
    )


@app.post("/api/upload", response_model=UploadResponse)
async def upload_document(request: UploadRequest):
    """
    上传文档到知识库

    支持格式: txt / pdf / docx / csv / jpg / png
    自动完成：格式校验 → 解析 → 分块 → 向量化入库
    """
    try:
        # 从注册表获取工具（单例，不用每次都 new）
        tool = registry.get_tool("document_upload")
        if tool is None:
            raise HTTPException(status_code=500, detail="文档上传工具未注册")

        result = tool.execute(file_path=request.file_path)

        if result.success:
            data = result.data
            return UploadResponse(
                success=True,
                filename=data.get("filename"),
                chunks=data.get("chunks"),
                characters=data.get("characters"),
            )
        else:
            return UploadResponse(success=False, error=result.error)

    except Exception as e:
        logger.error(f"[API] 文档上传失败: {e}", exc_info=True)
        return UploadResponse(success=False, error=str(e))


@app.get("/api/sessions")
async def list_sessions():
    """
    获取所有活跃会话列表
    """
    # SessionManager 内部是 dict，没有 list API，
    # 通过直接访问内部结构获取（后续可优化）
    sessions = []
    for sid, session_data in session_manager._sessions.items():
        sessions.append(SessionInfo(
            session_id=sid,
            message_count=len(session_data.messages) if hasattr(session_data, 'messages') else 0,
            created_at=str(session_data.created_at) if hasattr(session_data, 'created_at') else "",
            last_active=str(session_data.last_active) if hasattr(session_data, 'last_active') else "",
        ))
    return {"sessions": sessions, "total": len(sessions)}


@app.delete("/api/sessions/{session_id}")
async def clear_session(session_id: str):
    """清理指定会话"""
    session_manager.clear_session(session_id)
    return {"success": True, "session_id": session_id}


# ────────────── 辅助函数 ──────────────

_SENTINEL = object()  # 哨兵值，标记生成器结束


async def _async_stream(sync_generator):
    """
    将同步生成器包装为异步迭代器

    run_in_executor + sentinel 模式，避免 StopIteration
    在异步上下文中传播导致 RuntimeError
    """
    import asyncio
    loop = asyncio.get_event_loop()

    def _next():
        """取下一个元素，结束返回哨兵"""
        try:
            return next(sync_generator)
        except StopIteration:
            return _SENTINEL

    while True:
        chunk = await loop.run_in_executor(None, _next)
        if chunk is _SENTINEL:
            break
        yield chunk


# ────────────── 性能指标 ──────────────

from infrastructure.metrics import metrics_collector


@app.get("/api/metrics", response_model=MetricsResponse)
async def get_metrics():
    """
    获取性能指标统计

    返回 LLM 调用、工具调用等端点的：
    - 请求总数、平均耗时、P50/P95 耗时
    - Token 消耗总量、平均每次 Token
    - 成功率
    """
    stats = metrics_collector.get_all_stats(window_seconds=3600)
    return MetricsResponse(
        stats=stats,
        total_requests=sum(s.get("total_requests", 0) for s in stats.values()),
    )

@app.get("/api/cache")
async def get_cache_stats():
    """
    热点问题缓存统计

    返回缓存命中/未命中次数、命中率、当前缓存大小
    """
    return qa_cache.stats()


# ────────────── 启动入口 ──────────────

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
