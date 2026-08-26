#!/usr/bin/env python3
"""
core.engine.retrieval — 三信号记忆检索路由（领域无关，v4.0 完整平移）
=====================================================================
检索路由（多信号融合，纯 SQLite 原生能力，零 embedding）：
  结构化过滤 → FTS5 trigram MATCH(≥3字) → 短词 LIKE 兜底(<3字或trigram未命中)
  → 实体关系信号(图连通性) → 元数据重排(bm25 + 类型权重 + 重要度 + 时间近因)

任何一层失败自动降级到结构化摘要，绝不抛错 / 丢数据。

改造点（相对 v4.0）：
- 只检索 core 表（memory_facts / episodes）；diary/knowledge 检索由
  personas/tutor/hooks.py 经 tutor_diary_fts / tutor_knowledge_fts 补齐
  （core 绝不 import personas，领域内容由上层钩子注入）。
- scope 取值收窄为 all / facts / episodes（旧 diary/knowledge 值交给上层钩子）。

本模块不出现任何业务域常量；schema 表名（memory_facts / episodes）是数据层事实。
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from typing import Any

from ..db import get_db

# 类型权重(重排用): 语义事实 > 情节
TYPE_WEIGHT = {"fact": 3, "episode": 2}

# 检索 trace 开关（测试或性能对比时可关闭）
_TRACE_ENABLED = True


def _get_conn(db=None):
    """获取数据库连接；允许调用方传入，否则懒加载 db 单例。"""
    return db if db is not None else get_db()


# ────────────────────────────────────────────────────────────
#  1 结构化字段过滤（始终可用，最稳）
# ────────────────────────────────────────────────────────────


def _structured_filter(subject, scope, db, agent_id: str = "alex"):
    """返回语义事实(memory_facts)候选，按 subject 约束(可多租户过滤)。"""
    rows = []
    if scope in ("all", "facts"):
        try:
            sql = (
                "SELECT id, subject, entity, fact, fact_type, importance, confidence, status "
                "FROM memory_facts WHERE status='active' AND agent_id=?"
            )
            args: list[Any] = [agent_id]
            if subject:
                sql += " AND (subject=? OR subject='')"
                args.append(subject)
            for r in db.execute(sql, args).fetchall():
                rows.append(
                    {
                        "source": "fact",
                        "id": r["id"],
                        "title": f"{r['entity']}: {r['fact']}",
                        "excerpt": r["fact"],
                        "date": None,
                        "importance": float(r["importance"] or 0.5),
                        "type_weight": TYPE_WEIGHT["fact"],
                        "score": 0.0,
                    }
                )
        except sqlite3.Error:
            return []  # memory_facts 尚未建表 → 无事实候选
    return rows


# ────────────────────────────────────────────────────────────
#  2 trigram MATCH（中文 ≥3 字，facts_fts / episodes_fts）
# ────────────────────────────────────────────────────────────


def _fts_trigram_match(query, subject, scope, db, limit, agent_id: str = "alex"):
    """对 facts_fts / episodes_fts 做 trigram MATCH；异常时返回空(交 LIKE 兜底)。"""
    hits = []
    q = '"' + query.replace('"', '""') + '"'
    try:
        if scope in ("all", "facts"):
            for r in db.execute(
                """
SELECT m.id, m.entity, m.fact, m.importance, m.fact_type, bm25(facts_fts) AS rank
FROM facts_fts f JOIN memory_facts m ON m.id = f.rowid
WHERE facts_fts MATCH ? AND m.agent_id=? AND m.status='active'
ORDER BY rank
LIMIT ?
""",
                (q, agent_id, limit),
            ).fetchall():
                hits.append(
                    {
                        "source": "fact",
                        "id": r["id"],
                        "title": f"{r['entity']}: {r['fact']}",
                        "excerpt": r["fact"],
                        "date": None,
                        "importance": float(r["importance"] or 0.5),
                        "type_weight": TYPE_WEIGHT["fact"],
                        "score": float(r["rank"]),
                    }
                )
        if scope in ("all", "episodes"):
            for r in db.execute(
                """
