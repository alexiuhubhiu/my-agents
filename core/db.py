#!/usr/bin/env python3
"""
core.db — 连接单例（WAL + Row）
================================
AGENTS_DB_PATH 可被环境变量覆盖（测试隔离 / 多库并存）。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# 默认数据库：D:\my_agents\data\agents.db（可用 AGENTS_DB_PATH 覆盖）
_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "agents.db"
AGENTS_DB_PATH = Path(os.environ.get("AGENTS_DB_PATH", str(_DEFAULT_DB)))

_conn: sqlite3.Connection | None = None


def get_db(path: str | Path | None = None) -> sqlite3.Connection:
    """返回进程级单例连接（WAL 模式 + Row 工厂）。"""
    global _conn
    if _conn is not None:
        return _conn
    db_path = Path(path) if path else AGENTS_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(db_path), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def close_db() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def reset_conn() -> None:
    """测试用：丢弃单例（不关闭底层文件）。"""
    global _conn
    _conn = None
