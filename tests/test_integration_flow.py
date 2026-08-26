#!/usr/bin/env python3
"""端到端集成测试：新会话协议全链路（v4.0 test_integration_flow 移植）。"""

import json


def test_full_session_flow(api, persona_ctx):
    """上课 → 每轮 → 蒸馏 → 下课 → 日记 → 进化 → 健康，全链路断言。"""
    # 上课
    s = api.start_session("alex", "tutor", subject="python", topic="闭包")
    sid = s["session_id"]
    assert s["status"] == "active"

    # 上下文（cold）
    ctx = api.get_context("alex", "tutor", freshness_level="cold", focus_subject="python")
    assert ctx["token_budget_limit"] == 2000
    assert "persona_ext" in ctx
    assert ctx["persona_ext"].get("active_subjects")  # 种子 LP

    # 每轮观察
    from personas.tutor.tools.interaction import tool_record_interaction

    r = tool_record_interaction(
        api, {"agent_id": "alex", "user_message": "闭包是什么？", "current_topic": "闭包", "session_id": sid}
    )
    assert r["success"] is True
    assert r["signals"]["turn_count"] >= 1
    assert r["episode_recorded"] is True

    # 补 assistant 回合
    api.log_episode(sid, "assistant", "闭包 = 函数捕获外层变量", agent_id="alex", topic="闭包")

    # 回忆
    rec = api.recall_episodes(session_id=sid)
    assert rec["count"] >= 2

    # 蒸馏
    d = api.distill_facts(
        "alex",
        [{"entity": "闭包", "fact": "学生能独立解释闭包原理", "fact_type": "strength", "importance": 0.8}],
        persona="tutor",
    )
    assert d["applied"] or d["upserted"]

    # 检索到蒸馏结果
    hits = api.retrieve("闭包原理", "alex", "tutor")
    assert any("闭包" in h["excerpt"] for h in hits)

    # 下课
    from personas.tutor.tools.session import tool_end_session

    r4 = tool_end_session(
        api,
        {
            "agent_id": "alex",
            "session_id": sid,
            "session_summary": {
                "subject": "python",
                "turns_total": 5,
                "concepts_introduced": 1,
                "notes": "讲完闭包，效果良好",
            },
        },
    )
    assert r4["success"] is True, f"下课失败: {r4['failed_steps']}"
    steps = r4["steps"]
    assert set(steps.keys()) == {
        "goodbye", "rounds_initialized", "errors_analyzed",
        "session_distilled", "session_closed", "evolution", "completed",
    }
    assert steps["rounds_initialized"]["rounds_left"] == 8
    assert steps["session_closed"]["status"] == "closed"

    # 会话已关闭 + 指标入库
    sess = api.conn.execute("SELECT status FROM sessions WHERE id=?", (sid,)).fetchone()
    assert sess["status"] == "closed"
    metrics = api.conn.execute(
        "SELECT COUNT(*) FROM tutor_teaching_metrics WHERE agent_id='alex'"
    ).fetchone()[0]
    assert metrics >= 1

    # 日记
    from personas.tutor.tools.diary import tool_write_diary

    r6 = tool_write_diary(
        api, {"agent_id": "alex", "content": "今天讲了闭包，他理解得很快。\n\n心情：开心"}
    )
    assert r6["success"] is True
    assert "diary" in r6["filepath"]

    # 健康
    h = api.health()
    assert h["healthy"] is True
    assert "retrieval_stats" in h


def test_end_session_with_none_summary(api, persona_ctx):
    """session_summary=None 下课不抛错（BUG-1 修复验证）。"""
    from personas.tutor.tools.session import tool_end_session

    s = api.start_session("alex", "tutor", subject="python")
    sid = s["session_id"]
    r = tool_end_session(api, {"agent_id": "alex", "session_id": sid, "session_summary": None})
    assert r["success"] is True
