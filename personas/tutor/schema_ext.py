#!/usr/bin/env python3
"""
personas.tutor.schema_ext — 导师人设专属 Schema 扩展
======================================================
两类扩展（registry.apply_persona_schema 幂等应用）：
1. EXT_COLUMNS — 对 core.agent_state 追加教学专属列（tutor_ 前缀）
   （原 v4.0 student_state 的教学字段：情绪三轴 / 数字信号 / 课后密集区）
2. EXT_TABLES  — 教学专属表（tutor_ 前缀）：
   tutor_learning_progress / tutor_teaching_metrics / tutor_error_patterns
   / tutor_pitfall_triggers / tutor_teacher_knowledge / tutor_diary_entries

约定红线：表名必须带 tutor_ 前缀（registry 会守卫校验）。
"""

from core.manifest import ExtColumn

# ── 1. 对 agent_state 的扩展列（原 student_state 教学字段）──
EXT_COLUMNS: list[ExtColumn] = [
    # 情绪三轴
    ExtColumn("agent_state", "tutor_mood", "TEXT NOT NULL DEFAULT 'neutral'"),
    ExtColumn("agent_state", "tutor_energy", "INTEGER NOT NULL DEFAULT 7"),
    ExtColumn("agent_state", "tutor_focus", "REAL NOT NULL DEFAULT 0.6"),
    # 数字信号
    ExtColumn("agent_state", "tutor_ds_reply_interval_sec", "REAL DEFAULT 30.0"),
    ExtColumn("agent_state", "tutor_ds_code_paste_speed", "TEXT DEFAULT 'normal'"),
    ExtColumn("agent_state", "tutor_ds_consecutive_short_replies", "INTEGER DEFAULT 0"),
    ExtColumn("agent_state", "tutor_ds_question_frequency", "REAL DEFAULT 0.3"),
    ExtColumn("agent_state", "tutor_ds_flow_state", "TEXT DEFAULT 'neutral'"),
    ExtColumn("agent_state", "tutor_ds_total_questions", "INTEGER DEFAULT 0"),
    ExtColumn("agent_state", "tutor_ds_last_interaction_at", "TEXT DEFAULT NULL"),
    # 课后密集区
    ExtColumn("agent_state", "tutor_post_class_mode", "BOOLEAN DEFAULT 0"),
    ExtColumn("agent_state", "tutor_post_class_rounds_left", "INTEGER DEFAULT 0"),
]

# ── 2. 教学专属表 ──
EXT_TABLES = """
-- 学习进度（复习计划）
CREATE TABLE IF NOT EXISTS tutor_learning_progress (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    subject         TEXT NOT NULL,
    topic           TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'in_progress',
    mastery_level   INTEGER DEFAULT 0,
    first_seen_at   TEXT,
    last_reviewed_at TEXT,
    review_count    INTEGER DEFAULT 0,
    next_review_at  TEXT,
    extra_data      TEXT DEFAULT '{}',
    UNIQUE(agent_id, subject, topic)
);
CREATE INDEX IF NOT EXISTS idx_tlp_review ON tutor_learning_progress(status, next_review_at);

-- 教学指标（每节课）
CREATE TABLE IF NOT EXISTS tutor_teaching_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id            TEXT NOT NULL,
    session_id          TEXT DEFAULT '',
    session_date        TEXT NOT NULL,
    subject             TEXT NOT NULL,
    turns_total         INTEGER,
    hints_given         INTEGER,
    concepts_introduced INTEGER,
    mistakes_made       INTEGER,
    independence_pct    REAL,
    notes               TEXT DEFAULT ''
);

-- 错误模式（错题追踪）
CREATE TABLE IF NOT EXISTS tutor_error_patterns (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id            TEXT NOT NULL,
    pattern             TEXT NOT NULL,
    category            TEXT NOT NULL,
    root_cause          TEXT NOT NULL,
    subject             TEXT NOT NULL DEFAULT '',
    first_seen_at       TEXT,
    last_seen_at        TEXT,
    frequency_history   TEXT DEFAULT '[]',
    status              TEXT DEFAULT 'active',
    remedy              TEXT DEFAULT '',
    cross_subject_mappings TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_tep_status ON tutor_error_patterns(status);

-- 坑位预警触发器
CREATE TABLE IF NOT EXISTS tutor_pitfall_triggers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id            TEXT NOT NULL,
    name                TEXT NOT NULL,
    trigger_keywords    TEXT NOT NULL,
    context_pattern     TEXT NOT NULL,
    mandatory_action    TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'warning',
    cooldown_turns      INTEGER DEFAULT 10,
    last_triggered_at_turn INTEGER DEFAULT 0,
    active              BOOLEAN DEFAULT 1,
    applicable_subjects TEXT DEFAULT '[]'
);

-- 教学知识库
CREATE TABLE IF NOT EXISTS tutor_teacher_knowledge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,
    subject     TEXT DEFAULT '',
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    priority    INTEGER DEFAULT 5,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- 教学日记索引
CREATE TABLE IF NOT EXISTS tutor_diary_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    date        TEXT NOT NULL,
    filepath    TEXT NOT NULL,
    excerpt     TEXT,
    has_romance BOOLEAN DEFAULT 0,
    mood_summary TEXT DEFAULT '',
    UNIQUE(agent_id, date)
);
CREATE INDEX IF NOT EXISTS idx_tde_date ON tutor_diary_entries(date DESC);

-- ── 3. 教学专属全文检索（检索完整性：diary 摘要与知识库可被搜到）──
CREATE VIRTUAL TABLE IF NOT EXISTS tutor_diary_fts USING fts5(
    excerpt, content=tutor_diary_entries, content_rowid=id, tokenize='trigram'
);
CREATE VIRTUAL TABLE IF NOT EXISTS tutor_knowledge_fts USING fts5(
    title, content, content=tutor_teacher_knowledge, content_rowid=id, tokenize='trigram'
);

-- FTS 同步触发器 — tutor_diary_fts
CREATE TRIGGER IF NOT EXISTS tutor_diary_fts_ai AFTER INSERT ON tutor_diary_entries BEGIN
    INSERT INTO tutor_diary_fts(rowid, excerpt) VALUES (new.id, new.excerpt);
END;
CREATE TRIGGER IF NOT EXISTS tutor_diary_fts_ad AFTER DELETE ON tutor_diary_entries BEGIN
    INSERT INTO tutor_diary_fts(tutor_diary_fts, rowid, excerpt) VALUES ('delete', old.id, old.excerpt);
END;
CREATE TRIGGER IF NOT EXISTS tutor_diary_fts_au AFTER UPDATE ON tutor_diary_entries BEGIN
    INSERT INTO tutor_diary_fts(tutor_diary_fts, rowid, excerpt) VALUES ('delete', old.id, old.excerpt);
    INSERT INTO tutor_diary_fts(rowid, excerpt) VALUES (new.id, new.excerpt);
END;

-- FTS 同步触发器 — tutor_knowledge_fts
CREATE TRIGGER IF NOT EXISTS tutor_knowledge_fts_ai AFTER INSERT ON tutor_teacher_knowledge BEGIN
    INSERT INTO tutor_knowledge_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS tutor_knowledge_fts_ad AFTER DELETE ON tutor_teacher_knowledge BEGIN
    INSERT INTO tutor_knowledge_fts(tutor_knowledge_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS tutor_knowledge_fts_au AFTER UPDATE ON tutor_teacher_knowledge BEGIN
    INSERT INTO tutor_knowledge_fts(tutor_knowledge_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
    INSERT INTO tutor_knowledge_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
"""
