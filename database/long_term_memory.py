"""
长期记忆服务（Long-Term Memory）

记忆分层：
- 短期记忆 = 会话内的滑动窗口（SessionManager 管理，跨轮次）
- 长期记忆 = 跨会话持久化的用户偏好事实，回答时注入上下文

实现要点：
- JSON 文件持久化（data/memory.json）+ 内存缓存，服务重启不丢
- 线程锁保护（并发写安全）
- 启发式正则从用户输入中抽取偏好事实（喜欢/需要/我家…）
- 每条用户记忆有上限（FIFO 淘汰），防止无限膨胀
"""

import json
import os
import re
import threading
from datetime import datetime

from utils.logger_handler import logger
from utils.path_tool import get_abs_path
from utils.config_handler import agent_conf


class LongTermMemory:
    """长期记忆（单例）"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        mem_conf = agent_conf.get("memory", {})
        self._max_facts = mem_conf.get("max_facts", 20)
        self._recall_top = mem_conf.get("recall_top", 3)

        self._path = get_abs_path("data/memory.json")
        self._lock = threading.Lock()
        self._memories = {}  # user_id -> [{"fact": str, "created_at": str}, ...]
        self._load()
        logger.info(f"[Memory] 长期记忆初始化完成: max_facts={self._max_facts}, recall_top={self._recall_top}")

    # ────────────── 持久化 ──────────────

    def _load(self):
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._memories = json.load(f)
            logger.info(f"[Memory] 已加载长期记忆，共 {len(self._memories)} 个用户")
        except Exception as e:
            logger.warning(f"[Memory] 加载失败: {e}")

    def _save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._memories, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[Memory] 保存失败: {e}")

    # ────────────── 核心 API ──────────────

    def remember(self, user_id: str, fact: str):
        """记住一条事实（去重 + 上限 FIFO 裁剪）"""
        fact = fact.strip()
        if not fact:
            return
        with self._lock:
            facts = self._memories.setdefault(user_id, [])
            if any(f["fact"] == fact for f in facts):
                return
            facts.append({"fact": fact, "created_at": datetime.now().isoformat()})
            if len(facts) > self._max_facts:
                facts = facts[-self._max_facts:]
            self._memories[user_id] = facts
            self._save()
            logger.info(f"[Memory] 记住新事实: {fact[:40]}...")

    def recall(self, user_id: str, limit: int = None) -> list:
        """回忆最近的事实（返回 dict 列表）"""
        limit = limit or self._recall_top
        with self._lock:
            facts = self._memories.get(user_id, [])
        return facts[-limit:]

    # ────────────── 事实抽取（启发式） ──────────────

    @staticmethod
    def extract_facts(text: str) -> list:
        """
        从用户输入中抽取偏好事实

        规则（可扩展）：命中「我家… / 我喜欢… / 我想要… / 我需要…」等
        偏好句式即认为是一条长期事实。生产环境可替换为 LLM 抽取。
        """
        if not text:
            return []
        patterns = [
            r"我家(?:是|有|住|用|在|比较)[^。！？，\n]{2,40}",
            r"我(?:喜欢|想要|需要|用的是|住在|在意|关注|希望)[^。！？，\n]{2,40}",
        ]
        facts = []
        for p in patterns:
            facts.extend(m.group(0) for m in re.finditer(p, text))
        return facts


# 全局单例
long_term_memory = LongTermMemory()
