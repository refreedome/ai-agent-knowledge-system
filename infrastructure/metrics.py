"""
性能指标收集模块

用于监控系统运行状态，包括：
1. 响应时间 - 平均耗时、P95、P99
2. Token消耗 - 每次调用的Token数量
3. 成功率 - 成功/失败的比例
4. 工具调用统计 - 哪些工具最常用

这些数据可以用于：
- 性能优化（找出瓶颈）
- 成本核算（Token费用）
- 容量规划（并发能力）
"""

import time
from collections import defaultdict
from typing import Any, Dict, List

import json


class MetricsCollector:
    """
    性能指标收集器

    使用内存存储，适合单机部署
    生产环境可以用Prometheus或InfluxDB
    """

    def __init__(self):
        """初始化指标收集器"""
        # 按端点分组存储指标
        self.metrics: Dict[str, List[Dict]] = defaultdict(list)

    def record_request(self,
                      endpoint: str,
                      duration_ms: float,
                      tokens_used: int = 0,
                      success: bool = True,
                      metadata: Dict = None):
        """
        记录一次请求

        参数：
        - endpoint: 端点名称（如"chat"、"knowledge_search"）
        - duration_ms: 耗时（毫秒）
        - tokens_used: Token消耗
        - success: 是否成功
        - metadata: 其他元数据
        """
        self.metrics[endpoint].append({
            "timestamp": time.time(),
            "duration_ms": duration_ms,
            "tokens_used": tokens_used,
            "success": success,
            "metadata": metadata or {}
        })

    def get_stats(self, endpoint: str, window_seconds: int = 3600) -> Dict:
        """
        获取最近一段时间的统计数据

        参数：
        - endpoint: 端点名称
        - window_seconds: 时间窗口（秒），默认1小时

        返回：
        - 统计字典
        """
        now = time.time()

        # 过滤出最近的记录
        recent = [
            m for m in self.metrics[endpoint]
            if now - m["timestamp"] < window_seconds
        ]

        if not recent:
            return None

        # 计算统计值
        total_requests = len(recent)
        durations = [m["duration_ms"] for m in recent]
        tokens = [m["tokens_used"] for m in recent]
        successes = sum(1 for m in recent if m["success"])

        # 排序用于计算百分位
        durations.sort()

        stats = {
            "endpoint": endpoint,
            "time_window": f"{window_seconds}s",
            "total_requests": total_requests,
            "avg_duration_ms": round(sum(durations) / total_requests, 2),
            "min_duration_ms": round(min(durations), 2),
            "max_duration_ms": round(max(durations), 2),
            "p50_duration_ms": round(durations[int(total_requests * 0.5)], 2),
            "p95_duration_ms": round(durations[int(total_requests * 0.95)], 2),
            "total_tokens": sum(tokens),
            "avg_tokens": round(sum(tokens) / total_requests, 2),
            "success_rate": round(successes / total_requests * 100, 2),
            "failed_requests": total_requests - successes
        }

        return stats

    def get_all_stats(self, window_seconds: int = 3600) -> Dict[str, Dict]:
        """获取所有端点的统计"""
        result = {}
        for endpoint in self.metrics.keys():
            stats = self.get_stats(endpoint, window_seconds)
            if stats:
                result[endpoint] = stats
        return result

    def get_top_tools(self, limit: int = 5) -> List[Dict]:
        """
        获取最常用的工具排行

        参数：
        - limit: 返回前N个

        返回：
        - 工具使用统计列表
        """
        tool_stats = defaultdict(int)

        # 统计工具调用次数
        for call in self.metrics.get("tool_call", []):
            tool_name = call.get("metadata", {}).get("tool_name", "unknown")
            tool_stats[tool_name] += 1

        # 排序
        sorted_tools = sorted(tool_stats.items(), key=lambda x: x[1], reverse=True)

        return [
            {"tool_name": name, "call_count": count}
            for name, count in sorted_tools[:limit]
        ]

    def reset(self):
        """重置所有指标（用于测试）"""
        self.metrics.clear()


# 创建全局指标收集器
metrics_collector = MetricsCollector()


# 测试代码
if __name__ == '__main__':
    import random

    # 模拟一些请求
    for i in range(100):
        metrics_collector.record_request(
            endpoint="chat",
            duration_ms=random.uniform(1000, 5000),
            tokens_used=random.randint(100, 500),
            success=random.random() > 0.1  # 90%成功率
        )

    for i in range(50):
        metrics_collector.record_request(
            endpoint="knowledge_search",
            duration_ms=random.uniform(500, 2000),
            tokens_used=random.randint(50, 200),
            success=True,
            metadata={"tool_name": "knowledge_search"}
        )

    # 获取统计
    chat_stats = metrics_collector.get_stats("chat")
    print("聊天接口统计:")
    print(json.dumps(chat_stats, indent=2, ensure_ascii=False))

    print("\n搜索接口统计:")
    search_stats = metrics_collector.get_stats("knowledge_search")
    print(json.dumps(search_stats, indent=2, ensure_ascii=False))

    print("\nTop工具:")
    top_tools = metrics_collector.get_top_tools()
    print(json.dumps(top_tools, indent=2, ensure_ascii=False))
