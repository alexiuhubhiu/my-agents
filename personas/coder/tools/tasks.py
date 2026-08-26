#!/usr/bin/env python3
"""
personas.coder.tools.tasks — 编程任务追踪工具（coder 专属）
"""

from __future__ import annotations

from core.api import MemoryAPI


def tool_record_task(api: MemoryAPI, p: dict) -> dict:
    """记录一个编程任务（去重置顶：同 (agent_id, title) 更新）。

    params: title(必填), description, repo, priority
    """
    agent_id = p.get("agent_id", "default")
    title = (p.get("title") or "").strip()
    if not title:
        return {"success": False, "error": "title 不能为空"}

    conn = api.conn
    conn.execute(
        """INSERT INTO coder_tasks (agent_id, title, description, repo, priority)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(agent_id, title) DO UPDATE SET
               description=excluded.description,
               repo=excluded.repo,
               priority=excluded.priority,
               status=CASE WHEN coder_tasks.status='done' THEN 'todo' ELSE coder_tasks.status END""",
        (agent_id, title, p.get("description", ""), p.get("repo", ""), p.get("priority", "medium")),
    )
    conn.execute(
        """UPDATE agent_state SET coder_open_tasks=(
               SELECT COUNT(*) FROM coder_tasks WHERE agent_id=? AND status IN ('todo','doing')
           ), updated_at=datetime('now') WHERE agent_id=?""",
        (agent_id, agent_id),
    )
    conn.commit()
    return {"success": True, "title": title, "status": "todo"}


def tool_complete_task(api: MemoryAPI, p: dict) -> dict:
    """完成一个编程任务。"""
    agent_id = p.get("agent_id", "default")
    title = (p.get("title") or "").strip()
    conn = api.conn
    cur = conn.execute(
        "UPDATE coder_tasks SET status='done', completed_at=datetime('now') WHERE agent_id=? AND title=?",
        (agent_id, title),
    )
    conn.commit()
    return {"success": cur.rowcount > 0, "title": title, "completed": cur.rowcount > 0}
