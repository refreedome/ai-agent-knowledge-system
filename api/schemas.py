"""
API 数据模型 (Pydantic)
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class ChatRequest(BaseModel):
    """聊天请求"""
    query: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    session_id: Optional[str] = Field(None, description="会话ID，不传则自动创建")


class ChatResponse(BaseModel):
    """聊天响应（非流式）"""
    answer: str
    session_id: str
    sources: Optional[List[dict]] = None


class UploadRequest(BaseModel):
    """文档上传请求"""
    file_path: str = Field(..., min_length=1, description="文件绝对路径")


class UploadResponse(BaseModel):
    """文档上传响应"""
    success: bool
    filename: Optional[str] = None
    chunks: Optional[int] = None
    characters: Optional[int] = None
    error: Optional[str] = None


class SessionInfo(BaseModel):
    """会话信息"""
    session_id: str
    message_count: int
    created_at: str
    last_active: str


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "ok"
    version: str = "1.0.0"
    session_count: int = 0
