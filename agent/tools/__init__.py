"""
工具包初始化

统一导出所有工具和注册表
"""

from .registry import registry, ToolRegistry
from .base_tool import BaseTool, ToolResult
from .knowledge_tools import (
    KnowledgeSearchTool, 
    DocumentUploadTool,
    register_knowledge_tools
)
from .system_tools import (
    QueryHistoryTool,
    GenerateSummaryTool,
    ExportReportTool,
    register_system_tools
)


def init_all_tools():
    """初始化并注册所有工具"""
    register_knowledge_tools()
    register_system_tools()
    
    return registry


# 自动初始化
all_registry = init_all_tools()
