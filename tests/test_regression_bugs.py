#!/usr/bin/env python3
"""回归测试：5 个历史 bug 护栏（v4.0 test_regression_bugs 移植，表名/包路径适配）。"""

import sqlite3

import pytest


def test_r1_short_query_like_fallback(db):
    """R1: 2 字中文查询 trigram 不命中，LIKE 兜底必须召回。"""
    from core.engine.retrieval import retrieve

    hits = retrieve("闭包", scope="facts", limit=10, db=db, agent_id="alex")
    assert hits, "2 字查询应命中"
    assert any("闭包" in h["excerpt"] for h in hits)


def test_r2_fullwidth_question_count(api):
    """R2: 全角问号计入提问频率（record_interaction 计数）。"""
    from personas.tutor.tools.interaction import tool_record_interaction

    r = tool_record_interaction(api, {"agent_id": "alex", "user_message": "这是什么？怎么用？"})
    assert r["signals"]["questions_in_message"] == 2
    assert r["signals"]["question_frequency"] > 0


def test_r3_turn_no_ordering(api):
    """R3: 同一会话内 turn_no 按插入顺序递增。"""
    s = api.start_session("alex", "tutor", subject="t")
    sid = s["session_id"]
    api.log_episode(sid, "user", "第一问", agent_id="alex")
    api.log_episode(sid, "assistant", "第一答", agent_id="alex")
    rec = api.recall_episodes(session_id=sid)
    turns = [e["turn_no"] for e in rec["episodes"]]
    assert turns == [1, 2], f"turn_no 应递增，实际 {turns}"


def test_r4_agent_isolation(db):
    """R4: 多 agent 数据隔离（alex 检索不到 bob 的事实）。"""
    from core.engine.retrieval import retrieve

    hits_alex = retrieve("Rust", scope="facts", limit=5, db=db, agent_id="alex")
    assert not any("Rust" in h["excerpt"] for h in hits_alex)
    hits_bob = retrieve("Rust", scope="facts", limit=5, db=db, agent_id="bob")
    assert any("Rust" in h["excerpt"] for h in hits_bob)


def test_r5_index_exists(db):
    """R5: 关键索引存在（explain 不走全表扫描的关键依赖）。"""
    idx = {r[1] for r in db.execute("SELECT * FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_mf_agent_status" in idx
    assert "idx_ep_session_turn" in idx
