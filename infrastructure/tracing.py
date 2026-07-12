"""
Agent执行链路追踪模块

企业级应用需要记录每次请求的完整执行过程，用于：
1. 问题排查 - 了解Agent为什么做出某个决策
2. 性能优化 - 找出哪个环节最慢
3. 质量改进 - 分析工具的调用模式

类似分布式追踪系统（如Jaeger），但更简化
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List
import uuid


class TraceStep:
    """追踪步骤 - 记录Agent执行的每个环节"""

    def __init__(self, step_name: str, step_type: str):
        """
        初始化追踪步骤

        参数：
        - step_name: 步骤名称（如"意图识别"）
        - step_type: 步骤类型（intent/tool_call/answer等）
        """
        self.step_name = step_name
        self.step_type = step_type
        self.start_time = datetime.now()
        self.end_time = None
        self.input_data = None
        self.output_data = None
        self.metadata = {}

    def set_input(self, data: Any):
        """设置输入数据"""
        self.input_data = data

    def set_output(self, data: Any):
        """设置输出数据"""
        self.output_data = data

    def add_metadata(self, key: str, value: Any):
        """添加元数据"""
        self.metadata[key] = value

    def finish(self):
        """标记步骤完成"""
        self.end_time = datetime.now()

    def get_duration_ms(self) -> float:
        """获取耗时（毫秒）"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return 0

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            "step_name": self.step_name,
            "step_type": self.step_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": round(self.get_duration_ms(), 2),
            "input": self._safe_serialize(self.input_data),
            "output": self._safe_serialize(self.output_data),
            "metadata": self.metadata
        }

    def _safe_serialize(self, obj: Any) -> Any:
        """安全序列化（处理不能序列化的对象）"""
        if obj is None:
            return None
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)  # 如果不能序列化，转为字符串


class AgentTracer:
    """
    Agent追踪器

    记录一次完整请求的所有步骤，保存到JSON文件
    """

    def __init__(self, trace_dir: str = "logs/traces"):
        """
        初始化追踪器

        参数：
        - trace_dir: Trace文件存储目录
        """
        self.trace_dir = trace_dir
        os.makedirs(trace_dir, exist_ok=True)

    def create_trace(self, trace_id: str = None) -> 'TraceSession':
        """
        创建一个新的追踪会话

        参数：
        - trace_id: 追踪ID（自动生成）

        返回：
        - TraceSession对象
        """
        if not trace_id:
            trace_id = f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        return TraceSession(trace_id, self.trace_dir)


class TraceSession:
    """
    追踪会话 - 管理一次完整请求的所有步骤
    """

    def __init__(self, trace_id: str, trace_dir: str):
        """
        初始化追踪会话

        参数：
        - trace_id: 追踪ID
        - trace_dir: 存储目录
        """
        self.trace_id = trace_id
        self.trace_dir = trace_dir
        self.steps: List[TraceStep] = []
        self.start_time = datetime.now()
        self.metadata = {}

    def add_step(self, step_name: str, step_type: str) -> TraceStep:
        """
        添加一个新步骤

        参数：
        - step_name: 步骤名称
        - step_type: 步骤类型

        返回：
        - TraceStep对象
        """
        step = TraceStep(step_name, step_type)
        self.steps.append(step)
        return step

    def add_metadata(self, key: str, value: Any):
        """添加会话级别的元数据"""
        self.metadata[key] = value

    def save(self):
        """
        保存Trace到JSON文件

        文件格式：logs/traces/{trace_id}.json
        """
        end_time = datetime.now()

        trace_data = {
            "trace_id": self.trace_id,
            "start_time": self.start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "total_duration_ms": round((end_time - self.start_time).total_seconds() * 1000, 2),
            "steps": [step.to_dict() for step in self.steps],
            "metadata": self.metadata
        }

        filepath = os.path.join(self.trace_dir, f"{self.trace_id}.json")

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(trace_data, f, ensure_ascii=False, indent=2)

        return filepath

    def get_summary(self) -> Dict:
        """获取Trace摘要（不保存）"""
        return {
            "trace_id": self.trace_id,
            "total_steps": len(self.steps),
            "total_duration_ms": round((datetime.now() - self.start_time).total_seconds() * 1000, 2),
            "steps": [
                {
                    "step_name": step.step_name,
                    "step_type": step.step_type,
                    "duration_ms": step.get_duration_ms()
                }
                for step in self.steps
            ]
        }


# 创建全局追踪器实例
tracer = AgentTracer()


# 测试代码
if __name__ == '__main__':
    # 创建一个追踪会话
    session = tracer.create_trace()
    session.add_metadata("user_id", "test_user")
    session.add_metadata("query", "什么是RAG？")

    # 步骤1：意图识别
    step1 = session.add_step("意图识别", "intent")
    step1.set_input({"query": "什么是RAG？"})
    step1.set_output({"intent": "knowledge_query"})
    step1.finish()

    # 步骤2：工具调用
    step2 = session.add_step("知识库检索", "tool_call")
    step2.set_input({"tool": "knowledge_search", "params": {"query": "RAG"}})
    step2.set_output({"result": "RAG是检索增强生成..."})
    step2.add_metadata("retrieved_docs", 5)
    step2.finish()

    # 步骤3：生成回答
    step3 = session.add_step("生成回答", "answer")
    step3.set_input({"context": "...", "query": "什么是RAG？"})
    step3.set_output({"answer": "RAG是一种...技术"})
    step3.finish()

    # 保存Trace
    filepath = session.save()
    print(f"Trace已保存到: {filepath}")

    # 打印摘要
    summary = session.get_summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