SELECT e.id, e.session_id, e.role, e.content, e.created_at, bm25(episodes_fts) AS rank
FROM episodes_fts f JOIN episodes e ON e.id = f.rowid
WHERE episodes_fts MATCH ? AND e.agent_id=?
ORDER BY rank
LIMIT ?
""",
                (q, agent_id, limit),
            ).fetchall():
                hits.append(
                    {
                        "source": "episode",
                        "id": r["id"],
                        "title": f"[{r['role']}] " + (r["content"] or "")[:40],
                        "excerpt": (r["content"] or "")[:200].replace("\n", " "),
                        "date": str(r["created_at"])[:10] if r["created_at"] else None,
                        "importance": 0.5,
                        "type_weight": TYPE_WEIGHT["episode"],
                        "score": float(r["rank"]),
                    }
                )
    except sqlite3.Error:
        return []  # trigram 异常(如 tokenizer 不支持) → 空,交给 LIKE 兜底
    return hits


# ────────────────────────────────────────────────────────────
#  3 短词 LIKE 兜底（<3 字 或 trigram 未命中）
# ────────────────────────────────────────────────────────────


def _like_fallback(query, subject, scope, db, limit, agent_id: str = "alex"):
    """2 字中文(如"算法""闭包")trigram 不命中，必须走 LIKE 兜底。"""
    hits = []
    like = f"%{query}%"
    try:
        if scope in ("all", "facts"):
            for r in db.execute(
                """
SELECT id, entity, fact, importance, fact_type FROM memory_facts
WHERE agent_id=? AND status='active'
  AND (entity LIKE ? ESCAPE '\\' OR fact LIKE ? ESCAPE '\\')
ORDER BY importance DESC
LIMIT ?
""",
                (agent_id, like, like, limit),
            ).fetchall():
                hits.append(
                    {
                        "source": "fact",
                        "id": r["id"],
                        "title": f"{r['entity']}: {r['fact']}",
                        "excerpt": r["fact"],
                        "date": None,
                        "importance": float(r["importance"] or 0.5),
                        "type_weight": TYPE_WEIGHT["fact"],
                        "score": 0.0,
                    }
                )
        if scope in ("all", "episodes"):
            for r in db.execute(
                """
SELECT id, role, content, created_at FROM episodes
WHERE agent_id=? AND content LIKE ? ESCAPE '\\'
ORDER BY created_at DESC
LIMIT ?
""",
                (agent_id, like, limit),
            ).fetchall():
                hits.append(
                    {
                        "source": "episode",
                        "id": r["id"],
                        "title": f"[{r['role']}] " + (r["content"] or "")[:40],
                        "excerpt": (r["content"] or "")[:200].replace("\n", " "),
                        "date": str(r["created_at"])[:10] if r["created_at"] else None,
                        "importance": 0.5,
                        "type_weight": TYPE_WEIGHT["episode"],
                        "score": 0.0,
                    }
                )
    except sqlite3.Error:
        return []
    return hits


# ────────────────────────────────────────────────────────────
#  3b 实体关系信号（三信号之一：图连通性）
#     查询词命中 memory_facts.entity 时，拉取该实体关联的
#     语义事实 + 提及该实体的情节(episodes)，打通「事实↔对话」图边。
# ────────────────────────────────────────────────────────────


def _signal_entity_relation(query, subject, scope, db, limit, agent_id: str = "alex"):
    """实体关系检索：以 memory_facts.entity 为锚，连接相关事实与情节。"""
    hits: list = []
    q = (query or "").strip()
    if len(q) < 2:
        return hits
    like = f"%{q}%"
    try:
        # 1) 命中实体名的语义事实
        fact_rows = db.execute(
            """
SELECT id, subject, entity, fact, fact_type, importance, confidence, status
FROM memory_facts
WHERE status='active' AND agent_id=?
  AND (entity LIKE ? ESCAPE '\\' OR ? LIKE '%' || entity || '%' ESCAPE '\\')
