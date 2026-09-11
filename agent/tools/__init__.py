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
from .agent_tools import (
    rag_summarize,
    get_weather,
    get_user_location,
    get_user_id,
    get_current_month,
    fetch_external_data,
    fill_context_for_report,
)


def init_all_tools():
    """初始化并注册所有工具"""
    register_knowledge_tools()
    register_system_tools()

    # 注册 @tool 装饰器工具，保证与主提示词 main_prompt.txt 中描述的工具一致
    for t in (
        rag_summarize, get_weather, get_user_location,
        get_user_id, get_current_month, fetch_external_data, fill_context_for_report,
    ):
        if t.name not in registry:
            registry.register(t, required_role="user")

    return registry


# 自动初始化
all_registry = init_all_tools()
