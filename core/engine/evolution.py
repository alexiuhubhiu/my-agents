#!/usr/bin/env python3
"""
core.engine.evolution — 通用记忆进化框架基座（领域无关）
=========================================================
职责（v4.0 平移，能力具体逻辑下沉人设层）：
- log_event           — 不可变进化事件日志（dry_run 时 applied=False）
- run_evolution       — 调度入口：从 registry 取当前人设挂载的进化能力（如 C2/C3）
                          + 通用能力，_EVO_LOCK 串行化防并发写库
- revert_evolution    — 回滚：按 change_before 回写目标表（兼容 C1 删除/C2 subject键/
                          C3 name键/通用列四类分支），并追加 revert 事件

设计原则（继承 v4.0）：
- 非破坏性分析 + 不可变日志(evolution_events)
- 置信度门控：>= 0.8 自动应用，0.5-0.8 仅记录供人工审查
- 支持 dry_run 模式用于安全测试
- 每次修改都有 change_before / change_after 完整记录

红线：本模块不 import personas，不出现任何领域常量；
能力通过 registry（core.registry._loaded[persona].evolution_caps）动态挂载。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import get_db

# 进化运行串行锁：避免并发写库造成竞争
_EVO_LOCK = threading.Lock()

# ── 能力标识（引擎级通用 ID，人设层引用；避免双源）──
C1_CAPS = {"c1_error_detect", "llm_pattern_discovery"}
C2_CAPS = {"c2_sm2_tune", "c2_review_schedule", "c2_review"}
C3_CAPS = {"c3_trigger_evolve", "c3_triggers"}

# 置信度门控
CONF_APPLY = 0.8


def log_event(
    db: sqlite3.Connection,
    event_type: str,
    capability: str,
    target_table: str,
    target_id: int | None,
    change_before: dict,
    change_after: dict,
    confidence: float,
    reason: str,
    applied: bool = False,
    dry_run: bool = False,
    agent_id: str = "",
) -> int:
    """将进化事件写入不可变日志。applied 在 dry_run 模式为 False。返回新事件 id。"""
    final_applied = applied and not dry_run
    cur = db.execute(
        """
        INSERT INTO evolution_events
        (event_type, capability, target_table, target_id,
         change_before, change_after, confidence, reason,
         applied, created_at, session_id, agent_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'), ?, ?)
        """,
        (
            event_type,
            capability,
            target_table,
            target_id,
            json.dumps(change_before, ensure_ascii=False),
            json.dumps(change_after, ensure_ascii=False),
            confidence,
            reason,
            1 if final_applied else 0,
            f"auto-{datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')}",
            agent_id,
        ),
    )
    return cur.lastrowid


# ────────────────────────────────────────────────────────────
#  进化调度入口
# ────────────────────────────────────────────────────────────


def run_evolution(
    capabilities: list | None = None,
    dry_run: bool = False,
    db_path: str | None = None,
    agent_id: str = "",
    persona: str = "",
) -> dict:
    """公开入口：串行化进化运行，避免并发写库竞争。"""
    with _EVO_LOCK:
        return _run_evolution_unlocked(capabilities, dry_run, db_path, agent_id, persona)


def _run_evolution_unlocked(
    capabilities: list | None = None,
    dry_run: bool = False,
    db_path: str | None = None,
    agent_id: str = "",
    persona: str = "",
) -> dict:
    """
    进化主入口（无锁版本）。

    分派规则：
    - capabilities=None → 执行当前 persona 挂载的全部能力
    - 能力键从 registry 已加载人设的 evolution_caps 中查找（personas/<name>/evolution.py 的 CAPABILITIES）
    - 能力签名统一：fn(conn, agent_id="", dry_run=False) -> dict
    - 通用能力（core 内置，如 c1_error_detect）直接调用；未注册 → warnings
    """
    if capabilities is None:
        capabilities = _default_capabilities(persona)

    if db_path:
        db = sqlite3.connect(str(db_path), timeout=5)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.row_factory = sqlite3.Row
    else:
        db = get_db()

    # 从 registry 取人设能力（core.registry 是 core 内部模块，允许引用）
    from .. import registry

    caps: dict = {}
    ctx = registry._loaded.get(persona) if persona else None
    if ctx:
        caps = ctx.evolution_caps

    results = []
    warnings: list[Any] = []
    total_applied = 0

    for cap in capabilities:
        fn = caps.get(cap)
        if fn is None:
            warnings.append(f"未知能力 '{cap}'（人设 '{persona}' 未注册），跳过")
            continue
        try:
            result = fn.run(db, agent_id=agent_id, dry_run=dry_run)
            results.append(result)
            total_applied += (
                result.get("adjustments_made", 0)
                + result.get("changes_made", 0)
                + result.get("applied_count", 0)
                + len(result.get("applied", []) or [])
            )
            for item in (
                result.get("adjustments", [])
                + result.get("changes", [])
                + result.get("applied", []) or []
            ):
                if isinstance(item, dict) and item.get("confidence", 1.0) < CONF_APPLY:
                    warnings.append(
                        {
                            "capability": cap,
                            "item": item.get("pattern") or item.get("subject") or item.get("name", "?"),
                            "confidence": item["confidence"],
                            "reason": item.get("reason", ""),
                        }
                    )
        except Exception as e:  # noqa: BLE001
            warnings.append({"capability": cap, "error": str(e)})

    db.commit()

    total_events = db.execute("SELECT COUNT(*) FROM evolution_events").fetchone()[0]

    if db_path:
        db.close()

    return {
        "success": True,
        "persona": persona,
        "dry_run": dry_run,
        "analyzed_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "results": results,
        "events_logged": total_events,
        "auto_applied": total_applied,
        "warnings": warnings,
        "summary": (
            f"执行 {len(capabilities)} 项能力{'（仅分析）' if dry_run else ''}，"
            f"自动应用 {total_applied} 项变更，"
            f"记录 {total_events} 条进化事件"
            + (f"，{len(warnings)} 项需人工审查" if warnings else "")
        ),
    }


def _default_capabilities(persona: str) -> list[str]:
    """默认执行人设已注册的全部能力。"""
    from .. import registry

    ctx = registry._loaded.get(persona)
    if ctx:
        return list(ctx.evolution_caps.keys())
    return []


# ────────────────────────────────────────────────────────────
#  回滚机制
# ────────────────────────────────────────────────────────────


def revert_evolution(db: sqlite3.Connection, event_id: int) -> dict:
    """
    回滚一个已应用的进化事件（v4.0 完整版平移 + 动态表名校验）。

    规则:
    - 只能回滚 applied=1 且 reverted=0 的事件
    - 读取 change_before，回写到目标表（target_table 动态校验列存在）
    - C1 分支：删除错误模式行（change_before.id 或 target_id）
    - C2 分支：change_before 为 {subject: {"next_review_at": ...}} 或直接 {"next_review_at": ...}
    - C3 分支：兼容扁平/嵌套两种 change_before 格式，按 name 回写
    - 通用列回滚：change_before 为 {列名: 值} 且 target_id 存在 → 按 id 回写
    - 标记 reverted=1，追加 revert 事件
    """
    event = db.execute("SELECT * FROM evolution_events WHERE id=?", (event_id,)).fetchone()
    if not event:
        return {"success": False, "error": f"事件 #{event_id} 不存在"}
    if not event["applied"]:
        return {"success": False, "error": f"事件 #{event_id} 未被应用，无需回滚"}
    if event["reverted"]:
        return {"success": False, "error": f"事件 #{event_id} 已被回滚"}

    change_before = json.loads(event["change_before"] or "{}")
    change_after = json.loads(event["change_after"] or "{}")
    target_table = event["target_table"]
    target_id = event["target_id"]
    capability = event["capability"]

    if not change_before or not target_table:
        return {"success": False, "error": "事件缺少 change_before 数据或目标表，无法回滚"}

    reverted_fields = []

    try:
        # 动态校验表存在 + 列清单（避免 SQL 报错）
        tbl_info = db.execute(f"PRAGMA table_info({target_table})").fetchall()
        if not tbl_info:
            return {"success": False, "error": f"目标表 {target_table} 不存在"}
        cols = {r[1] for r in tbl_info}

        if capability in C2_CAPS:
            # C2 回滚：change_before 可能是 {subject: {next_review_at}} 或直接 {next_review_at}
            if "next_review_at" in change_before and not isinstance(
                next(iter(change_before.values())), dict
            ):
                # 直接格式（单行）
                if "next_review_at" in cols and target_id is not None:
                    db.execute(
                        f"UPDATE {target_table} SET next_review_at=? WHERE id=?",
                        (change_before["next_review_at"], target_id),
                    )
                    reverted_fields.append(
                        f"#{target_id}: 复习计划已恢复 (next_review_at={change_before['next_review_at']})"
                    )
                elif "subject" in cols:
                    db.execute(
                        f"UPDATE {target_table} SET next_review_at=? WHERE subject=?",
                        (change_before.get("next_review_at"), change_before.get("subject", "")),
                    )
            else:
                # 嵌套格式 {subject: {next_review_at: ...}}
                for subject, params in change_before.items():
                    if not isinstance(params, dict):
                        continue
                    if params.get("next_review_at") is not None and "next_review_at" in cols:
                        db.execute(
                            f"UPDATE {target_table} SET next_review_at=? WHERE subject=?",
                            (params["next_review_at"], subject),
                        )
                        reverted_fields.append(
                            f"{subject}: 复习计划已恢复 (next_review_at={params['next_review_at']})"
                        )

        elif capability in C3_CAPS:
            # C3 回滚：兼容扁平/嵌套两种 change_before 格式，按 name 回写
            def _restore_trigger(name, state):
                if not isinstance(state, dict):
                    return
                upd, vals = [], []
                if "active" in state and "active" in cols:
                    upd.append("active=?")
                    vals.append(1 if state.get("active") else 0)
                if "severity" in state and "severity" in cols:
                    upd.append("severity=?")
                    vals.append(state.get("severity", "warning"))
                if "cooldown_turns" in state and "cooldown_turns" in cols:
                    upd.append("cooldown_turns=?")
                    vals.append(state.get("cooldown_turns"))
                if upd and "name" in cols:
                    vals.append(name)
                    db.execute(f"UPDATE {target_table} SET {', '.join(upd)} WHERE name=?", vals)
                    reverted_fields.append(
                        f"{name}: active={state.get('active')}, severity={state.get('severity')}"
                    )

            if "name" in change_before and not isinstance(change_before.get("name"), dict):
                _restore_trigger(change_before["name"], change_before)
            else:
                for name, state in change_before.items():
                    _restore_trigger(name, state)

        elif capability in C1_CAPS:
            # C1 回滚：删除新发现的错误模式
            del_id = change_before.get("id") if isinstance(change_before, dict) else None
            row_id = del_id or target_id
            if row_id is not None:
                db.execute(f"DELETE FROM {target_table} WHERE id=?", (row_id,))
                reverted_fields.append(f"{target_table} #{row_id} 已删除")

        else:
            # 通用列回滚：change_before 为 {列名: 值}，按 target_id 回写
            if target_id is not None:
                updates, values = [], []
                for key, val in change_before.items():
                    if key in cols:
                        updates.append(f"{key}=?")
                        values.append(val)
                if updates:
                    values.append(target_id)
                    db.execute(
                        f"UPDATE {target_table} SET {', '.join(updates)} WHERE id=?",
                        values,
                    )
                    reverted_fields.append(f"#{target_id}: {', '.join(change_before.keys())} 已恢复")

        # 标记事件为已回滚
        db.execute("UPDATE evolution_events SET reverted=1 WHERE id=?", (event_id,))

        # 记录回滚事件
        log_event(
            db,
            "revert",
            capability,
            target_table,
            target_id,
            change_after,
            change_before,
            1.0,
            f"手动回滚事件 #{event_id}: {event['reason']}",
            applied=True,
            dry_run=False,
            agent_id=event["agent_id"] or "",
        )

        db.commit()
        return {
            "success": True,
            "event_id": event_id,
            "capability": capability,
            "reverted_fields": reverted_fields,
            "message": f"事件 #{event_id} 已成功回滚",
        }

    except Exception as e:  # noqa: BLE001
        db.rollback()
        return {"success": False, "error": f"回滚失败: {str(e)}"}
