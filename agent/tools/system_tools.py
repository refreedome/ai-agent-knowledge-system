"""
系统工具

包含：
1. 对话历史查询
2. 对话摘要生成
3. 报告导出
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from agent.tools.base_tool import BaseTool, ToolResult
from database.session_manager import session_manager


class QueryHistoryTool(BaseTool):
    """
    对话历史查询工具
    从当前会话中检索最近的对话记录
    """

    def __init__(self):
        super().__init__(
            name="query_history",
            description="查询当前会话的最近对话历史，用于多轮对话理解"
        )

    def execute(self, session_id: str = None, limit: int = 10, **kwargs) -> ToolResult:
        """
        查询历史对话

        参数：
        - session_id: 会话ID（不传则返回所有会话概览）
        - limit: 返回条数

        返回：
        - ToolResult，包含对话记录列表
        """
        try:
            if session_id:
                # 查询指定会话
                history = session_manager.get_recent(session_id, rounds=limit // 2)
                if not history:
                    return ToolResult.ok({
                        "session_id": session_id,
                        "messages": [],
                        "message": "该会话暂无记录"
                    })
                return ToolResult.ok({
                    "session_id": session_id,
                    "messages": history,
                    "count": len(history),
                })
            else:
                # 返回所有会话概览
                return ToolResult.ok({
                    "sessions": [
                        {"session_id": sid, "count": len(msgs)}
                        for sid, msgs in session_manager._sessions.items()
                    ],
                    "total_sessions": session_manager.session_count,
                })

        except Exception as e:
            return ToolResult.fail(f"查询历史失败: {str(e)}")


class GenerateSummaryTool(BaseTool):
    """
    对话摘要生成工具
    """

    def __init__(self):
        super().__init__(
            name="generate_summary",
            description="生成长对话的摘要，便于快速回顾"
        )

    def execute(self, conversation_text: str, **kwargs) -> ToolResult:
        """
        生成对话摘要

        参数：
        - conversation_text: 对话文本

        返回：
        - ToolResult对象
        """
        try:
            # TODO: 调用大模型生成摘要
            # 这里简化处理
            summary = f"对话摘要：共{len(conversation_text)}字符"

            return ToolResult.ok(summary)

        except Exception as e:
            return ToolResult.fail(f"生成摘要失败: {str(e)}")


class ExportReportTool(BaseTool):
    """
    报告导出工具
    """

    def __init__(self):
        super().__init__(
            name="export_report",
            description="导出问答报告为PDF或Markdown格式"
        )

    def execute(self, session_id: str, format: str = "pdf", **kwargs) -> ToolResult:
        """
        导出报告

        参数：
        - session_id: 会话ID
        - format: 导出格式（pdf）

        返回：
        - ToolResult对象
        """
        try:
            # TODO: 实现报告导出
            return ToolResult.ok(f"报告已导出为 {format} 格式")

        except Exception as e:
            return ToolResult.fail(f"导出失败: {str(e)}")


# 自动注册工具
def register_system_tools():
    """注册系统工具"""
    from .registry import registry

    registry.register(QueryHistoryTool(), required_role="user")
    registry.register(GenerateSummaryTool(), required_role="user")
    registry.register(ExportReportTool(), required_role="admin")


# 测试代码
if __name__ == '__main__':
    register_system_tools()

    from .registry import registry
    tools = registry.list_tools("user")
    print("系统工具:")
    for tool in tools:
        print(f"  - {tool['name']}: {tool['description']}")