LIMIT ?
""",
            (agent_id, like, q, limit),
        ).fetchall()
        for r in fact_rows:
            hits.append(
                {
                    "source": "fact",
                    "id": r["id"],
                    "title": f"{r['entity']}: {r['fact']}",
                    "excerpt": r["fact"],
                    "date": None,
                    "importance": float(r["importance"] or 0.5),
                    "type_weight": TYPE_WEIGHT["fact"],
                    "score": 0.0,
                    "signal": "entity",
                }
            )

        # 2) 该实体关联的情节(图边: 事实实体 → 对话回合)
        if scope in ("all", "episodes"):
            ent_rows = db.execute(
                "SELECT DISTINCT entity FROM memory_facts WHERE agent_id=? "
                "AND (entity LIKE ? ESCAPE '\\' OR ? LIKE '%' || entity || '%' ESCAPE '\\') LIMIT ?",
                (agent_id, like, q, limit),
            ).fetchall()
            for er in ent_rows:
                ent = er["entity"]
                for ep in db.execute(
                    """
SELECT id, session_id, role, content, created_at
FROM episodes
WHERE agent_id=? AND content LIKE ? ESCAPE '\\'
ORDER BY created_at DESC
LIMIT ?
""",
                    (agent_id, f"%{ent}%", limit),
                ).fetchall():
                    hits.append(
                        {
                            "source": "episode",
                            "id": ep["id"],
                            "title": f"[{ep['role']}] {ent}",
                            "excerpt": (ep["content"] or "")[:200].replace("\n", " "),
                            "date": str(ep["created_at"])[:10] if ep["created_at"] else None,
                            "importance": 0.5,
                            "type_weight": TYPE_WEIGHT["episode"],
                            "score": 0.0,
                            "signal": "entity",
                        }
                    )
    except sqlite3.Error:
        return []
    return hits


# ────────────────────────────────────────────────────────────
#  4 合并 / 去重 / 重排
# ────────────────────────────────────────────────────────────


def _merge_dedupe(*lists):
    """合并多源结果并去重(按 source+id，保留首次出现)。"""
    seen = set()
    merged = []
    for lst in lists:
        for item in lst:
            key = (item["source"], item["id"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _recency_boost(item):
    """时间近因信号：带日期且越近的条目加权越高(三信号之一)。"""
    d = item.get("date")
    if not d:
        return 0.0
    try:
        dt = datetime.strptime(str(d)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return 0.0
    days = (datetime.now() - dt).days
    if days < 0:
        return 0.3
    if days <= 7:
        return 0.3
    if days <= 30:
        return 0.15
    if days <= 90:
        return 0.05
    return 0.0


def _rerank(merged):
    """
    元数据重排(多信号融合)：
    - 相关性：bm25 越负越相关 → 升序最前；实体关系命中(信号=entity)得 -0.5 提权
    - 时间近因：越近的条目越优先(_recency_boost 从相关分中扣除)
    - 类型权重高优先（语义事实 > 情节）
    - 重要度高优先
    """

    def key(it):
        score = it.get("score") or 0.0
        if it.get("signal") == "entity":
            score -= 0.5
        return (
            score - _recency_boost(it),
            -TYPE_WEIGHT.get(it.get("source", ""), 1),
            -(it.get("importance") or 0.0),
        )

    return sorted(merged, key=key)


# ────────────────────────────────────────────────────────────
#  降级护栏：结构化摘要（无检索结果时返回，绝不丢数据）
# ────────────────────────────────────────────────────────────


def _structured_summary(subject, scope, db, limit, agent_id: str = "alex"):
    """core 可及的结构化兜底：按科目返回高重要度事实 / 最近情节。"""
    try:
        if scope in ("all", "facts"):
            rows = db.execute(
                """
SELECT entity, fact, importance FROM memory_facts
WHERE agent_id=? AND status='active' AND (subject=? OR subject='')
ORDER BY importance DESC, last_confirmed_at DESC LIMIT ?
""",
                (agent_id, subject or "", limit),
            ).fetchall()
            return [
                {
                    "source": "fact",
                    "id": None,
                    "title": f"{r['entity']}: {r['fact']}",
                    "excerpt": r["fact"],
                    "date": None,
                    "importance": float(r["importance"] or 0.5),
                    "type_weight": TYPE_WEIGHT["fact"],
                    "score": 0.0,
                }
                for r in rows
            ]
        if scope == "episodes":
            rows = db.execute(
                """
