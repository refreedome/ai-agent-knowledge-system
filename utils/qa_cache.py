"""
热点问题缓存（简单版）

功能：
- 相同问题在 TTL 内直接返回缓存答案，节省 LLM 调用
- LRU 容量控制：超过 max_size 淘汰最久未命中项
- 线程安全（Streamlit / FastAPI 多线程场景）
- 提供命中统计，便于演示"高频问题秒回"效果

说明：
- 缓存键 = 归一化问题（去空白、全角转半角、去标点、小写）
- 缓存值 = 完整回答文本（含思考过程，与原始流式输出一致）
"""

import re
import time
import threading
from collections import OrderedDict


class QACache:
    """热点问题缓存（单例）"""

    def __init__(self, max_size: int = 200, ttl_seconds: int = 600):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._cache: OrderedDict[str, tuple] = OrderedDict()  # key -> (expire_ts, answer)
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    # ────────────── 工具方法 ──────────────

    @staticmethod
    def _normalize(question: str) -> str:
        """归一化问题：去首尾空白、全角转半角、去标点、统一小写"""
        q = question.strip().lower()
        # 全角标点转半角
        table = str.maketrans(
            '，。！？；：""''（）【】～',
            ',.!?;:\"\"''()[]~',
        )
        q = q.translate(table)
        # 去除所有空白字符
        q = re.sub(r'\s+', '', q)
        return q

    @staticmethod
    def iter_chunks(text: str, size: int = 80, delay: float = 0.03):
        """将缓存答案分片 yield，模拟流式输出节奏（秒回 + 打字机效果）"""
        for i in range(0, len(text), size):
            yield text[i:i + size]
            if delay > 0:
                time.sleep(delay)

    # ────────────── 核心 API ──────────────

    def get(self, question: str):
        """查询缓存；未命中或已过期返回 None"""
        key = self._normalize(question)
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                self.misses += 1
                return None
            expire_ts, answer = item
            if time.time() > expire_ts:
                # 过期：删除
                self._cache.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            self._cache.move_to_end(key)  # 更新 LRU 位置
            return answer

    def put(self, question: str, answer: str):
        """写入缓存（空答案不缓存）"""
        if not answer or not answer.strip():
            return
        key = self._normalize(question)
        with self._lock:
            self._cache[key] = (time.time() + self._ttl, answer)
            self._cache.move_to_end(key)
            # LRU 淘汰：超出容量移除最久未命中的项
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def stats(self) -> dict:
        """缓存统计（演示用）"""
        with self._lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / (self.hits + self.misses), 4) if (self.hits + self.misses) else 0.0,
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl_seconds": self._ttl,
            }


# 全局单例
qa_cache = QACache()
