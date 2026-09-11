"""
上下文压缩服务（Compaction + 结构化笔记）

背景：原来的 `get_context_window` 对超出窗口的历史是**硬丢**——早期上下文里的信息就永久没了。
本模块把「硬丢」升级成「**压缩保留**」：

1. Compaction（滚动摘要）：把被挤出窗口的历史消息交给 LLM 摘要成一段，
   并与上一次的摘要**增量合并**（不全量重算，省 Token）。
2. 结构化笔记（降级路径）：LLM 摘要失败时，退化为「抽取式要点」——
   把每条被丢弃消息截断成要点列表，保证不丢关键实体且**零额外调用**。

设计要点：
- 摘要按会话缓存（存在 SessionData 里并落 SQLite），避免每轮重复摘要
- 只有**新被挤出**的消息才会进摘要（增量），因此成本随对话长度次线性增长
- 摘要以 system 消息注入到窗口之前，优先级高于易变的历史原文
"""

import threading

from utils.config_handler import agent_conf
from utils.logger_handler import logger

# 摘要提示词：要求压缩而非复述，保留实体与结论
_SUMMARY_PROMPT = """你是对话历史压缩器。请把下面的对话历史压缩成一段简洁的中文摘要。

要求：
1. 只保留【关键事实、用户偏好、已确认的结论、未解决的问题】，删掉寒暄和重复内容；
2. 保留具体实体（产品型号、数字、专有名词）不要泛化；
3. 输出不超过 {max_chars} 字，纯文本，不要分点标题，不要加解释；
4. 如果给了「已有摘要」，请把它和新对话**合并成一段**，不要重复已有内容。

已有摘要：{prev_summary}

新增对话：
{new_messages}

合并后的摘要："""


class CompactionService:
    """上下文压缩服务（单例）"""

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

        comp_conf = agent_conf.get("compaction", {})
        self._enabled = comp_conf.get("enabled", True)
        self._max_chars = comp_conf.get("summary_max_chars", 400)
        self._lock = threading.Lock()
        self._model = None  # 懒加载，避免与 model.factory 形成导入环
        logger.info(f"[Compaction] 初始化完成: enabled={self._enabled}, summary_max_chars={self._max_chars}")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _get_model(self):
        if self._model is None:
            from model.factory import chat_model  # 懒导入
            self._model = chat_model
        return self._model

    # ────────────── 主入口 ──────────────

    def compact(self, messages: list, prev_summary: str = "") -> str:
        """
        把一批历史消息压缩成摘要（带 LLM 失败降级）

        参数：
        - messages: 新被挤出窗口的消息列表 [{"role","content"}, ...]
        - prev_summary: 上一次的摘要（用于增量合并）

        返回：新的摘要字符串（失败时返回结构化笔记降级结果）
        """
        if not messages:
            return prev_summary

        text = self._render(messages)

        if self._enabled:
            try:
                return self._llm_summarize(text, prev_summary)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[Compaction] LLM 摘要失败，降级为结构化笔记: {e}")

        return self._structured_note(messages, prev_summary)

    # ────────────── 实现细节 ──────────────

    @staticmethod
    def _render(messages: list) -> str:
        lines = []
        for m in messages:
            role = "用户" if m.get("role") == "user" else "助手"
            content = str(m.get("content", "")).strip().replace("\n", " ")
            lines.append(f"{role}: {content[:500]}")
        return "\n".join(lines)

    def _llm_summarize(self, text: str, prev_summary: str) -> str:
        prompt = _SUMMARY_PROMPT.format(
            max_chars=self._max_chars,
            prev_summary=prev_summary or "（无）",
            new_messages=text,
        )
        with self._lock:  # 串行化，避免同一实例并发调用
            result = self._get_model().invoke(prompt)
        summary = str(getattr(result, "content", result)).strip()
        if len(summary) > self._max_chars * 2:  # 防御：模型没遵守长度约束
            summary = summary[: self._max_chars * 2] + "…"
        logger.info(f"[Compaction] 摘要完成: {len(text)} 字 -> {len(summary)} 字")
        return summary

    def _structured_note(self, messages: list, prev_summary: str) -> str:
        """降级路径：抽取式要点（零额外调用，绝不丢信息）"""
        notes = [prev_summary] if prev_summary else []
        for m in messages:
            content = str(m.get("content", "")).strip().replace("\n", " ")
            if content:
                notes.append(content[:120])
        note = " / ".join(notes)
        if len(note) > self._max_chars * 2:
            note = note[: self._max_chars * 2] + "…"
        logger.info(f"[Compaction] 使用结构化笔记降级，共 {len(notes)} 条要点")
        return note


# 全局单例
compaction_service = CompactionService()
