"""
会话管理器

功能：
- 创建会话（Session）
- 读写消息（Messages），同步持久化到 SQLite
- 会话裁剪（保留最近 N 轮）
- 会话过期（TTL）与自动清理
- 内存缓存 + SQLite 双重存储，服务重启后可恢复
"""

import uuid
import json
import sqlite3
import threading
import time
import os
from typing import List, Optional
from datetime import datetime, timedelta
from contextlib import contextmanager

from utils.logger_handler import logger
from utils.config_handler import agent_conf


class SessionData:
    """单个会话的数据与元信息"""

    def __init__(self, messages: list = None, created_at: str = None, last_active: str = None):
        self.messages: list = messages or []
        self.created_at: datetime = self._parse_time(created_at) if created_at else datetime.now()
        self.last_active: datetime = self._parse_time(last_active) if last_active else datetime.now()

    def touch(self):
        self.last_active = datetime.now()

    def is_expired(self, ttl_minutes: int) -> bool:
        return datetime.now() - self.last_active > timedelta(minutes=ttl_minutes)

    @staticmethod
    def _parse_time(time_str: str) -> datetime:
        try:
            return datetime.fromisoformat(time_str)
        except (ValueError, TypeError):
            return datetime.now()


class SessionManager:
    """会话管理器（单例 + 内存缓存 + SQLite 持久化）"""

    _instance = None
    _sessions: dict[str, SessionData] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 配置
        session_conf = agent_conf.get("session", {})
        self._max_rounds: int = session_conf.get("max_rounds", 20)
        self._ttl_minutes: int = session_conf.get("ttl_minutes", 30)
        cleanup_interval: int = session_conf.get("cleanup_interval", 60)

        # 线程锁
        self._lock = threading.Lock()

        # 初始化 SQLite
        self._db_path = "data/sessions.db"
        self._init_db()

        # 启动时从 SQLite 恢复活跃会话
        self._restore_sessions()

        # 后台清理线程
        self._start_cleanup_thread(cleanup_interval)

        logger.info(
            f"[SessionManager] 初始化完成: max_rounds={self._max_rounds}, "
            f"ttl={self._ttl_minutes}min, db={self._db_path}"
        )

    # ────────────── SQLite 持久化 ──────────────

    def _init_db(self):
        """创建数据库表"""
        db_dir = os.path.dirname(self._db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    messages TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_active TEXT NOT NULL
                )
            """)

    @contextmanager
    def _get_conn(self):
        """获取 SQLite 连接（上下文管理器，自动提交关闭）"""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _save_to_db(self, session_id: str, data: SessionData):
        """写入 SQLite（插入或替换）"""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sessions (session_id, messages, created_at, last_active)
                   VALUES (?, ?, ?, ?)""",
                (
                    session_id,
                    json.dumps(data.messages, ensure_ascii=False),
                    data.created_at.isoformat(),
                    data.last_active.isoformat(),
                )
            )

    def _delete_from_db(self, session_id: str):
        """从 SQLite 删除会话"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def _restore_sessions(self):
        """从 SQLite 恢复所有未过期的会话到内存"""
        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT session_id, messages, created_at, last_active FROM sessions"
                ).fetchall()

            restored = 0
            for session_id, messages_json, created_at, last_active in rows:
                messages = json.loads(messages_json)
                data = SessionData(messages=messages, created_at=created_at, last_active=last_active)
                if data.is_expired(self._ttl_minutes):
                    self._delete_from_db(session_id)
                    continue
                self._sessions[session_id] = data
                restored += 1

            if restored:
                logger.info(f"[SessionManager] 从 SQLite 恢复了 {restored} 个会话")
        except Exception as e:
            logger.warning(f"[SessionManager] SQLite 恢复会话失败（首次运行？）: {e}")

    # ────────────── 核心 API ──────────────

    def create_session(self) -> str:
        session_id = uuid.uuid4().hex[:8]
        data = SessionData()
        with self._lock:
            self._sessions[session_id] = data
        self._save_to_db(session_id, data)
        logger.info(f"[SessionManager] 创建会话: {session_id}")
        return session_id

    def get_messages(self, session_id: str) -> list:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return []
        if session.is_expired(self._ttl_minutes):
            logger.info(f"[SessionManager] 会话 {session_id} 已过期，自动清理")
            self.clear_session(session_id)
            return []
        session.touch()
        return session.messages

    def add_message(self, session_id: str, role: str, content: str):
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = SessionData()
                self._sessions[session_id] = session
            session.touch()
            session.messages.append({
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            })
            self._trim(session)
        self._save_to_db(session_id, session)

    def add_pair(self, session_id: str, user_msg: str, assistant_msg: str):
        self.add_message(session_id, "user", user_msg)
        self.add_message(session_id, "assistant", assistant_msg)

    def get_recent(self, session_id: str, rounds: int = 10) -> list:
        messages = self.get_messages(session_id)
        return messages[-(rounds * 2):]

    def clear_session(self, session_id: str):
        with self._lock:
            self._sessions.pop(session_id, None)
        self._delete_from_db(session_id)

    def clear_expired_sessions(self) -> int:
        with self._lock:
            expired_ids = [
                sid for sid, session in self._sessions.items()
                if session.is_expired(self._ttl_minutes)
            ]
            for sid in expired_ids:
                self._sessions.pop(sid, None)
        for sid in expired_ids:
            self._delete_from_db(sid)
        if expired_ids:
            logger.info(f"[SessionManager] 清理了 {len(expired_ids)} 个过期会话")
        return len(expired_ids)

    # ────────────── 内部方法 ──────────────

    def _trim(self, session: SessionData):
        max_messages = self._max_rounds * 2
        if len(session.messages) > max_messages:
            session.messages = session.messages[-max_messages:]

    def _start_cleanup_thread(self, interval: int):
        def cleanup_loop():
            while True:
                time.sleep(interval)
                try:
                    self.clear_expired_sessions()
                except Exception as e:
                    logger.error(f"[SessionManager] 清理异常: {e}")
        thread = threading.Thread(target=cleanup_loop, daemon=True, name="session-cleanup")
        thread.start()

    @property
    def session_count(self) -> int:
        return len(self._sessions)


# 全局单例
session_manager = SessionManager()
