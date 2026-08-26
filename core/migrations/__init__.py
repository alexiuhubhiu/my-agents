#!/usr/bin/env python3
"""
core.migrations — 目录化数据库迁移（v4.0 框架平移）
====================================================
按 PRAGMA user_version 顺序执行迁移，全部幂等可重跑：
- CREATE TABLE / CREATE INDEX 均带 IF NOT EXISTS
- 需要守卫的迁移使用 module.migrate(conn) 而非裸 UP_SQL

用法:
    from core.migrations import apply_pending, SCHEMA_VERSION
    apply_pending(str(db_path))               # 应用未执行的迁移，返回最新版本号
    apply_pending(str(db_path), verify=True)  # 只读校验：返回当前 user_version

协议:
    - 每个迁移文件暴露 UP_SQL（幂等 DDL 字符串），或 migrate(conn)（需守卫的迁移）
    - 0001_core_init — core 基础表 + FTS + 索引（= core.schema.CORE_SCHEMA_SQL）
    - 人设扩展表（tutor_*）不在此管理——由 registry.apply_persona_schema 按人设加载时应用
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

# 当前 Schema 版本（= 最后一个迁移编号）
SCHEMA_VERSION = 1

# (user_version, 迁移模块名)，严格按依赖顺序
MIGRATIONS: list[tuple[int, str]] = [
    (1, "0001_core_init"),
]


def _open(db_path: str | Path) -> sqlite3.Connection:
    """打开连接：WAL + Row（与 core.db 一致的 PRAGMA 约定）。"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def apply_pending(db_path: str | Path, *, verify: bool = False) -> int:
    """按 user_version 顺序应用未执行的迁移，返回最终版本号。

    verify=True 时只读：返回当前 user_version，不执行任何写操作。
    """
    db_path = Path(db_path)
    conn = _open(db_path)
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if verify:
            return int(current)

        applied = int(current)
        for version, name in MIGRATIONS:
            if version <= applied:
                continue
            mod = importlib.import_module(f"core.migrations.{name}")
            if hasattr(mod, "migrate"):
                mod.migrate(conn)
            else:
                conn.executescript(mod.UP_SQL)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
            applied = version

        final = int(conn.execute("PRAGMA user_version").fetchone()[0])
        return final
    finally:
        conn.close()
