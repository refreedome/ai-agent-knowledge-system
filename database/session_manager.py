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
from .compaction import compaction_service


class SessionData:
    """单个会话的数据与元信息"""

    def __init__(self, messages: list = None, created_at: str = None, last_active: str = None,
                 user_id: str = "default", summary: str = "", compacted_count: int = 0):
        self.messages: list = messages or []
        self.user_id: str = user_id
        self.summary: str = summary or ""              # 被挤出窗口的历史压缩摘要（Compaction）
        self.compacted_count: int = compacted_count     # 已进入摘要的消息条数（增量压缩游标）
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
        # 存储上限（比窗口大得多）：压缩需要「被挤出的原文」做素材，硬丢太早会没得压
        self._max_stored_rounds: int = session_conf.get("max_stored_rounds", 100)
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
                    last_active TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    summary TEXT NOT NULL DEFAULT '',
                    compacted_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            # 兼容旧库：缺列则补充（表结构随功能演进的迁移）
            cols = [row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()]
            if "user_id" not in cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
            if "summary" not in cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
            if "compacted_count" not in cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN compacted_count INTEGER NOT NULL DEFAULT 0")
            # 用户维度查询索引（按用户 + 最近活跃查会话）
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, last_active)"
            )

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
                """INSERT OR REPLACE INTO sessions
                   (session_id, messages, created_at, last_active, user_id, summary, compacted_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    json.dumps(data.messages, ensure_ascii=False),
                    data.created_at.isoformat(),
                    data.last_active.isoformat(),
                    getattr(data, "user_id", "default"),
                    getattr(data, "summary", ""),
                    getattr(data, "compacted_count", 0),
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
                    "SELECT session_id, messages, created_at, last_active, user_id, summary, compacted_count "
                    "FROM sessions"
                ).fetchall()

            restored = 0
            for session_id, messages_json, created_at, last_active, user_id, summary, compacted_count in rows:
                messages = json.loads(messages_json)
                data = SessionData(
                    messages=messages, created_at=created_at,
                    last_active=last_active, user_id=user_id or "default",
                    summary=summary or "", compacted_count=compacted_count or 0,
                )
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

    def create_session(self, user_id: str = "default") -> str:
        session_id = uuid.uuid4().hex[:8]
        data = SessionData(user_id=user_id)
        with self._lock:
            self._sessions[session_id] = data
        self._save_to_db(session_id, data)
        logger.info(f"[SessionManager] 创建会话: {session_id} (user={user_id})")
        return session_id

    def list_sessions(self, user_id: str = None) -> list:
        """
        会话概要列表（可按用户过滤），按最近活跃倒序

        多用户隔离：user_id 为空时返回全部（管理员视角），
        传入 user_id 时只返回该用户自己的会话。
        """
        with self._lock:
            items = list(self._sessions.items())

        result = []
        for sid, data in items:
            if user_id and getattr(data, "user_id", "default") != user_id:
                continue
            result.append({
                "session_id": sid,
                "user_id": getattr(data, "user_id", "default"),
                "message_count": len(data.messages),
                "created_at": data.created_at.isoformat(),
                "last_active": data.last_active.isoformat(),
            })
        result.sort(key=lambda x: x["last_active"], reverse=True)
        return result

    def get_owner(self, session_id: str) -> Optional[str]:
        """取会话归属用户（用于权限校验）；会话不存在返回 None"""
        with self._lock:
            data = self._sessions.get(session_id)
        return getattr(data, "user_id", None) if data else None

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

    def get_context_window(self, session_id: str, max_chars: int = None) -> list:
        """
        上下文窗口 = 【更早对话的压缩摘要】 + 窗口内的近期原文

        三层处理：
        - 第一层（轮数）：存储层由 `max_stored_rounds` 兜底，避免过早丢原文
        - 第二层（字符）：按总字符数从最旧开始裁剪，**始终保留最新消息**
        - 第三层（压缩 Compaction）：被挤出窗口的历史不再「硬丢」，而是**增量摘要**成
          一段文本，以 system 消息注入到窗口之前 —— 信息不丢，Token 还省

        返回：可直接拼进模型 messages 的列表
        """
        session = self._sessions.get(session_id)
        messages = self.get_messages(session_id)
        if max_chars is None:
            max_chars = agent_conf.get("session", {}).get("max_history_chars", 4000)

        # 1) 从最新往回累加，划出窗口
        total = 0
        kept = []
        for m in reversed(messages):
            total += len(m.get("content", ""))
            if total > max_chars and kept:
                break
            kept.append(m)
        kept.reverse()

        # 2) 窗口之外的部分 → 增量压缩（只压「新被挤出」的，不重复压已压过的）
        dropped_end = len(messages) - len(kept)
        prefix = []
        if session is not None and compaction_service.enabled and dropped_end > 0:
            newly_dropped = messages[session.compacted_count: dropped_end]
            if newly_dropped:
                session.summary = compaction_service.compact(newly_dropped, session.summary)
                session.compacted_count = dropped_end
                self._save_to_db(session_id, session)
            if session.summary:
                prefix.append({
                    "role": "system",
                    "content": f"【更早对话的摘要（已压缩，非原文）】{session.summary}",
                })

        return prefix + kept

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
        """存储层硬上限（比上下文窗口大得多，给压缩留素材）"""
        max_messages = self._max_stored_rounds * 2
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
