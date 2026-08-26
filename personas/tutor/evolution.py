#!/usr/bin/env python3
"""
personas.tutor.evolution — 导师专属进化能力（v4.0 C2/C3 完整平移）
===================================================================
能力签名：fn(conn, agent_id="", dry_run=False) -> dict（挂载到 core 进化框架）。
每次变更经 core.engine.evolution.log_event 落 evolution_events（不可变日志）。

C2 复习计划（v4.0 tune_sm2_params 平移）：
  mastery≥80/mastered → 7d；50-79 → 3d；<50/not_started → 1d
  该科目有活跃错误 → 间隔减半（≥1d）；conf 0.85(有错)/0.75
  只维护 next_review_at；target_id=行id 使通用回滚可用

C3 触发器进化（v4.0 evolve_triggers 平移）：
  从未触发 且 总教学记录≥5 且 不匹配当前活跃科目 → 休眠
  通用触发器（applicable_subjects 空）→ 保活
  critical 但不在当前科目范围 → 降级 high；conf 0.90/0.80
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from core.engine.evolution import log_event
from core.manifest import EvolutionCapability

CST = timezone(timedelta(hours=8))

# C3 通用触发器（applicable_subjects 为空但必须保活）
UNIVERSAL_TRIGGERS = ["overwhelm-signal", "flow-state-signal", "session-fatigue"]


def _c2_review(conn: sqlite3.Connection, agent_id: str = "", dry_run: bool = False) -> dict:
    """C2 复习计划（v4.0 完整规则）。"""
    subjects = conn.execute(
        """
        SELECT id, subject, status, mastery_level, next_review_at, last_reviewed_at
        FROM tutor_learning_progress
        WHERE agent_id=? AND status IN ('in_progress', 'not_started', 'deprioritized')
        """,
        (agent_id,),
    ).fetchall()

    recent_errors = conn.execute(
        """
        SELECT subject, COUNT(*) as err_count
        FROM tutor_error_patterns
        WHERE agent_id=? AND status='active'
        GROUP BY subject
        """,
        (agent_id,),
    ).fetchall()
    error_by_subject = {r["subject"]: r["err_count"] for r in recent_errors}

    adjustments = []
    today = datetime.now(CST)

    for subj in subjects:
        subject = subj["subject"]
        mastery = subj["mastery_level"] or 0
        status = subj["status"]

        if mastery >= 80 or status == "mastered":
            interval = 7
        elif mastery >= 50:
            interval = 3
        else:
            interval = 1

        if error_by_subject.get(subject, 0) > 0:
            interval = max(1, interval // 2)
            reason = f"mastery={mastery} 但有 {error_by_subject[subject]} 个活跃错误 → 间隔 {interval}d"
        else:
            reason = f"mastery={mastery} → 间隔 {interval}d"

        new_next_review = (today + timedelta(days=interval)).strftime("%Y-%m-%d")
        old_params = {"next_review_at": subj["next_review_at"]}
        new_params = {"next_review_at": new_next_review}
        changed = old_params != new_params
        confidence = 0.85 if error_by_subject.get(subject, 0) > 0 else 0.75

        if changed:
            adjustments.append(
                {
                    "subject": subject,
                    "old": old_params,
                    "new": new_params,
                    "reason": reason,
                    "confidence": confidence,
                }
            )

        if not dry_run:
            conn.execute(
                """
                UPDATE tutor_learning_progress
                SET next_review_at=?, last_reviewed_at=COALESCE(last_reviewed_at, datetime('now','localtime'))
                WHERE id=?
                """,
                (new_next_review, subj["id"]),
            )

        log_event(
            conn,
            "tutor_c2_review_schedule",
            "c2_review_schedule",
            "tutor_learning_progress",
            subj["id"],  # target_id=行id（通用回滚可用）
            old_params,
            new_params,
            confidence,
            reason,
            applied=changed,
            dry_run=dry_run,
            agent_id=agent_id,
        )

    if not dry_run:
        conn.commit()
    return {
        "capability": "C2 - 复习计划（按掌握度）",
        "subjects_analyzed": len(subjects),
        "adjustments_made": len(adjustments),
        "dry_run": dry_run,
        "adjustments": adjustments,
    }


def _c3_triggers(conn: sqlite3.Connection, agent_id: str = "", dry_run: bool = False) -> dict:
    """C3 触发器进化（v4.0 完整规则）。"""
    triggers = conn.execute(
        """
        SELECT id, name, severity, active, cooldown_turns,
               last_triggered_at_turn, applicable_subjects
        FROM tutor_pitfall_triggers
        WHERE agent_id=?
        """,
        (agent_id,),
    ).fetchall()

    active_subjects = [
        r["subject"]
        for r in conn.execute(
            "SELECT subject FROM tutor_learning_progress WHERE agent_id=? AND status='in_progress'",
            (agent_id,),
        ).fetchall()
    ]

    total_sessions_row = conn.execute(
        "SELECT COUNT(DISTINCT session_date) FROM tutor_teaching_metrics WHERE agent_id=?",
        (agent_id,),
    ).fetchone()
    total_sessions = total_sessions_row[0] if total_sessions_row else 10

    # 科目 → 触发器映射（数据化，避免硬编码）
    subject_trigger_map: dict[str, list[str]] = {}
    for trig in triggers:
        try:
            subjects = json.loads(trig["applicable_subjects"]) if trig["applicable_subjects"] else []
        except (json.JSONDecodeError, TypeError):
            subjects = []
        for subj in subjects:
            subject_trigger_map.setdefault(subj, []).append(trig["name"])

    for ut in UNIVERSAL_TRIGGERS:
        for s in active_subjects:
            if ut not in subject_trigger_map.get(s, []):
                subject_trigger_map.setdefault(s, []).append(ut)

    changes = []
    for trig in triggers:
        old_state = {
            "active": bool(trig["active"]),
            "severity": trig["severity"],
            "cooldown_turns": trig["cooldown_turns"],
        }
        new_active = bool(trig["active"])
        new_severity = trig["severity"]
        reason_parts = []

        # 规则1: 从未触发 + 总记录≥5 + 不匹配当前活跃科目 → 休眠
        if trig["last_triggered_at_turn"] == 0 and total_sessions >= 5:
            relevant = any(
                trig["name"] in subject_trigger_map.get(s, []) for s in active_subjects
            )
            if not relevant:
                new_active = False
                reason_parts.append(f"从未触发 + 不匹配当前活跃科目{active_subjects} → 休眠")

        # 规则2: 通用触发器（applicable_subjects 空）→ 保活
        try:
            trig_subjects = json.loads(trig["applicable_subjects"]) if trig["applicable_subjects"] else []
        except (json.JSONDecodeError, TypeError):
            trig_subjects = []
        if not trig_subjects:
            new_active = True

        # 规则3: critical 不在当前科目范围 → 降级 high
        if trig["severity"] == "critical" and new_active:
            relevant = any(
                trig["name"] in subject_trigger_map.get(s, []) for s in active_subjects
            )
            if not relevant:
                new_severity = "high"
                reason_parts.append("critical 但不在当前科目范围 → 降级为 high")

        new_state = {
            "active": new_active,
            "severity": new_severity,
            "cooldown_turns": trig["cooldown_turns"],
        }
        changed = old_state != new_state
        if changed:
            confidence = 0.90 if not new_active else 0.80
            reason = " | ".join(reason_parts) if reason_parts else "基于命中率分析自动调整"
            changes.append(
                {
                    "name": trig["name"],
                    "old": old_state,
                    "new": new_state,
                    "confidence": confidence,
                    "reason": reason,
                }
            )
            if not dry_run:
                conn.execute(
                    "UPDATE tutor_pitfall_triggers SET active=?, severity=? WHERE id=?",
                    (1 if new_active else 0, new_severity, trig["id"]),
                )
            log_event(
                conn,
                "tutor_c3_trigger_evolve",
                "c3_trigger_evolve",
                "tutor_pitfall_triggers",
                trig["id"],
                old_state,
                new_state,
                confidence,
                reason,
                applied=changed,
                dry_run=dry_run,
                agent_id=agent_id,
            )

    if not dry_run:
        conn.commit()
    return {
        "capability": "C3 - 触发器进化",
        "triggers_analyzed": len(triggers),
        "changes_made": len(changes),
        "dry_run": dry_run,
        "changes": changes,
    }


# 能力注册表（manifest.evolution 指向本模块时由 registry 挂载）
CAPABILITIES: dict[str, EvolutionCapability] = {
    "c2_review": EvolutionCapability(
        key="c2_review",
        description="按 mastery_level 重算复习间隔（v4.0 C2 完整规则）",
        run=_c2_review,
    ),
    "c3_triggers": EvolutionCapability(
        key="c3_triggers",
        description="低命中触发器自动休眠/降级（v4.0 C3 完整规则）",
        run=_c3_triggers,
    ),
}
