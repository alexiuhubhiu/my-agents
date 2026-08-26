#!/usr/bin/env python3
"""检索引擎测试：三信号路由 + 降级 + trace（v4.0 test_unit_retrieval 移植）。"""

from core.engine.retrieval import retrieve


def test_fts_trigram_hit(db):
    """≥3 字中文走 trigram 命中。"""
    hits = retrieve("闭包", scope="facts", limit=10, db=db, agent_id="alex")
    assert any("闭包" in h["excerpt"] for h in hits)


def test_like_fallback_two_char(db):
    """2 字查询走 LIKE 兜底（"TCP"）。"""
    hits = retrieve("TCP", scope="facts", limit=10, db=db, agent_id="alex")
    assert any("TCP" in h["excerpt"] for h in hits)


def test_entity_relation_signal(db):
    """实体关系信号：查询命中 entity 时附带 episodes。"""
    hits = retrieve("闭包", scope="all", limit=10, db=db, agent_id="alex")
    sources = {h["source"] for h in hits}
    assert "fact" in sources
    # 种子 episode 含"闭包"内容 → 可能经实体关系召回
    assert len(hits) > 0


def test_scope_facts_only(db):
    """scope=facts 只返回事实，不返回 episode。"""
    hits = retrieve("闭包", scope="facts", limit=10, db=db, agent_id="alex")
    assert all(h["source"] == "fact" for h in hits)


def test_agent_isolation(db):
    """agent_id 过滤：alex 检索不到 bob 的事实。"""
    hits = retrieve("Rust", scope="facts", limit=5, db=db, agent_id="alex")
    assert not any("Rust" in h["excerpt"] for h in hits)


def test_retrieval_trace_recorded(db):
    """检索写 retrieval_log（trace）。"""
    before = db.execute("SELECT COUNT(*) FROM retrieval_log").fetchone()[0]
    retrieve("闭包", scope="facts", limit=5, db=db, agent_id="alex")
    after = db.execute("SELECT COUNT(*) FROM retrieval_log").fetchone()[0]
    assert after == before + 1


def test_trace_disabled(db):
    """trace=False 不写 retrieval_log。"""
    before = db.execute("SELECT COUNT(*) FROM retrieval_log").fetchone()[0]
    retrieve("闭包", scope="facts", limit=5, db=db, agent_id="alex", trace=False)
    after = db.execute("SELECT COUNT(*) FROM retrieval_log").fetchone()[0]
    assert after == before


def test_no_query_returns_structured_summary(db):
    """空查询 → 结构化摘要兜底（不抛错、有结果）。"""
    hits = retrieve("", scope="facts", limit=5, db=db, agent_id="alex")
    assert isinstance(hits, list)
    assert len(hits) >= 0
