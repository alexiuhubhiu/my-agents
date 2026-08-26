#!/usr/bin/env python3
"""
personas.tutor.tools.session — 导师下课收尾组合（v4.0 end_session 完整平移）
============================================================================
7 步编排（顺序即契约，每步 try/except 不阻断）：
① GOODBYE + session_summary（→ tutor_teaching_metrics 级联 + tutor_learning_progress 复习计数）
② 课后密集区初始化 rounds=8
③ 错误模式入库（C1 辅助通道，去重 + evolution_events）
③.5 自动蒸馏本 session 事实（facts 优先，notes[:200] 降级）
③.6 sessions 回填（turn_count 由 episodes 计数兜底、summary=notes[:500]、status='closed'）
④ 进化（C2 复习计划 + C3 触发器进化，api.evolve 委托）
⑤ COMPLETED
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.api import MemoryAPI

CST = timezone(timedelta(hours=8))
ROUNDS_LEFT = 8  # 课后密集区轮数（v4.0 魔法数保留）


def tool_end_session(api: MemoryAPI, p: dict) -> dict:
    """下课收尾组合（v4.0 完整编排）。

    params:
      session_summary {subject, turns_total, hints_given, concepts_introduced,
                       mistakes_made, independence_pct, notes, facts?}
      error_patterns  错误模式列表（可选）
      session_id      当前会话ID（可选，缺省取最近 active）
      agent_id        实例标识
    """
    from .interaction import tool_analyze_session_errors

    agent_id = p.get("agent_id", "alex")
    session_summary = p.get("session_summary") or {}
    error_patterns = p.get("error_patterns") or []
    run_evo = p.get("run_evolution", True)
    session_id = p.get("session_id", "")
    db = api.conn

    today = datetime.now(CST).strftime("%Y-%m-%d")
    steps: dict[str, dict] = {}

    # ── ① GOODBYE + summary 级联（复用 mem_update_state 语义）──
    steps["goodbye"] = api.update_state(
        agent_id,
        {
            "ritual_state": "GOODBYE",
            "tutor_post_class_mode": True,
            "last_session_at": today,
            **({k: v for k, v in _summary_state_fields(session_summary).items() if v is not None}),
        },
    )
    try:
        if session_summary and session_id:
            _apply_summary_cascade(db, agent_id, session_id, session_summary)
            steps["goodbye"]["summary_cascade"] = True
    except Exception as e:  # noqa: BLE001
        steps["goodbye"]["summary_cascade"] = False
        steps["goodbye"]["cascade_error"] = str(e)

    # ── ② 课后密集区初始化 ──
    try:
        db.execute(
            """UPDATE agent_state SET tutor_post_class_rounds_left=?,
                   updated_at=datetime('now'), version=version+1 WHERE agent_id=?""",
            (ROUNDS_LEFT, agent_id),
        )
        db.commit()
        steps["rounds_initialized"] = {"success": True, "rounds_left": ROUNDS_LEFT}
    except Exception as e:  # noqa: BLE001
        steps["rounds_initialized"] = {"success": False, "error": str(e)}

    # ── ③ 错误模式入库（可选，C1 辅助通道）──
    steps["errors_analyzed"] = {"success": True, "skipped": not error_patterns}
    if error_patterns:
        try:
            steps["errors_analyzed"] = tool_analyze_session_errors(
                api, {"error_patterns": error_patterns, "agent_id": agent_id}
            )
        except Exception as e:  # noqa: BLE001
            steps["errors_analyzed"] = {"success": False, "error": str(e)}

    # ── ③.5 自动蒸馏 + ③.6 回填 sessions ──
    sid = session_id or _find_active_session_id(db, agent_id)
    steps["session_distilled"] = {"success": True, "skipped": not (session_summary and sid)}
    if session_summary and sid:
        try:
            distill_facts = session_summary.get("facts") or []
            if not distill_facts:
                notes = str(session_summary.get("notes") or "").strip()
                if notes:
                    distill_facts = [
                        {
                            "subject": session_summary.get("subject", ""),
                            "entity": session_summary.get("subject", "") or "session",
                            "fact": notes[:200],
                            "fact_type": "general",
                            "importance": 0.5,
                            "confidence": 0.6,
                        }
                    ]
            if distill_facts:
                steps["session_distilled"] = api.distill_facts(
                    agent_id, distill_facts, persona="tutor"
                )
            else:
                steps["session_distilled"] = {
                    "success": True,
                    "skipped": True,
                    "message": "无 facts/notes，跳过蒸馏",
                }
        except Exception as e:  # noqa: BLE001
            steps["session_distilled"] = {"success": False, "error": str(e)}

    steps["session_closed"] = {"success": True, "skipped": not sid}
    if sid:
        try:
            turn_count = session_summary.get("turns_total")
            if not turn_count:
                cnt = db.execute(
                    "SELECT COUNT(*) FROM episodes WHERE session_id=?", (sid,)
                ).fetchone()[0]
                turn_count = cnt or 0
            summary_text = str(session_summary.get("notes") or "")[:500]
            db.execute(
                """UPDATE sessions
                   SET ended_at=datetime('now'), turn_count=?, summary=?, status='closed'
                   WHERE id=?""",
                (turn_count, summary_text, sid),
            )
            db.commit()
            steps["session_closed"] = {"success": True, "session_id": sid, "status": "closed"}
        except Exception as e:  # noqa: BLE001
            steps["session_closed"] = {"success": False, "error": str(e)}

    # ── ④ 进化（C2 + C3）──
    steps["evolution"] = {"success": True, "skipped": not run_evo}
    if run_evo:
        try:
            evo = api.evolve(
                capabilities=["c2_review", "c3_triggers"],
                agent_id=agent_id,
                persona="tutor",
            )
            steps["evolution"] = {
                "success": evo.get("success", True),
                "auto_applied": evo.get("auto_applied", 0),
                "summary": evo.get("summary", ""),
            }
        except Exception as e:  # noqa: BLE001
            steps["evolution"] = {"success": False, "error": str(e)}

    # ── ⑤ COMPLETED ──
    try:
        steps["completed"] = api.update_state(agent_id, {"ritual_state": "COMPLETED"})
    except Exception as e:  # noqa: BLE001
        steps["completed"] = {"success": False, "error": str(e)}

    failed = [k for k, v in steps.items() if isinstance(v, dict) and not v.get("success", True)]
    return {
        "success": len(failed) == 0,
        "steps": steps,
        "failed_steps": failed,
        "message": "下课收尾完成" if not failed else f"以下步骤需补做: {', '.join(failed)}",
    }


def _summary_state_fields(summary: dict) -> dict:
    """summary 中映射到 agent_state 扩展列的字段（v4.0 update_state 级联子集）。"""
    mapping = {
        "mood": "tutor_mood",
        "energy": "tutor_energy",
        "focus": "tutor_focus",
    }
    out = {}
    for src, dst in mapping.items():
        v = summary.get(src)
        if v is not None:
            out[dst] = v
    return out


def _apply_summary_cascade(db, agent_id: str, session_id: str, summary: dict) -> None:
    """summary 级联：INSERT tutor_teaching_metrics + 复习进度计数（v4.0 语义）。"""
    db.execute(
        """INSERT INTO tutor_teaching_metrics
               (agent_id, session_id, session_date, subject, turns_total,
                hints_given, concepts_introduced, mistakes_made, independence_pct, notes)
           VALUES (?, ?, date('now'), ?, ?, ?, ?, ?, ?, ?)""",
        (
            agent_id,
            session_id,
            summary.get("subject", ""),
            summary.get("turns_total", 0),
            summary.get("hints_given", 0),
            summary.get("concepts_introduced", 0),
            summary.get("mistakes_made", 0),
            summary.get("independence_pct", 0),
            summary.get("notes", ""),
        ),
    )
    subject = summary.get("subject", "")
    if subject and summary.get("concepts_introduced") is not None:
        db.execute(
            """UPDATE tutor_learning_progress
               SET last_reviewed_at=datetime('now'),
                   review_count=review_count+1,
                   next_review_at=datetime('now','+1 day')
               WHERE agent_id=? AND subject=? AND status='in_progress'""",
            (agent_id, subject),
        )
    db.commit()


def _find_active_session_id(db, agent_id: str) -> str:
    row = db.execute(
        """SELECT id FROM sessions
           WHERE agent_id=? AND status='active'
           ORDER BY started_at DESC LIMIT 1""",
        (agent_id,),
    ).fetchone()
    return row["id"] if row else ""
