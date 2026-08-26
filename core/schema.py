#!/usr/bin/env python3
"""
core.schema — 记忆底层 Schema 单一来源（通用层）
==================================================
只包含**所有工作人设共需**的基础表。任何领域专属字段/表
一律放 personas/<name>/schema_ext.py，经 registry 合并应用。

表前缀约定：
- 基础表（本文件）          ：无前缀，如 sessions / memory_facts
- 人设扩展表（schema_ext）  ：带 <persona>_ 前缀，如 tutor_learning_progress
- 人设扩展列（schema_ext）  ：带 <persona>_ 列名前缀，如 tutor_mood

设计要点：
1. agent_state 泛化原 student_state —— 只保留通用工作状态
   （active_persona / state_json / version 乐观锁），教学专属列下沉到 tutor。
2. 六张通用记忆表 + 一张观测表，覆盖五层记忆模型中最通用的四层：
   情节(sessions/episodes) / 语义(memory_facts) / 核心(core_memory) /
   程序性(evolution_events 的进化痕迹) + 工作记忆(agent_state)。
3. 全部表带 agent_id（多租户 + 多人设切换的隔离基础）。
"""

CORE_SCHEMA_SQL = """
-- ============================================================
-- my_agents core v1.0 — 基础 Schema（领域无关）
-- ============================================================

-- ── 1. 通用工作状态（单行/agent，泛化原 student_state）──
--     领域专属状态一律经扩展列（tutor_mood 等）追加，见 personas/*/schema_ext.py
CREATE TABLE IF NOT EXISTS agent_state (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id          TEXT NOT NULL UNIQUE,          -- 人设实例标识（如 alex）
    active_persona    TEXT NOT NULL DEFAULT '',      -- 当前激活的工作人设
    -- 通用工作状态（JSON，领域无关）
    current_task      TEXT NOT NULL DEFAULT '',      -- 当前任务/主题
    turn_count        INTEGER NOT NULL DEFAULT 0,
    session_count     INTEGER NOT NULL DEFAULT 0,
    last_session_at   TEXT,
    ritual_state      TEXT NOT NULL DEFAULT 'IDLE',  -- 通用仪式状态机（如 STARTED/CLOSED）
    state_json        TEXT NOT NULL DEFAULT '{}',    -- 人设自由扩展的轻量状态
    -- 元数据
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    version           INTEGER NOT NULL DEFAULT 1     -- 乐观锁（PATCH 时校验）
);

-- ── 2. 会话表（情节记忆容器）──
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,                    -- 会话 UUID（start_session 生成）
    agent_id    TEXT NOT NULL,
    persona     TEXT NOT NULL DEFAULT '',            -- 归属人设（切换后仍可回溯）
    subject     TEXT DEFAULT '',
    topic       TEXT DEFAULT '',
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at    TEXT,
    turn_count  INTEGER DEFAULT 0,
    summary     TEXT DEFAULT '',
    status      TEXT DEFAULT 'active'                -- active | completed
);
CREATE INDEX IF NOT EXISTS idx_sess_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sess_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sess_agent ON sessions(agent_id, persona);

-- ── 3. 情节（对话回合）表 ──
CREATE TABLE IF NOT EXISTS episodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    turn_no     INTEGER NOT NULL DEFAULT 0,
    role        TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content     TEXT NOT NULL,
    topic       TEXT DEFAULT '',
    tokens_est  INTEGER DEFAULT 0,
    embedding   BLOB DEFAULT NULL,                   -- P2 预留：语义向量（默认不写）
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_ep_session ON episodes(session_id);
CREATE INDEX IF NOT EXISTS idx_ep_session_turn ON episodes(session_id, turn_no);
CREATE INDEX IF NOT EXISTS idx_ep_created ON episodes(created_at DESC);

-- ── 4. 核心记忆块（persona_profile / current_goals / user_preferences 等）──
CREATE TABLE IF NOT EXISTS core_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    block_key   TEXT NOT NULL,                       -- persona_profile|current_goals|user_preferences|...
    block_value TEXT NOT NULL,
    priority    INTEGER DEFAULT 5,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    version     INTEGER DEFAULT 1,
    UNIQUE(agent_id, block_key)
);

-- ── 5. 语义事实表（主动蒸馏落点，领域无关）──
CREATE TABLE IF NOT EXISTS memory_facts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id          TEXT NOT NULL,
    persona           TEXT NOT NULL DEFAULT '',      -- 事实来源人设（跨人设检索可过滤）
    subject           TEXT DEFAULT '',               -- 科目/主题域（检索按科目过滤，v4.0 兼容）
    entity            TEXT NOT NULL,                 -- 实体/主题词
    fact              TEXT NOT NULL,                 -- 事实陈述
    fact_type         TEXT DEFAULT 'general',        -- general|preference|mistake|strength|goal|habit
    importance        REAL DEFAULT 0.5,              -- 0..1，重排依据
    confidence        REAL DEFAULT 0.8,
    source_episode_id INTEGER,
    last_confirmed_at TEXT NOT NULL DEFAULT (datetime('now')),
    first_seen_at     TEXT NOT NULL DEFAULT (datetime('now')),
    status            TEXT DEFAULT 'active',         -- active|deprecated|conflict
    version           INTEGER DEFAULT 1,
    UNIQUE(agent_id, entity, fact)                   -- upsert 冲突键（含 agent 隔离）
);
CREATE INDEX IF NOT EXISTS idx_mf_entity ON memory_facts(entity);
CREATE INDEX IF NOT EXISTS idx_mf_subject ON memory_facts(subject);
CREATE INDEX IF NOT EXISTS idx_mf_agent_status ON memory_facts(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_mf_persona ON memory_facts(persona);
CREATE INDEX IF NOT EXISTS idx_mf_importance ON memory_facts(importance DESC);

-- ── 6. 进化事件日志（不可变，领域无关框架层）──
CREATE TABLE IF NOT EXISTS evolution_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id            TEXT NOT NULL DEFAULT '',
    event_type          TEXT NOT NULL,               -- 建议带 persona 前缀：tutor_c1 / tutor_c2 ...
    capability          TEXT NOT NULL,
    target_table        TEXT DEFAULT '',
    target_id           INTEGER,
    change_before       TEXT DEFAULT '{}',
    change_after        TEXT DEFAULT '{}',
    confidence          REAL NOT NULL DEFAULT 0.0,
    reason              TEXT NOT NULL DEFAULT '',
    applied             BOOLEAN NOT NULL DEFAULT 0,
    reverted            BOOLEAN NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    session_id          TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ee_type ON evolution_events(event_type);
CREATE INDEX IF NOT EXISTS idx_ee_applied ON evolution_events(applied);
CREATE INDEX IF NOT EXISTS idx_ee_created ON evolution_events(created_at);

-- ── 7. 观测表（检索 trace）──
CREATE TABLE IF NOT EXISTS retrieval_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    query       TEXT DEFAULT '',
    agent_id    TEXT DEFAULT '',
    persona     TEXT DEFAULT '',
    signals_used TEXT DEFAULT '[]',
    hits        INTEGER DEFAULT 0,
    latency_ms  REAL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_rl_ts ON retrieval_log(ts DESC);

-- ============================================================
-- 全文检索虚拟表（trigram，中文子串匹配）
-- ============================================================
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    entity, fact, content=memory_facts, content_rowid=id, tokenize='trigram'
);
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    content, content=episodes, content_rowid=id, tokenize='trigram'
);

-- FTS 同步触发器 — facts_fts
CREATE TRIGGER IF NOT EXISTS facts_fts_ai AFTER INSERT ON memory_facts BEGIN
    INSERT INTO facts_fts(rowid, entity, fact) VALUES (new.id, new.entity, new.fact);
END;
CREATE TRIGGER IF NOT EXISTS facts_fts_ad AFTER DELETE ON memory_facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, entity, fact) VALUES ('delete', old.id, old.entity, old.fact);
END;
CREATE TRIGGER IF NOT EXISTS facts_fts_au AFTER UPDATE ON memory_facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, entity, fact) VALUES ('delete', old.id, old.entity, old.fact);
    INSERT INTO facts_fts(rowid, entity, fact) VALUES (new.id, new.entity, new.fact);
END;

-- FTS 同步触发器 — episodes_fts
CREATE TRIGGER IF NOT EXISTS episodes_fts_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS episodes_fts_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS episodes_fts_au AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO episodes_fts(rowid, content) VALUES (new.id, new.content);
END;
"""

# 基础表清单（供 health_check / registry 校验）
CORE_TABLES = [
    "agent_state",
    "sessions",
    "episodes",
    "core_memory",
    "memory_facts",
    "evolution_events",
]

# 观测表（不参与行数统计）
OBSERVATION_TABLES = ["retrieval_log"]

# FTS 虚拟表
FTS_TABLES = ["facts_fts", "episodes_fts"]
