#!/usr/bin/env python3
"""
personas.coder.tools.reviews — 代码审查记录工具（coder 专属）
"""

from __future__ import annotations

from core.api import MemoryAPI


def tool_record_review(api: MemoryAPI, p: dict) -> dict:
    """记录一次代码审查（含问题/修复统计）。"""
    agent_id = p.get("agent_id", "default")
    conn = api.conn
    cur = conn.execute(
        """INSERT INTO coder_reviews (agent_id, repo, file_path, review_type, issues_found, issues_fixed, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            agent_id,
            p.get("repo", ""),
            p.get("file_path", ""),
            p.get("review_type", "self"),
            int(p.get("issues_found", 0)),
            int(p.get("issues_fixed", 0)),
            p.get("notes", ""),
        ),
    )
    conn.commit()
    return {"success": True, "review_id": cur.lastrowid}
