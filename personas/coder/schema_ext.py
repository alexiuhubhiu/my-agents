#!/usr/bin/env python3
"""
personas.coder.schema_ext — 编程人设专属 Schema 扩展（coder_ 前缀）
====================================================================
与导师人设完全不同的领域表：任务清单 + 代码审查记录。
"""

from core.manifest import ExtColumn

# 对 agent_state 的扩展列（编程语境）
EXT_COLUMNS: list[ExtColumn] = [
    ExtColumn("agent_state", "coder_active_repo", "TEXT DEFAULT ''"),
    ExtColumn("agent_state", "coder_open_tasks", "INTEGER DEFAULT 0"),
]

# 专属表（coder_ 前缀，registry 前缀守卫校验）
EXT_TABLES = """
-- 编程任务清单
CREATE TABLE IF NOT EXISTS coder_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT DEFAULT '',
    repo            TEXT DEFAULT '',
    priority        TEXT DEFAULT 'medium',      -- high|medium|low
    status          TEXT DEFAULT 'todo',        -- todo|doing|done|cancelled
    created_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT,
    UNIQUE(agent_id, title)
);
CREATE INDEX IF NOT EXISTS idx_ct_status ON coder_tasks(agent_id, status);

-- 代码审查记录
CREATE TABLE IF NOT EXISTS coder_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    repo            TEXT DEFAULT '',
    file_path       TEXT DEFAULT '',
    review_type     TEXT DEFAULT 'self',        -- self|peer|ai
    issues_found    INTEGER DEFAULT 0,
    issues_fixed    INTEGER DEFAULT 0,
    notes           TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now'))
);
"""
