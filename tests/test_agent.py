"""Agent 模块单元测试"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import json
import time
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from datetime import datetime, timedelta

from abc import ABC
from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.registry import ToolRegistry
from database.session_manager import SessionManager, SessionData


# ═══════════════════════════════════════════
# ToolResult 测试
# ═══════════════════════════════════════════

class TestToolResult:
    """工具执行结果封装测试"""

    def test_ok(self):
        """成功结果应包含 data"""
        result = ToolResult.ok({"answer": "test"})
        assert result.success is True
        assert result.data == {"answer": "test"}
        assert result.error is None

    def test_fail(self):
        """失败结果应包含 error"""
        result = ToolResult.fail("出错了")
        assert result.success is False
        assert result.error == "出错了"
        assert result.data is None

    def test_to_string_success(self):
        """成功时 to_string 返回 data 的字符串形式"""
        result = ToolResult.ok({"answer": "hello"})
        assert "hello" in result.to_string()

    def test_to_string_fail(self):
        """失败时 to_string 包含错误信息"""
        result = ToolResult.fail("执行异常")
        assert "执行异常" in result.to_string()

    def test_to_dict(self):
        """to_dict 返回序列化字典"""
        result = ToolResult.ok("data")
        d = result.to_dict()
        assert d["success"] is True
        assert d["data"] == "data"


# ═══════════════════════════════════════════
# BaseTool 测试
# ═══════════════════════════════════════════

class TestBaseTool:
    """工具基类测试"""

    def test_cannot_instantiate_abstract(self):
        """抽象类不能直接实例化"""
        with pytest.raises(TypeError):
            BaseTool("test", "description")

    def test_concrete_tool(self):
        """实例子类应正常工作"""
        class MyTool(BaseTool):
            def execute(self, **kwargs):
                return ToolResult.ok(kwargs.get("input", "done"))

        tool = MyTool("my_tool", "我的测试工具")
        assert tool.name == "my_tool"
        assert tool.description == "我的测试工具"

    def test_execute(self):
        """execute 方法应返回正确结果"""
        class GreetTool(BaseTool):
            def execute(self, **kwargs):
                name = kwargs.get("name", "world")
                return ToolResult.ok(f"hello {name}")

        tool = GreetTool("greet", "打招呼")
        result = tool.execute(name="Agent")
        assert result.success is True
        assert "hello Agent" in str(result.data)

    def test_validate_params_default(self):
        """默认参数验证应返回 True"""
        class MyTool(BaseTool):
            def execute(self, **kwargs):
                return ToolResult.ok("done")

        tool = MyTool("t", "d")
        assert tool.validate_params(x=1) is True

    def test_validate_params_custom(self):
        """自定义参数验证"""
        class StrictTool(BaseTool):
            def execute(self, **kwargs):
                return ToolResult.ok("done")

            def validate_params(self, **kwargs) -> bool:
                return "name" in kwargs and len(kwargs["name"]) > 0

        tool = StrictTool("strict", "严格的工具")
        assert tool.validate_params(name="hello") is True
        assert tool.validate_params(name="") is False

    def test_to_dict(self):
        """to_dict 返回工具信息"""
        class MyTool(BaseTool):
            def execute(self, **kwargs):
                return ToolResult.ok("done")

        tool = MyTool("tool1", "desc1")
        d = tool.to_dict()
        assert d["name"] == "tool1"
        assert d["description"] == "desc1"

    def test_repr(self):
        """repr 应包含工具名"""
        class MyTool(BaseTool):
            def execute(self, **kwargs):
                return ToolResult.ok("done")

        tool = MyTool("mytool", "desc")
        assert "mytool" in repr(tool)


# ═══════════════════════════════════════════
# ToolRegistry 测试
# ═══════════════════════════════════════════

class TestToolRegistry:
    """工具注册表测试"""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """每个测试前后清空注册表"""
        registry = ToolRegistry()
        registry.clear()
        yield
        registry.clear()

    @pytest.fixture
    def sample_tool(self):
        class SampleTool(BaseTool):
            def execute(self, **kwargs):
                return ToolResult.ok(kwargs.get("query", ""))
        return SampleTool("sample", "示例工具")

    @pytest.fixture
    def admin_tool(self):
        class AdminTool(BaseTool):
            def execute(self, **kwargs):
                return ToolResult.ok("admin only")
        return AdminTool("admin_tool", "管理员工具")

    def test_register(self, sample_tool):
        """注册工具后应能获取"""
        registry = ToolRegistry()
        registry.register(sample_tool)
        assert "sample" in registry

    def test_register_duplicate(self, sample_tool):
        """重复注册应报错"""
        registry = ToolRegistry()
        registry.register(sample_tool)
        with pytest.raises(ValueError, match="已经注册"):
            registry.register(sample_tool)

    def test_get_tool(self, sample_tool):
        """按名称获取工具"""
        registry = ToolRegistry()
        registry.register(sample_tool)
        tool = registry.get_tool("sample")
        assert tool is not None
        assert tool.name == "sample"

    def test_get_tool_not_found(self):
        """不存在的工具应返回 None"""
        registry = ToolRegistry()
        assert registry.get_tool("nonexistent") is None

    def test_permission_user_cannot_access_admin(self, sample_tool, admin_tool):
        """普通用户不能获取管理员工具"""
        registry = ToolRegistry()
        registry.register(sample_tool, required_role="user")
        registry.register(admin_tool, required_role="admin")

        user_tool = registry.get_tool("admin_tool", user_role="user")
        assert user_tool is None

    def test_permission_admin_can_access_any(self, sample_tool, admin_tool):
        """管理员可以访问任何工具"""
        registry = ToolRegistry()
        registry.register(sample_tool, required_role="user")
        registry.register(admin_tool, required_role="admin")

        tool = registry.get_tool("admin_tool", user_role="admin")
        assert tool is not None

    def test_list_tools_by_role(self, sample_tool, admin_tool):
        """list_tools 应根据角色过滤"""
        registry = ToolRegistry()
        registry.register(sample_tool, required_role="user")
        registry.register(admin_tool, required_role="admin")

        user_tools = registry.list_tools(user_role="user")
        assert len(user_tools) == 1
        assert user_tools[0]["name"] == "sample"

        admin_tools = registry.list_tools(user_role="admin")
        assert len(admin_tools) == 2

    def test_unregister(self, sample_tool):
        """注销后工具不再可用"""
        registry = ToolRegistry()
        registry.register(sample_tool)
        registry.unregister("sample")
        assert "sample" not in registry

    def test_clear(self, sample_tool, admin_tool):
        """清空后无工具"""
        registry = ToolRegistry()
        registry.register(sample_tool)
        registry.register(admin_tool)
        registry.clear()
        assert len(registry) == 0

    def test_singleton(self):
        """ToolRegistry 应为单例"""
        r1 = ToolRegistry()
        r2 = ToolRegistry()
        assert r1 is r2


# ═══════════════════════════════════════════
# SessionManager 测试
# ═══════════════════════════════════════════

class TestSessionData:
    """会话数据测试"""

    def test_touch_updates_time(self):
        """touch 应更新 last_active"""
        data = SessionData()
        old = data.last_active
        data.touch()
        assert data.last_active >= old

    def test_is_expired_true(self):
        """超时会话应判定为过期"""
        data = SessionData()
        old_time = datetime.now() - timedelta(minutes=60)
        data.last_active = old_time
        assert data.is_expired(ttl_minutes=30) is True

    def test_is_expired_false(self):
        """未超时会话应判定为未过期"""
        data = SessionData()
        data.last_active = datetime.now()
        assert data.is_expired(ttl_minutes=30) is False


class TestSessionManager:
    """会话管理器测试"""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """每个测试后重置单例"""
        mgr = SessionManager()
        mgr._sessions.clear()
        # 清空数据库（使用临时数据库避免影响实际数据）
        with patch.object(mgr, "_db_path", ":memory:"):
            mgr._init_db()
        yield

    @patch.object(SessionManager, "_start_cleanup_thread", return_value=None)
    @patch.object(SessionManager, "_restore_sessions", return_value=None)
    @patch.object(SessionManager, "_init_db", return_value=None)
    def test_create_session(self, mock_db, mock_restore, mock_cleanup):
        """创建会话应返回非空 session_id"""
        mgr = SessionManager()
        session_id = mgr.create_session()
        assert session_id is not None
        assert len(session_id) == 8  # uuid4 hex[:8]

    @patch.object(SessionManager, "_start_cleanup_thread", return_value=None)
    @patch.object(SessionManager, "_restore_sessions", return_value=None)
    @patch.object(SessionManager, "_init_db", return_value=None)
    def test_add_and_get_messages(self, mock_db, mock_restore, mock_cleanup):
        """添加消息后应能读取"""
        mgr = SessionManager()
        session_id = mgr.create_session()
        mgr.add_message(session_id, "user", "你好")
        mgr.add_message(session_id, "assistant", "你好！有什么可以帮助你的？")

        messages = mgr.get_messages(session_id)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    @patch.object(SessionManager, "_start_cleanup_thread", return_value=None)
    @patch.object(SessionManager, "_restore_sessions", return_value=None)
    @patch.object(SessionManager, "_init_db", return_value=None)
    def test_get_messages_nonexistent(self, mock_db, mock_restore, mock_cleanup):
        """不存在的会话应返回空列表"""
        mgr = SessionManager()
        messages = mgr.get_messages("nonexistent")
        assert messages == []

    @patch.object(SessionManager, "_start_cleanup_thread", return_value=None)
    @patch.object(SessionManager, "_restore_sessions", return_value=None)
    @patch.object(SessionManager, "_init_db", return_value=None)
    def test_add_pair(self, mock_db, mock_restore, mock_cleanup):
        """add_pair 应同时添加两条消息"""
        mgr = SessionManager()
        session_id = mgr.create_session()
        mgr.add_pair(session_id, "问", "答")
        assert len(mgr.get_messages(session_id)) == 2

    @patch.object(SessionManager, "_start_cleanup_thread", return_value=None)
    @patch.object(SessionManager, "_restore_sessions", return_value=None)
    @patch.object(SessionManager, "_init_db", return_value=None)
    def test_get_recent(self, mock_db, mock_restore, mock_cleanup):
        """get_recent 应返回指定轮次的消息"""
        mgr = SessionManager()
        session_id = mgr.create_session()
        for i in range(5):
            mgr.add_pair(session_id, f"q{i}", f"a{i}")
        recent = mgr.get_recent(session_id, rounds=2)
        assert len(recent) == 4  # 2 rounds × 2 messages

    @patch.object(SessionManager, "_start_cleanup_thread", return_value=None)
    @patch.object(SessionManager, "_restore_sessions", return_value=None)
    @patch.object(SessionManager, "_init_db", return_value=None)
    def test_clear_session(self, mock_db, mock_restore, mock_cleanup):
        """清除会话后应不能获取消息"""
        mgr = SessionManager()
        session_id = mgr.create_session()
        mgr.add_message(session_id, "user", "hi")
        mgr.clear_session(session_id)
        assert mgr.get_messages(session_id) == []

    @patch.object(SessionManager, "_start_cleanup_thread", return_value=None)
    @patch.object(SessionManager, "_restore_sessions", return_value=None)
    @patch.object(SessionManager, "_init_db", return_value=None)
    def test_session_count(self, mock_db, mock_restore, mock_cleanup):
        """session_count 应返回正确数量"""
        mgr = SessionManager()
        assert mgr.session_count == 0
        mgr.create_session()
        mgr.create_session()
        assert mgr.session_count == 2
