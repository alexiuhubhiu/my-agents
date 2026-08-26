#!/usr/bin/env python3
"""数据导入测试：import_v4_data 幂等 + 一致性 + persona 回填（用 fixture 旧库，不碰生产）。"""

import sqlite3
from pathlib import Path

import pytest

from core.schema import CORE_SCHEMA_SQL


def _build_old_db(path: Path) -> sqlite3.Connection:
    """构造一个迷你 v4.0 旧库（student_state + memory_facts + diary_entries 等）。"""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE student_state (id INTEGER PRIMARY KEY, mood TEXT, energy INTEGER, turn_count INTEGER);
        INSERT INTO student_state (id, mood, energy, turn_count) VALUES (1, 'good', 7, 12);
        CREATE TABLE memory_facts (id INTEGER PRIMARY KEY, entity TEXT, fact TEXT, importance REAL, confidence REAL, subject TEXT);
        INSERT INTO memory_facts (entity, fact, importance, confidence, subject) VALUES ('ISIS', '正在备考HCIE', 0.9, 0.8, 'hcie');
        CREATE TABLE learning_progress (id INTEGER PRIMARY KEY, subject TEXT, topic TEXT, status TEXT, mastery_level INTEGER);
        INSERT INTO learning_progress (subject, topic, status, mastery_level) VALUES ('hcie', '', 'in_progress', 60);
        CREATE TABLE sessions (id TEXT PRIMARY KEY, agent_id TEXT, subject TEXT, status TEXT);
        INSERT INTO sessions (id, agent_id, subject, status) VALUES ('s1', 'alex', 'hcie', 'closed');
        CREATE TABLE episodes (id INTEGER PRIMARY KEY, session_id TEXT, agent_id TEXT, turn_no INTEGER, role TEXT, content TEXT);
        INSERT INTO episodes (session_id, agent_id, turn_no, role, content) VALUES ('s1', 'alex', 1, 'user', 'ISIS是什么');
        CREATE TABLE diary_entries (date TEXT PRIMARY KEY, filepath TEXT, excerpt TEXT);
        INSERT INTO diary_entries (date, filepath, excerpt) VALUES ('2026-08-01', 'diary/2026-08-01.md', '今天学ISIS');
        CREATE TABLE evolution_events (id INTEGER PRIMARY KEY, event_type TEXT, capability TEXT, target_table TEXT, target_id INTEGER, change_before TEXT, change_after TEXT, confidence REAL, reason TEXT, applied INTEGER, reverted INTEGER, created_at TEXT, session_id TEXT);
        CREATE TABLE retrieval_log (id INTEGER PRIMARY KEY, ts TEXT, query TEXT, agent_id TEXT, signals_used TEXT, hits INTEGER, latency_ms REAL);
        """
    )
    conn.commit()
    return conn


def test_import_v4_data_end_to_end(tmp_path, monkeypatch):
    """导入：行数一致 + persona 回填 + diary 复制 + 幂等。"""
    sys_path_fix(tmp_path)
    monkeypatch.setenv("AGENTS_BACKUP_DIR", str(tmp_path / "backups"))  # 备份写 tmp，不碰生产

    old_db = tmp_path / "old_tutor.db"
    _build_old_db(old_db).close()

    new_db = tmp_path / "agents.db"
    # 先建新库 schema
    conn = sqlite3.connect(str(new_db))
    conn.executescript(CORE_SCHEMA_SQL)
    from core import registry
    from personas.tutor import schema_ext as tutor_ext

    registry.apply_persona_schema(tutor_ext, "tutor", conn)
    conn.close()

    # 日记目录
    old_diary = tmp_path / "old_diary"
    old_diary.mkdir()
    (old_diary / "2026-08-01.md").write_text("今天学ISIS", encoding="utf-8")

    import importlib
    import scripts.import_v4_data as imp

    result = imp.run_import(old_db, new_db, force=True, src_diary=old_diary, diary_dst=tmp_path / "diary")

    conn = sqlite3.connect(str(new_db))
    conn.row_factory = sqlite3.Row
    # 1) 行数一致
    assert conn.execute("SELECT COUNT(*) FROM agent_state").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tutor_learning_progress").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tutor_diary_entries").fetchone()[0] == 1
    # 2) persona 回填
    mf = conn.execute("SELECT persona, agent_id FROM memory_facts").fetchone()
    assert mf["persona"] == "tutor"
    assert mf["agent_id"] == "alex"
    # 3) agent_state 教学列映射
    st = conn.execute("SELECT tutor_mood, active_persona FROM agent_state").fetchone()
    assert st["tutor_mood"] == "good"
    assert st["active_persona"] == "tutor"
    # 4) diary filepath 回写
    de = conn.execute("SELECT filepath FROM tutor_diary_entries").fetchone()
    assert de["filepath"] == "diary/alex/2026-08-01.md"
    conn.close()

    # 5) 幂等：再次导入不产生重复
    result2 = imp.run_import(old_db, new_db, force=True, src_diary=old_diary)
    conn = sqlite3.connect(str(new_db))
    assert conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    conn.close()


def sys_path_fix(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
