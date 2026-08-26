#!/usr/bin/env python3
"""进化引擎测试：log_event dry_run 语义、C2/C3 dry_run/应用、revert 分支（v4.0 移植 + 表名 tutor_*）。"""

import json

from core.engine.evolution import log_event, revert_evolution


def _seed_lp(db, agent_id="alex"):
    db.execute(
        """INSERT INTO tutor_learning_progress (agent_id, subject, topic, status, mastery_level, next_review_at)
           VALUES (?, 'java', '', 'in_progress', 60, date('now','-3 days'))""",
        (agent_id,),
    )
    db.execute(
        """INSERT INTO tutor_learning_progress (agent_id, subject, topic, status, mastery_level, next_review_at)
           VALUES (?, 'go', '', 'in_progress', 90, date('now','-7 days'))""",
        (agent_id,),
    )
    db.commit()


def test_log_event_dry_run_semantics(db):
    """dry_run 时 log_event 写入事件但 applied=0。"""
    ev_id = log_event(
        db, "test_evt", "c2_review", "tutor_learning_progress", 1,
        {"next_review_at": "a"}, {"next_review_at": "b"},
        0.9, "test", applied=True, dry_run=True, agent_id="alex",
    )
    db.commit()
    row = db.execute("SELECT * FROM evolution_events WHERE id=?", (ev_id,)).fetchone()
    assert row["applied"] == 0
    assert row["agent_id"] == "alex"


def test_c2_review_applies_and_events(db):
    """C2 真实应用：更新 next_review_at + 落 evolution_events。"""
    from personas.tutor.evolution import _c2_review

    _seed_lp(db)
    result = _c2_review(db, agent_id="alex", dry_run=False)
    assert result["adjustments_made"] >= 2  # 含 conftest 种子的 python/network
    rows = db.execute(
        "SELECT next_review_at FROM tutor_learning_progress WHERE subject='java'"
    ).fetchone()
    assert rows["next_review_at"] is not None
    ev = db.execute("SELECT COUNT(*) FROM evolution_events WHERE capability='c2_review_schedule'").fetchone()[0]
    assert ev >= 2


def test_c2_review_dry_run_no_write(db):
    """C2 dry_run：不写库但返回分析。"""
    from personas.tutor.evolution import _c2_review

    _seed_lp(db)
    before = db.execute("SELECT next_review_at FROM tutor_learning_progress WHERE subject='java'").fetchone()[0]
    result = _c2_review(db, agent_id="alex", dry_run=True)
    assert result["adjustments_made"] >= 2
    after = db.execute("SELECT next_review_at FROM tutor_learning_progress WHERE subject='java'").fetchone()[0]
    assert after == before


def test_c3_trigger_evolve(db):
    """C3：从未触发 + 不匹配活跃科目 → 休眠。"""
    from personas.tutor.evolution import _c3_triggers

    db.execute(
        """INSERT INTO tutor_pitfall_triggers (agent_id, name, trigger_keywords, context_pattern,
               mandatory_action, severity, applicable_subjects)
           VALUES ('alex', '无关触发器', '["zzz"]', '', '无', 'warning', '["不存在科目"]')"""
    )
    db.execute(
        """INSERT INTO tutor_teaching_metrics (agent_id, session_date, subject)
           VALUES ('alex', date('now'), 'python')"""
    )
    # 造 5 个不同日期的 teaching_metrics 满足 total_sessions>=5
    for i in range(1, 5):
        db.execute(
            f"INSERT INTO tutor_teaching_metrics (agent_id, session_date, subject) VALUES ('alex', date('now','-{i} days'), 'python')"
        )
    db.commit()
    result = _c3_triggers(db, agent_id="alex", dry_run=False)
    assert result["changes_made"] == 1
    row = db.execute("SELECT active FROM tutor_pitfall_triggers WHERE name='无关触发器'").fetchone()
    assert row["active"] == 0


def test_revert_generic_column(db):
    """通用列回滚：按 target_id 恢复 change_before。"""
    db.execute(
        "INSERT INTO tutor_learning_progress (agent_id, subject, topic, status, mastery_level, next_review_at)"
        " VALUES ('alex', 'java', '', 'in_progress', 50, '2026-08-01')"
    )
    row = db.execute("SELECT id FROM tutor_learning_progress WHERE subject='java'").fetchone()
    target_id = row["id"]
    ev_id = log_event(
        db, "tutor_c2_review_schedule", "c2_review_schedule", "tutor_learning_progress", target_id,
        {"next_review_at": "2026-08-01"}, {"next_review_at": "2026-08-27"},
        0.75, "test", applied=True, dry_run=False, agent_id="alex",
    )
    db.commit()
    # 先应用 change_after
    db.execute("UPDATE tutor_learning_progress SET next_review_at='2026-08-27' WHERE id=?", (target_id,))
    db.commit()
    result = revert_evolution(db, ev_id)
    assert result["success"] is True
    restored = db.execute("SELECT next_review_at FROM tutor_learning_progress WHERE id=?", (target_id,)).fetchone()
    assert restored["next_review_at"] == "2026-08-01"


def test_revert_c1_delete(db):
    """C1 回滚：删除错误模式行。"""
    db.execute(
        "INSERT INTO tutor_error_patterns (agent_id, pattern, category, root_cause, subject, status)"
        " VALUES ('alex', 'p-test', 'c-test', '', '', 'active')"
    )
    row = db.execute("SELECT id FROM tutor_error_patterns WHERE pattern='p-test'").fetchone()
    target_id = row["id"]
    ev_id = log_event(
        db, "tutor_llm_pattern_discovery", "llm_pattern_discovery", "tutor_error_patterns", target_id,
        {"id": target_id}, {"pattern": "p-test"},
        0.9, "test", applied=True, dry_run=False, agent_id="alex",
    )
    db.commit()
    result = revert_evolution(db, ev_id)
    assert result["success"] is True
    assert db.execute("SELECT COUNT(*) FROM tutor_error_patterns WHERE id=?", (target_id,)).fetchone()[0] == 0
