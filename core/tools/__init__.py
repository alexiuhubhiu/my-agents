#!/usr/bin/env python3
"""
core.tools — 记忆底层通用 MCP 工具（全人设共享）
==================================================
工具名不带前缀（全人设共享命名空间）；人设专属工具在
personas/<name>/tools/ 中带 <persona>_ 前缀。

CORE_TOOLS 契约：每个元素 = (工具名, 描述, 处理器函数, 参数Schema)。
server.py 依此注册到 FastMCP，人设层不得覆盖 core 工具名。
"""

from __future__ import annotations

from ..api import MemoryAPI
from .. import registry

# 处理器签名统一：fn(api, params: dict) -> dict


def _start_session(api: MemoryAPI, p: dict) -> dict:
    return api.start_session(
        agent_id=p.get("agent_id", "default"),
        persona=p.get("persona", ""),
        subject=p.get("subject", ""),
        topic=p.get("topic", ""),
    )


def _end_session(api: MemoryAPI, p: dict) -> dict:
    return api.end_session(
        session_id=p.get("session_id", ""),
        summary=p.get("summary", ""),
        turn_count=int(p.get("turn_count", 0)),
    )


def _log_episode(api: MemoryAPI, p: dict) -> dict:
    return api.log_episode(
        session_id=p.get("session_id", ""),
        role=p.get("role", "user"),
        content=p.get("content", ""),
        agent_id=p.get("agent_id", "default"),
        topic=p.get("topic", ""),
    )


def _recall_episodes(api: MemoryAPI, p: dict) -> dict:
    return api.recall_episodes(
        session_id=p.get("session_id", ""),
        agent_id=p.get("agent_id", "default"),
        last_n=int(p.get("last_n", 1)),
        scope=p.get("scope", "current_session"),
    )


def _distill_memory(api: MemoryAPI, p: dict) -> dict:
    return api.distill_facts(
        agent_id=p.get("agent_id", "default"),
        facts=p.get("facts", []),
        persona=p.get("persona", ""),
    )


def _get_context(api: MemoryAPI, p: dict) -> dict:
    return api.get_context(
        agent_id=p.get("agent_id", "default"),
        persona=p.get("persona", ""),
        freshness_level=p.get("freshness_level", "hot"),
        focus_subject=p.get("focus_subject", ""),
        session_id=p.get("session_id", ""),
    )


def _get_state(api: MemoryAPI, p: dict) -> dict:
    return api.get_state(p.get("agent_id", "default"))


def _update_state(api: MemoryAPI, p: dict) -> dict:
    return api.update_state(
        agent_id=p.get("agent_id", "default"),
        updates=p.get("updates", {}),
        expected_version=p.get("expected_version"),
    )


def _retrieve(api: MemoryAPI, p: dict) -> dict:
    hits = api.retrieve(
        query=p.get("query", ""),
        agent_id=p.get("agent_id", "default"),
        persona=p.get("persona", ""),
        subject=p.get("subject", "") or None,
        limit=int(p.get("limit", 10)),
    )
    return {"hits": hits, "count": len(hits)}


def _switch_persona(api: MemoryAPI, p: dict) -> dict:
    return registry.switch_persona(
        agent_id=p.get("agent_id", "default"),
        persona=p.get("persona", ""),
    )


def _list_personas(api: MemoryAPI, p: dict) -> dict:
    return {"personas": registry.list_personas()}


def _evolve(api: MemoryAPI, p: dict) -> dict:
    return api.evolve(
        capabilities=p.get("capabilities"),
        dry_run=bool(p.get("dry_run", False)),
        agent_id=p.get("agent_id", "default"),
        persona=p.get("persona", ""),
    )


def _revert_evolution(api: MemoryAPI, p: dict) -> dict:
    return api.revert_evolution(
        event_id=int(p.get("event_id", 0)),
        agent_id=p.get("agent_id", "default"),
    )


def _health(api: MemoryAPI, p: dict) -> dict:
    return api.health()


def _db_query(api: MemoryAPI, p: dict) -> dict:
    sql = p.get("sql", "")
    if not sql.strip().upper().startswith(("SELECT", "EXPLAIN", "PRAGMA", "WITH")):
        return {"success": False, "reason": "仅允许只读 SQL"}
    rows = api.conn.execute(sql).fetchall()
    cols = rows[0].keys() if rows else []
    return {"columns": list(cols), "rows": [dict(r) for r in rows], "row_count": len(rows)}


def _db_execute(api: MemoryAPI, p: dict) -> dict:
    """写 SQL（v4.0 tool_db_execute 平移）：白名单 + 禁 DROP。"""
    sql = (p.get("sql") or "").strip()
    stmt = sql.split(None, 1)[0].upper() if sql else ""
    allowed = {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "BEGIN", "COMMIT", "ROLLBACK"}
    if not sql:
        return {"success": False, "error": "sql 为空"}
    if stmt not in allowed:
        return {
            "success": False,
            "error": f"语句类型 '{stmt}' 不允许（仅 {sorted(allowed)}），DROP 需手动 sqlite3 CLI",
        }
    try:
        conn = api.conn
        cur = conn.execute(sql)
        conn.commit()
        return {"success": True, "changes": conn.total_changes, "statement_type": stmt}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}


def _schema(api: MemoryAPI, p: dict) -> dict:
    conn = api.conn
    table = p.get("table", "")
    if table:
        names = [table]
    else:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
    out = {}
    for t in names:
        cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        out[t] = {
            "row_count": n,
            "fields": [
                {"name": c[1], "type": c[2], "notnull": bool(c[3]), "default": c[4], "pk": bool(c[5])}
                for c in cols
            ],
        }
    return {"tables": out}


# ── 注册表：供 server.py 遍历注册 ──
CORE_TOOLS: list[tuple[str, str, callable]] = [
    ("mem_start_session", "创建会话（通用，全人设共享）。返回 session_id，幂等复用。", _start_session),
    ("mem_end_session", "关闭会话（通用收尾）。人设专属收尾见各人设工具。", _end_session),
    ("mem_log_episode", "追加对话回合（情节记忆）。", _log_episode),
    ("mem_recall_episodes", "回忆历史对话（上次聊了什么）。", _recall_episodes),
    ("mem_distill", "蒸馏语义事实（upsert 冲突消解）。", _distill_memory),
    ("mem_get_context", "聚合上下文：通用记忆 + 当前人设扩展（persona_ext）。", _get_context),
    ("mem_get_state", "查询通用工作状态。", _get_state),
    ("mem_update_state", "原子化更新工作状态（PATCH+乐观锁，扩展列自动路由）。", _update_state),
    ("mem_retrieve", "三信号检索语义记忆。", _retrieve),
    ("mem_switch_persona", "切换当前激活的工作人设（数据不销毁，按 agent_id 隔离）。", _switch_persona),
    ("mem_list_personas", "列出已加载工作人设。", _list_personas),
    ("mem_evolve", "运行进化框架（人设自定义能力 + 通用能力）。", _evolve),
    ("mem_revert_evolution", "回滚进化事件。", _revert_evolution),
    ("mem_health", "记忆底层健康自检（含检索 P95）。", _health),
    ("mem_db_query", "只读 SQL（SELECT/EXPLAIN/PRAGMA/WITH）。", _db_query),
    ("mem_db_execute", "写 SQL（INSERT/UPDATE/DELETE/CREATE/ALTER，禁 DROP）。", _db_execute),
    ("mem_schema", "查询表结构（写 SQL 前必查）。", _schema),
]
