"""上下文压缩（Compaction）单元测试 —— 全 Mock，无需 API Key、离线可跑"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import patch

from database.compaction import CompactionService
from database.session_manager import SessionManager


class TestCompactionService:
    """压缩服务本身"""

    def test_empty_messages_returns_prev_summary(self):
        """没有新消息时不产生新摘要，原样返回旧摘要"""
        svc = CompactionService()
        assert svc.compact([], "已有摘要") == "已有摘要"

    def test_llm_summary_used_when_available(self):
        """LLM 可用时使用模型摘要"""
        svc = CompactionService()
        with patch.object(svc, "_llm_summarize", return_value="用户关注宠物毛发清理"):
            out = svc.compact([{"role": "user", "content": "我家有两只猫"}], "")
        assert out == "用户关注宠物毛发清理"

    def test_fallback_to_structured_note_on_failure(self):
        """LLM 失败时降级为结构化笔记，关键信息不能丢"""
        svc = CompactionService()
        msgs = [
            {"role": "user", "content": "我家有两只猫，滚刷老缠毛"},
            {"role": "assistant", "content": "推荐防缠绕滚刷的机型"},
        ]
        with patch.object(svc, "_llm_summarize", side_effect=RuntimeError("no api key")):
            note = svc.compact(msgs, "")
        assert "两只猫" in note
        assert "防缠绕" in note

    def test_prev_summary_passed_for_incremental_merge(self):
        """增量压缩：旧摘要要作为参数传给 LLM，避免全量重算"""
        svc = CompactionService()
        with patch.object(svc, "_llm_summarize", return_value="合并后的摘要") as m:
            svc.compact([{"role": "user", "content": "新内容"}], "旧摘要")
        assert m.call_args[0][1] == "旧摘要"


class TestContextWindowCompaction:
    """会话窗口与压缩的联动"""

    def test_summary_injected_and_compaction_is_incremental(self):
        sm = SessionManager()
        sid = sm.create_session(user_id="compaction_test_user")

        # 写入远超窗口（4000 字符）的历史
        for i in range(30):
            sm.add_message(sid, "user", f"问题{i}：" + "内容" * 120)
            sm.add_message(sid, "assistant", f"回答{i}：" + "内容" * 120)

        # 第一次取窗口：应该触发压缩，并把摘要以 system 消息注入
        with patch(
            "database.session_manager.compaction_service.compact",
            return_value="历史摘要ABC",
        ) as m1:
            window = sm.get_context_window(sid)
        assert m1.call_count == 1
        assert window[0]["role"] == "system"
        assert "历史摘要ABC" in window[0]["content"]
        assert len(window) > 1  # 摘要之后还有原文

        count_after_first = sm._sessions[sid].compacted_count
        assert count_after_first > 0

        # 第二次取窗口：没有新消息被挤出 → 不应重复压缩
        with patch(
            "database.session_manager.compaction_service.compact",
            return_value="历史摘要ABC",
        ) as m2:
            window2 = sm.get_context_window(sid)
        assert m2.call_count == 0, "没有新内容被挤出时不应重复调用压缩"
        assert sm._sessions[sid].compacted_count == count_after_first
        assert window2[0]["role"] == "system"

        sm.clear_session(sid)

    def test_short_history_not_compacted(self):
        """历史很短时不触发压缩（没有内容被挤出窗口）"""
        sm = SessionManager()
        sid = sm.create_session(user_id="short_test_user")
        sm.add_message(sid, "user", "小户型适合哪些扫地机器人？")
        sm.add_message(sid, "assistant", "推荐小巧机型的扫地机器人。")

        with patch(
            "database.session_manager.compaction_service.compact",
            return_value="不应被调用",
        ) as m:
            window = sm.get_context_window(sid)
        assert m.call_count == 0
        assert all(msg["role"] != "system" for msg in window)

        sm.clear_session(sid)
