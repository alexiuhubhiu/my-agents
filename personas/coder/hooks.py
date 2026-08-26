#!/usr/bin/env python3
"""
personas.coder.hooks — 编程人设 context 钩子（get_context 注入编程专属上下文）
===============================================================================
注入：活跃任务 / 最近审查 / 当前仓库。
"""

from __future__ import annotations


def inject_coder_context(bundle: dict, agent_id: str, freshness_level: str) -> dict:
    from core.db import get_db

    conn = get_db()
    ext: dict = {}

    # 1) 活跃任务（todo/doing，按优先级）
    tasks = conn.execute(
        """SELECT title, description, repo, priority, status FROM coder_tasks
           WHERE agent_id=? AND status IN ('todo', 'doing')
           ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
           LIMIT 5""",
        (agent_id,),
    ).fetchall()
    if tasks:
        ext["active_tasks"] = [dict(r) for r in tasks]

    # 2) 最近审查
    reviews = conn.execute(
        """SELECT repo, file_path, review_type, issues_found, issues_fixed, created_at
           FROM coder_reviews WHERE agent_id=?
           ORDER BY created_at DESC LIMIT 3""",
        (agent_id,),
    ).fetchall()
    if reviews:
        ext["recent_reviews"] = [dict(r) for r in reviews]

    # 3) 当前仓库（agent_state 扩展列）
    row = conn.execute(
        "SELECT coder_active_repo, coder_open_tasks FROM agent_state WHERE agent_id=?", (agent_id,)
    ).fetchone()
    if row:
        ext["active_repo"] = row["coder_active_repo"] or ""
        ext["open_tasks_count"] = row["coder_open_tasks"] or 0

    return ext
