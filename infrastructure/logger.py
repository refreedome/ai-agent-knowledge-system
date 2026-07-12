"""
结构化日志模块

企业级应用需要记录详细的操作日志，用于：
1. 问题排查 - 出错时快速定位原因
2. 性能分析 - 找出慢的环节
3. 审计追踪 - 记录谁做了什么操作

JSONL格式（每行一个JSON对象）便于后续用ELK栈分析
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict


class StructuredLogger:
    """
    结构化日志记录器

    相比普通日志的优势：
    - 记录为JSON格式，包含更多上下文信息
    - 可以记录结构化数据（如工具调用参数、耗时等）
    - 便于程序化分析和可视化
    """

    def __init__(self, name: str = "enterprise_agent"):
        """
        初始化日志记录器

        参数：
        - name: 日志名称，用于区分不同模块
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        # 创建logs目录
        os.makedirs("logs", exist_ok=True)

        # 添加文件处理器（JSONL格式）
        file_handler = logging.FileHandler(f"logs/{name}.jsonl", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)

        # 添加控制台处理器（方便调试）
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        self.logger.addHandler(console_handler)

    def _log_json(self, level: str, event: str, data: Dict[str, Any]):
        """
        记录JSON格式的日志

        参数：
        - level: 日志级别（INFO/WARNING/ERROR）
        - event: 事件类型（如tool_call、agent_start等）
        - data: 要记录的额外数据
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),  # 时间戳
            "level": level,                            # 日志级别
            "event": event,                            # 事件类型
            **data                                     # 展开额外数据
        }

        # 将字典转为JSON字符串并记录
        log_message = json.dumps(log_entry, ensure_ascii=False)

        if level == "ERROR":
            self.logger.error(log_message)
        elif level == "WARNING":
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)

    def log_agent_start(self, user_id: str, query: str):
        """记录Agent开始处理请求"""
        self._log_json("INFO", "agent_start", {
            "user_id": user_id,
            "query_preview": query[:50]  # 只记录前50个字符
        })

    def log_agent_end(self, user_id: str, duration_ms: float):
        """记录Agent处理完成"""
        self._log_json("INFO", "agent_end", {
            "user_id": user_id,
            "duration_ms": round(duration_ms, 2)
        })

    def log_tool_call(self, tool_name: str, params: Dict, result_preview: str, duration_ms: float):
        """
        记录工具调用

        参数：
        - tool_name: 工具名称
        - params: 传入参数
        - result_preview: 结果预览（截断）
        - duration_ms: 耗时（毫秒）
        """
        self._log_json("INFO", "tool_call", {
            "tool_name": tool_name,
            "params": params,
            "result_preview": result_preview[:100],
            "duration_ms": round(duration_ms, 2)
        })

    def log_error(self, error_type: str, message: str, context: Dict = None):
        """
        记录错误信息

        参数：
        - error_type: 错误类型
        - message: 错误消息
        - context: 错误发生的上下文
        """
        self._log_json("ERROR", error_type, {
            "message": message,
            "context": context or {}
        })

    def log_performance(self, operation: str, duration_ms: float, metrics: Dict = None):
        """
        记录性能指标

        参数：
        - operation: 操作名称
        - duration_ms: 耗时
        - metrics: 其他指标（如token数量）
        """
        self._log_json("INFO", "performance", {
            "operation": operation,
            "duration_ms": round(duration_ms, 2),
            "metrics": metrics or {}
        })


# 创建全局日志实例
logger = StructuredLogger()


# 测试代码
if __name__ == '__main__':
    # 测试结构化日志
    logger.log_agent_start("user_001", "什么是RAG技术？")
    logger.log_tool_call(
        tool_name="knowledge_search",
        params={"query": "RAG"},
        result_preview="RAG是检索增强生成...",
        duration_ms=1234.56
    )
    logger.log_agent_end("user_001", 2345.67)