SELECT id, role, content, created_at FROM episodes
WHERE agent_id=? ORDER BY created_at DESC LIMIT ?
""",
                (agent_id, limit),
            ).fetchall()
            return [
                {
                    "source": "episode",
                    "id": r["id"],
                    "title": f"[{r['role']}] " + (r["content"] or "")[:40],
                    "excerpt": (r["content"] or "")[:200].replace("\n", " "),
                    "date": str(r["created_at"])[:10] if r["created_at"] else None,
                    "importance": 0.5,
                    "type_weight": TYPE_WEIGHT["episode"],
                    "score": 0.0,
                }
                for r in rows
            ]
        return []
    except sqlite3.Error:
        return []


def _record_trace(db, query: str, agent_id: str, signals_used: list[str], hits: int, latency_ms: float, persona: str = "") -> None:
    """检索 trace 落 retrieval_log（幂等：表不存在则静默跳过，不阻断主流程）。"""
    if not _TRACE_ENABLED:
        return
    try:
        db.execute(
            """
INSERT INTO retrieval_log (query, agent_id, persona, signals_used, hits, latency_ms)
VALUES (?, ?, ?, ?, ?, ?)
""",
            (query, agent_id, persona, json.dumps(signals_used, ensure_ascii=False), hits, latency_ms),
        )
        if getattr(db, "in_transaction", False):
            db.commit()
    except sqlite3.Error:
        pass  # 表未迁移 / 只读测试库 → 跳过 trace


# ────────────────────────────────────────────────────────────
#  统一检索入口（领域无关，多租户就绪）
# ────────────────────────────────────────────────────────────


def retrieve(
    query: str,
    subject: str | None = None,
    scope: str = "all",
    limit: int = 10,
    db=None,
    agent_id: str = "alex",
    trace: bool = True,
    persona: str = "",
) -> list[dict]:
    """
    统一检索入口（结构化 → trigram → LIKE → 实体关系 → 重排）。

    Args:
        query:    检索词（中文 ≥3 字走 trigram；<3 字或 trigram 未命中走 LIKE）
        subject:  科目过滤（结构化过滤 + 实体关系关联用）
        scope:    "all" | "facts" | "episodes"（diary/knowledge 由人设钩子补）
        limit:    返回上限(1-50)
        db:       可选连接；省略则使用单例
        agent_id: 多租户过滤（默认 "alex"，向后兼容）
        trace:    是否写 retrieval_log（默认真实）
        persona:  检索来源人设（trace 记录用）

    Returns:
        list[dict]，每条含 source / id / title / excerpt / date / importance / score 等
    """
    conn = _get_conn(db)
    limit = max(1, min(int(limit), 50))
    t0 = time.perf_counter()
    signals_used: list[str] = []
    result: list[dict] = []  # finally 引用前先初始化，避免异常路径 NameError

    try:
        candidates = _structured_filter(subject, scope, conn, agent_id)
        trigram_hits, like_hits, entity_hits = [], [], []
        q = (query or "").strip()
        if q and len(q) >= 3:  # 1 trigram（中文 ≥3 字）
            trigram_hits = _fts_trigram_match(q, subject, scope, conn, limit, agent_id)
            if trigram_hits:
                signals_used.append("trigram")
        if (q and len(q) < 3) or not trigram_hits:  # 2 短词 LIKE 兜底
            like_hits = _like_fallback(q, subject, scope, conn, limit, agent_id)
            if like_hits:
                signals_used.append("like")
        if q:  # 3b 实体关系信号
            entity_hits = _signal_entity_relation(q, subject, scope, conn, limit, agent_id)
            if entity_hits:
                signals_used.append("entity")

        merged = _merge_dedupe(trigram_hits, like_hits, entity_hits, candidates)
        ranked = _rerank(merged)

        if not ranked:  # 降级：仅结构化
            ranked = _structured_summary(subject, scope, conn, limit, agent_id)

        result = ranked[:limit]
        if result:
            signals_used.append("structured")
        return result
    except Exception:
        # 降级护栏：任何一层检索异常 → 结构化摘要，绝不抛错 / 丢数据
        try:
            return _structured_summary(subject, scope, conn, limit, agent_id)[:limit]
        except Exception:
            return []
    finally:
        latency_ms = (time.perf_counter() - t0) * 1000
        if trace:
            _record_trace(conn, (query or "").strip(), agent_id, signals_used, len(result), latency_ms, persona)
