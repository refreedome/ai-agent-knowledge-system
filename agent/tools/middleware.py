"""
中间件模块

提供工具监控、日志记录、提示词切换等能力。
集成 Trace 链路追踪 + Metrics 性能指标采集。
继承自 LangChain 的 AgentMiddleware，适配新版 create_agent API。
"""

import time
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from utils.logger_handler import logger

# Trace 链路追踪（JSON 文件，记录每个步骤的输入/输出/耗时）
from infrastructure.tracing import tracer
# Metrics 性能指标（内存统计，P50/P95 耗时、Token 消耗、成功率）
from infrastructure.metrics import metrics_collector


class MonitorToolMiddleware(AgentMiddleware):
    """
    工具调用监控中间件

    监控粒度：
    - before_agent: Agent 整体启动，创建 Trace 会话
    - after_agent:  Agent 整体结束，保存 Trace + 记录总指标
    - wrap_tool_call: 每次工具调用，记录 Trace 步骤 + 单次耗时指标
    """

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Agent 开始处理时记录"""
        messages = state.get("messages", [])
        query = messages[-1].content if messages else ""
        logger.info(f"[中间件] Agent 开始处理, 查询: {str(query)[:50]}...")

        # 记录开始时间
        start_time = time.time()

        # 创建 Trace 会话
        trace_session = tracer.create_trace()
        trace_session.add_metadata("query", str(query)[:200])

        # 添加 Agent 起始步骤
        step = trace_session.add_step("Agent 启动", "agent_start")
        step.set_input({"query": str(query)[:200]})
        step.finish()

        return {
            "_agent_start_time": start_time,
            "_trace_session": trace_session,
        }

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Agent 整体处理完成时记录"""
        messages = state.get("messages", [])
        query = messages[-1].content if messages else ""

        start_time = state.get("_agent_start_time")
        trace_session = state.get("_trace_session")

        if start_time:
            total_duration = time.time() - start_time
            logger.info(f"[中间件] Agent 处理完成, 总耗时: {total_duration:.3f}s")

            # 记录总指标
            metrics_collector.record_request(
                endpoint="agent",
                duration_ms=total_duration * 1000,
                success=True,
                metadata={"query": str(query)[:200]}
            )

        if trace_session:
            # 添加完成步骤
            step = trace_session.add_step("Agent 完成", "agent_end")
            step.set_output({"duration_s": round(time.time() - (start_time or time.time()), 3)})
            step.finish()

            # 保存 Trace 到 JSON 文件
            filepath = trace_session.save()
            logger.info(f"[Trace] 已保存: {filepath}")

        return None

    def wrap_tool_call(self, request, handler):
        """
        拦截并记录每次工具调用

        request: ToolCallRequest 对象
        handler: 实际执行工具的函数
        """
        tool_name = request.tool_call.get("name", "unknown")
        args = request.tool_call.get("args", {})
        logger.info(f"[中间件] 工具调用开始: {tool_name}, 参数: {args}")

        # 从 state 中获取 Trace 会话
        state = request.state
        trace_session = state.get("_trace_session") if state else None

        # 添加 Trace 步骤
        trace_step = None
        if trace_session:
            trace_step = trace_session.add_step(f"工具调用: {tool_name}", "tool_call")
            trace_step.set_input({"tool": tool_name, "args": args})

        start = time.time()
        try:
            result = handler(request)
            duration = time.time() - start

            logger.info(f"[中间件] 工具调用完成: {tool_name}, 耗时: {duration:.3f}s")

            # 记录工具指标
            metrics_collector.record_request(
                endpoint=f"tool_{tool_name}",
                duration_ms=duration * 1000,
                success=True,
                metadata={"tool_name": tool_name, "args": str(args)[:200]}
            )

            # 完成 Trace 步骤
            if trace_step:
                trace_step.set_output({"result": str(result)[:500]})
                trace_step.add_metadata("duration_ms", round(duration * 1000, 2))
                trace_step.finish()

            return result

        except Exception as e:
            duration = time.time() - start
            logger.error(f"[中间件] 工具调用异常: {tool_name}, 错误: {str(e)}")

            # 记录失败指标
            metrics_collector.record_request(
                endpoint=f"tool_{tool_name}",
                duration_ms=duration * 1000,
                success=False,
                metadata={"tool_name": tool_name, "error": str(e)[:200]}
            )

            # 标记 Trace 步骤为失败
            if trace_step:
                trace_step.set_output({"error": str(e)[:500]})
                trace_step.add_metadata("duration_ms", round(duration * 1000, 2))
                trace_step.finish()

            raise


class LogBeforeModelMiddleware(AgentMiddleware):
    """模型调用前后记录日志 + Trace"""

    def __init__(self):
        self._llm_start_time = None
        self._llm_trace_step = None

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        logger.info(f"[中间件] 当前消息数: {len(messages)}, 即将调用模型")

        self._llm_start_time = time.time()
        self._llm_trace_step = None

        trace_session = state.get("_trace_session") if state else None
        if trace_session:
            step = trace_session.add_step("LLM 调用", "llm_call")
            step.set_input({"message_count": len(messages)})
            self._llm_trace_step = step

        return None

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """模型输出完成时记录"""
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else None
        logger.info("[中间件] 模型输出完成")

        duration = time.time() - (self._llm_start_time or time.time())

        # 提取 Token 消耗信息（兼容不同 LangChain 版本和模型提供商）
        tokens_used = 0
        if last_msg:
            if hasattr(last_msg, 'usage_metadata') and last_msg.usage_metadata:
                meta = last_msg.usage_metadata
                tokens_used = meta.get("total_tokens", 0)
                logger.info(
                    f"[中间件] Token 消耗: 输入={meta.get('input_tokens', 0)}, "
                    f"输出={meta.get('output_tokens', 0)}, 总计={tokens_used}"
                )
            elif hasattr(last_msg, 'response_metadata') and last_msg.response_metadata:
                usage = last_msg.response_metadata.get("token_usage", {})
                if usage:
                    tokens_used = usage.get("total_tokens", 0)
                    logger.info(
                        f"[中间件] Token 消耗(response_metadata): "
                        f"输入={usage.get('input_tokens', 0)}, "
                        f"输出={usage.get('output_tokens', 0)}, 总计={tokens_used}"
                    )

        # 完成 LLM Trace 步骤
        if self._llm_trace_step:
            content_preview = str(last_msg.content)[:200] if last_msg and hasattr(last_msg, 'content') else ""
            self._llm_trace_step.set_output({"response_preview": content_preview})
            self._llm_trace_step.add_metadata("duration_ms", round(duration * 1000, 2))
            self._llm_trace_step.add_metadata("tokens_used", tokens_used)
            self._llm_trace_step.finish()

        # 记录 LLM 调用指标（含 Token 消耗）
        if last_msg and hasattr(last_msg, 'content'):
            metrics_collector.record_request(
                endpoint="llm_call",
                duration_ms=duration * 1000,
                tokens_used=tokens_used,
                success=True,
            )

        return None


class ReportPromptSwitchMiddleware(AgentMiddleware):
    """报告场景提示词切换"""

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        context = getattr(runtime, "context", {}) or {}
        if context.get("report"):
            logger.info("[中间件] 检测到报告生成场景")
            state["_report_mode"] = True
        return None


def create_default_middleware():
    """创建默认中间件列表"""
    return [
        MonitorToolMiddleware(),
        LogBeforeModelMiddleware(),
        ReportPromptSwitchMiddleware(),
    ]
