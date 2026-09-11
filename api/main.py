"""
FastAPI 服务入口

提供 RESTful API 将 Agent 能力暴露为 HTTP 服务。
支持流式对话（SSE）、文档上传、会话管理。
"""

import json
import os
import shutil
import time
import uvicorn
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent.react_agent import ReactAgent
from agent.tools.registry import registry
from agent.tools.knowledge_tools import DocumentUploadTool
from database.session_manager import session_manager
from utils.logger_handler import logger
from utils.permission import permission_service

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    身份：优先取请求体 user_id；未知用户归一到默认用户；无 chat 权限返回 403。
    用法：
        curl -N -X POST http://localhost:8000/api/chat \\
            -H "Content-Type: application/json" \\
            -d '{"query": "小户型适合哪些扫地机器人？"}'
    """
    requester = permission_service.resolve_user(request.user_id)
    if not permission_service.has_permission(requester, "chat"):
        raise HTTPException(status_code=403, detail="当前用户无对话权限")

    session_id = request.session_id

    async def event_stream():
        """
        异步生成 SSE 事件流

        事件结构由 ReactAgent 产出（见其事件协议注释）：
          {"type":"token","content":str,"turn":N}  模型文本增量（第 N 轮）
          {"type":"tool","turn":N,"name":str}      第 N 轮调用了工具 → 前端把该轮归入"思考"
          {"type":"done"}                          流结束
        """
        try:
            async for event in _async_stream(
                react_agent.execute_stream(request.query, session_id, requester)
            ):
                payload = event if isinstance(event, dict) else {"type": "token", "content": str(event)}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

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


@app.get("/api/users")
async def list_users():
    """
    用户列表（含角色与权限），供前端切换用户

    注意：演示级实现，identity 由前端声明；生产应接 JWT/SSO。
    """
    users = permission_service.list_users()
    for u in users:
        u["session_count"] = len(session_manager.list_sessions(u["user_id"]))
    return {
        "users": users,
        "total": len(users),
        "default_user": permission_service.default_user,
    }


@app.post("/api/upload", response_model=UploadResponse)
async def upload_document(request: UploadRequest, x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    """
    上传文档到知识库（按服务端绝对路径）

    权限：需要 upload 权限（admin 角色）。
    """
    requester = permission_service.resolve_user(x_user_id)
    if not permission_service.has_permission(requester, "upload"):
        logger.warning(f"[API] 用户 {requester} 尝试上传文档但无 upload 权限")
        raise HTTPException(status_code=403, detail="当前用户无上传权限（需要管理员）")

    try:
        # 从注册表获取工具（按用户真实角色做权限判定）
        tool = registry.get_tool("document_upload", user_role=permission_service.get_role(requester))
        if tool is None:
            raise HTTPException(status_code=403, detail="当前角色无权使用文档上传工具")

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


@app.post("/api/upload/file", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...), x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    """
    文件上传接口（multipart/form-data）

    前端以表单上传文件，服务端保存后自动解析入库。
    支持格式与知识库配置一致：txt / pdf / docx / csv / jpg / jpeg / png
    权限：需要 upload 权限（admin 角色）。
    """
    requester = permission_service.resolve_user(x_user_id)
    if not permission_service.has_permission(requester, "upload"):
        logger.warning(f"[API] 用户 {requester} 尝试上传文件但无 upload 权限")
        raise HTTPException(status_code=403, detail="当前用户无上传权限（需要管理员）")

    tool = registry.get_tool("document_upload", user_role=permission_service.get_role(requester))
    if tool is None:
        raise HTTPException(status_code=403, detail="当前角色无权使用文档上传工具")

    filename = os.path.basename(file.filename or "upload.bin")

    # 保存到 data/uploads 目录
    upload_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uploads"
    )
    os.makedirs(upload_dir, exist_ok=True)
    dest = os.path.join(upload_dir, filename)

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = tool.execute(file_path=dest)
        if result.success:
            data = result.data or {}
            return UploadResponse(
                success=True,
                filename=data.get("filename"),
                chunks=data.get("chunks"),
                characters=data.get("characters"),
            )
        return UploadResponse(success=False, error=result.error)
    except Exception as e:
        logger.error(f"[API] 文件上传处理失败: {e}", exc_info=True)
        return UploadResponse(success=False, error=str(e))


@app.get("/api/sessions")
async def list_sessions(
    user_id: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """
    获取会话列表（带权限约束）

    - admin：可查询全部用户会话，也可用 user_id 过滤
    - 普通用户：只能查询自己的会话，越权查询返回 403
    """
    requester = permission_service.resolve_user(x_user_id)

    if not permission_service.is_admin(requester):
        if user_id and user_id != requester:
            raise HTTPException(status_code=403, detail="无权查看其他用户的会话")
        user_id = requester

    sessions = [
        SessionInfo(
            session_id=item["session_id"],
            user_id=item["user_id"],
            message_count=item["message_count"],
            created_at=item["created_at"],
            last_active=item["last_active"],
        )
        for item in session_manager.list_sessions(user_id)
    ]
    return {"sessions": sessions, "total": len(sessions)}


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """
    获取指定会话的历史消息（前端切换会话时恢复上下文）

    权限：admin 可查任意会话；普通用户只能查自己的会话，越权返回 403。
    """
    requester = permission_service.resolve_user(x_user_id)
    if not permission_service.is_admin(requester):
        owner = session_manager.get_owner(session_id)
        if owner is not None and owner != requester:
            logger.warning(f"[API] 用户 {requester} 尝试读取 {owner} 的会话 {session_id}")
            raise HTTPException(status_code=403, detail="无权查看该会话")

    messages = session_manager.get_messages(session_id)
    return {
        "session_id": session_id,
        "messages": messages,
        "total": len(messages),
    }


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

# ────────────── 启动入口 ──────────────

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        # 注意：不要开 reload=True。
        # uvicorn 的 --reload 会监听整个项目目录，而应用运行时持续写
        # data/（会话库、记忆文件、日志、向量库），会造成「写入→重载→再写入」
        # 的重启风暴。开发期需要热重载时改用：
        #   uvicorn api.main:app --reload --reload-dir api --reload-dir agent --reload-dir rag
        # 只监听代码目录，排除数据目录。
        reload=False,
    )
