"""
API 数据模型 (Pydantic)
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


class ChatRequest(BaseModel):
    """聊天请求"""
    query: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    session_id: Optional[str] = Field(None, description="会话ID，不传则自动创建")
    user_id: Optional[str] = Field("default", max_length=64, description="用户标识，用于会话与记忆隔离")

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, v: str) -> str:
        """
        拦截「纯空白」输入

        注意：min_length=1 只能拦住空字符串，" "（一个空格）长度是 1 会穿透进来，
        实测发现它会一路走到 LLM 白烧一次 Token。这里做一次 strip 后再判空，
        同时把首尾空白规范化掉（顺带防止 " 问题 " 这类脏输入）。
        """
        stripped = (v or "").strip()
        if not stripped:
            raise ValueError("query 不能为空白字符")
        return stripped


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
    user_id: Optional[str] = "default"
    message_count: int
    created_at: str
    last_active: str


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "ok"
    version: str = "1.0.0"
    session_count: int = 0


class MetricsResponse(BaseModel):
    """性能指标响应"""
    stats: dict
    total_requests: int = 0
