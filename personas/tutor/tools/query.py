#!/usr/bin/env python3
"""
personas.tutor.tools.query — 结构化错误查询（v4.0 tool_query_errors 完整平移）
==============================================================================
适配：error_patterns→tutor_error_patterns、memory_facts 按 agent_id 过滤。
"""

from __future__ import annotations

import json
import sqlite3

from core.api import MemoryAPI


def tool_query_errors(api: MemoryAPI, p: dict) -> dict:
    """结构化错误查询（完整字段：排序 / 统计 / 跨科目泛化 / 语义事实关联）。"""
    db = api.conn
    agent_id = p.get("agent_id", "alex")

    subject = p.get("subject", "")
    category = p.get("category", "")
    status = p.get("status", "")
    include_cross = p.get("include_cross_subject", False)
    limit = min(int(p.get("limit", 10)), 50)  # 上限保护

    where_clauses = ["agent_id=?"]
    where_args: list = [agent_id]

    if subject:
        where_clauses.append("(subject=? OR subject='' OR subject=?)")
        where_args.extend([subject, "general"])
    if category:
        where_clauses.append("category LIKE ?")
        where_args.append(f"%{category}%")
    if status:
        where_clauses.append("status=?")
        where_args.append(status)

    where_sql = " WHERE " + " AND ".join(where_clauses)

    rows = db.execute(
        f"""
        SELECT id, pattern, category, root_cause, subject,
               first_seen_at, last_seen_at, frequency_history,
               status, remedy, cross_subject_mappings
        FROM tutor_error_patterns
        {where_sql}
        ORDER BY
            CASE status
                WHEN 'active' THEN 0
                WHEN 'mostly_resolved' THEN 1
                ELSE 2
            END,
            JSON_ARRAY_LENGTH(frequency_history) DESC,
            LENGTH(frequency_history) DESC
        LIMIT ?
        """,
        (*where_args, limit),
    ).fetchall()

    results = []
    for r in rows:
        item = dict(r)
        try:
            item["frequency_history"] = json.loads(item.get("frequency_history") or "[]")
        except Exception:  # noqa: BLE001
            pass
        try:
            item["cross_subject_maps"] = json.loads(item.get("cross_subject_mappings") or "[]")
        except Exception:  # noqa: BLE001
            pass
        # 关联语义事实（同 subject 的 mistake/strength）
        try:
            rel = db.execute(
                """
                SELECT entity, fact, fact_type, importance, confidence, status
                FROM memory_facts
                WHERE agent_id=? AND status='active' AND fact_type IN ('mistake', 'strength')
                  AND (subject=? OR subject='')
                ORDER BY importance DESC, last_confirmed_at DESC
                LIMIT 3
                """,
                (agent_id, item.get("subject", "")),
            ).fetchall()
            item["related_facts"] = [dict(x) for x in rel] if rel else []
        except sqlite3.Error:
            item["related_facts"] = []
        results.append(item)

    # 统计
    total_active = db.execute(
        "SELECT COUNT(*) FROM tutor_error_patterns WHERE agent_id=? AND status='active'",
        (agent_id,),
    ).fetchone()[0]
    resolved_this_month = db.execute(
        """SELECT COUNT(*) FROM tutor_error_patterns
           WHERE agent_id=? AND status IN ('resolved', 'resolved_after_incident')
           AND last_seen_at >= date('now', '-30 days')""",
        (agent_id,),
    ).fetchone()[0]

    # 跨科目泛化
    cross_results = []
    if include_cross and results:
        categories_seen = {r["category"] for r in results}
        seen_ids = {r["id"] for r in results}
        for cat in categories_seen:
            cross_args: list = [agent_id, cat]
            if subject:
                cross_args.extend([subject, ""])
            id_placeholders = ",".join("?" * len(seen_ids)) if seen_ids else "NULL"
            cross_rows = db.execute(
                f"""
                SELECT pattern, subject, status, remedy
                FROM tutor_error_patterns
                WHERE agent_id=? AND category=?
                {"AND subject NOT IN (?, ?)" if subject else ""}
                AND id NOT IN ({id_placeholders})
                LIMIT 2
                """,
                tuple(cross_args + list(seen_ids)),
            ).fetchall()
            cross_results.extend([dict(r) for r in cross_rows])

    return {
        "results": results,
        "total_active": total_active,
        "resolved_this_month": resolved_this_month,
        "cross_subject_matches": cross_results,
        "query_params": {
            "subject": subject,
            "category": category,
            "status": status,
            "include_cross_subject": include_cross,
            "limit": limit,
        },
    }
