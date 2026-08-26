#!/usr/bin/env python3
"""
personas.tutor.hooks — get_context 扩展钩子（v4.0 get_context 教学字段完整平移）
==============================================================================
签名：fn(bundle: dict, agent_id: str, freshness_level: str) -> dict
返回 dict 合并进 bundle["persona_ext"]（core 零感知，只做加法）。

注入字段：
- student_state         教学状态扩展列（mood/energy/focus/数字信号/课后密集区）+ persona_anchor
- active_subjects       进行中科目（focus 时附 pending_topics）
- recent_errors         活跃错题 top2（按 frequency_history 长度）
- today_summary         今日教学指标聚合
- today_plan_suggestion 今日计划建议（继续 subject + 到期复习前3）
- knowledge_index       知识索引（category 分组，排除 subject_experience）
- tutor_memory_snippets tutor 专属检索（tutor_diary_fts / tutor_knowledge_fts，失败回退最近日记）
"""

from __future__ import annotations

import json
import sqlite3


def inject_tutor_context(bundle: dict, agent_id: str, freshness_level: str) -> dict:
    """注入教学专属上下文（v4.0 get_context hot/cold 数据块）。"""
    from core.db import get_db

    conn = get_db()
    ext: dict = {}

    # ── 1. student_state（扩展列白名单 + persona_anchor）──
    row = conn.execute(
        """SELECT tutor_mood, tutor_energy, tutor_focus,
                  tutor_ds_reply_interval_sec, tutor_ds_code_paste_speed,
                  tutor_ds_consecutive_short_replies, tutor_ds_question_frequency,
                  tutor_ds_flow_state, tutor_ds_total_questions,
                  tutor_post_class_mode, tutor_post_class_rounds_left,
                  current_task, ritual_state, turn_count, session_count, last_session_at,
                  state_json, updated_at
           FROM agent_state WHERE agent_id=?""",
        (agent_id,),
    ).fetchone()
    if row:
        state = {k: v for k, v in dict(row).items() if v is not None}
        # 复杂 JSON 字段解析
        try:
            parsed = json.loads(state.pop("state_json", "{}") or "{}")
            # persona_anchor = excitement_moments 末元素（v4.0 语义）
            excitement = parsed.get("excitement_moments", [])
            if excitement:
                state["persona_anchor"] = excitement[-1]
            state["recent_successes"] = parsed.get("recent_successes", [])
            state["recent_difficulties"] = parsed.get("recent_difficulties", [])
        except (json.JSONDecodeError, TypeError):
            pass
        ext["student_state"] = state

    focus_subject = (bundle.get("focus_subject") or "").strip()

    # ── 2. active_subjects ──
    active = conn.execute(
        """SELECT subject, topic, status, mastery_level, next_review_at
           FROM tutor_learning_progress
           WHERE agent_id=? AND status IN ('in_progress', 'not_started')
           ORDER BY status='in_progress' DESC, mastery_level ASC""",
        (agent_id,),
    ).fetchall()
    if active:
        subjects = [dict(r) for r in active]
        if focus_subject:
            for s in subjects:
                if focus_subject in s["subject"]:
                    pending = conn.execute(
                        """SELECT topic FROM tutor_learning_progress
                           WHERE agent_id=? AND subject=? AND status != 'mastered'""",
                        (agent_id, s["subject"]),
                    ).fetchall()
                    s["pending_topics"] = [r["topic"] for r in pending if r["topic"]]
        ext["active_subjects"] = subjects

    # ── 3. recent_errors（active 按 frequency_history 长度 top2）──
    errors = conn.execute(
        """SELECT id, pattern, category, subject, status, remedy, frequency_history
           FROM tutor_error_patterns
           WHERE agent_id=? AND status='active'
           ORDER BY LENGTH(frequency_history) DESC LIMIT 2""",
        (agent_id,),
    ).fetchall()
    if errors:
        err_list = []
        for r in errors:
            item = dict(r)
            try:
                item["frequency_history"] = json.loads(item.get("frequency_history") or "[]")
            except Exception:  # noqa: BLE001
                pass
            err_list.append(item)
        ext["recent_errors"] = err_list

    # ── 4. today_summary（今日教学指标）──
    try:
        ts = conn.execute(
            """SELECT COUNT(*) AS sessions, COALESCE(SUM(turns_total), 0) AS turns_total,
                      AVG(independence_pct) AS avg_independence
               FROM tutor_teaching_metrics
               WHERE agent_id=? AND session_date >= date('now', 'localtime')""",
            (agent_id,),
        ).fetchone()
        if ts and ts["sessions"]:
            ext["today_summary"] = {
                "sessions_today": ts["sessions"],
                "turns_total": ts["turns_total"],
                "avg_independence_pct": (
                    round(ts["avg_independence"], 1) if ts["avg_independence"] is not None else None
                ),
            }
    except sqlite3.Error:
        pass

    # ── 5. today_plan_suggestion（继续 subject + 到期复习前3）──
    ext["today_plan_suggestion"] = _build_plan_suggestion(conn, agent_id)

    # ── 6. knowledge_index（category 分组，排除 subject_experience）──
    try:
        rows = conn.execute(
            """SELECT category, COUNT(*) AS count, GROUP_CONCAT(title, ' | ') AS titles
               FROM tutor_teacher_knowledge
               WHERE category != 'subject_experience'
               GROUP BY category ORDER BY count DESC"""
        ).fetchall()
        if rows:
            ext["knowledge_index"] = [
                {
                    "category": r["category"],
                    "count": r["count"],
                    "sample_titles": (r["titles"] or "").split(" | ")[:3],
                }
                for r in rows
            ]
    except sqlite3.Error:
        pass

    # ── 7. tutor_memory_snippets（tutor 专属检索：diary + knowledge FTS）──
    snippets = _tutor_retrieve(conn, agent_id, focus_subject)
    if snippets:
        ext["tutor_memory_snippets"] = snippets

    return ext


def _build_plan_suggestion(conn, agent_id: str) -> str:
    """今日计划建议（v4.0 _build_plan_suggestion 语义）。"""
    parts = []
    state = conn.execute(
        "SELECT current_task FROM agent_state WHERE agent_id=?", (agent_id,)
    ).fetchone()
    if state and state["current_task"]:
        parts.append(f"继续 {state['current_task']}")
    due = conn.execute(
        """SELECT subject FROM tutor_learning_progress
           WHERE agent_id=? AND status='in_progress' AND next_review_at <= date('now')
           ORDER BY next_review_at ASC LIMIT 3""",
        (agent_id,),
    ).fetchall()
    if due:
        parts.append("复习到期: " + "、".join(r["subject"] for r in due))
    if not parts:
        return "开始新科目或回顾最近进度"
    return "；".join(parts)


def _tutor_retrieve(conn, agent_id: str, query: str, limit: int = 6) -> list[dict]:
    """tutor 专属检索（v4.0 cold 层 recent_memory_snippets 语义）。

    focus 有查询词 → diary_fts + knowledge_fts trigram 检索（≥3字），
                       2 字或未命中 → LIKE 兜底（v4.0 _like_fallback 语义）
    无查询词 → 最近 2 条日记摘要
    失败 → 回退最近 2 条日记
    """
    if query:
        hits: list[dict] = []
        q = '"' + query.replace('"', '""') + '"'
        # ── 通道1: FTS trigram（≥3 字才可靠）──
        if len(query.strip()) >= 3:
            try:
                for r in conn.execute(
                    """SELECT d.id, d.date, d.excerpt, bm25(tutor_diary_fts) AS rank
                       FROM tutor_diary_fts f JOIN tutor_diary_entries d ON d.id = f.rowid
                       WHERE tutor_diary_fts MATCH ? AND d.agent_id=?
                         AND d.date >= date('now', '-90 days')
                       ORDER BY rank LIMIT ?""",
                    (q, agent_id, limit),
                ).fetchall():
                    hits.append({"source": "diary", "date": r["date"], "excerpt": r["excerpt"]})
                for r in conn.execute(
                    """SELECT k.id, k.title, k.content, bm25(tutor_knowledge_fts) AS rank
                       FROM tutor_knowledge_fts f JOIN tutor_teacher_knowledge k ON k.id = f.rowid
                       WHERE tutor_knowledge_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (q, limit),
                ).fetchall():
                    hits.append(
                        {
                            "source": "knowledge",
                            "title": r["title"],
                            "excerpt": (r["content"] or "")[:200].replace("\n", " "),
                        }
                    )
            except sqlite3.Error:
                pass
        # ── 通道2: LIKE 兜底（<3 字或 trigram 未命中）──
        if not hits:
            like = f"%{query}%"
            try:
                for r in conn.execute(
                    """SELECT date, excerpt FROM tutor_diary_entries
                       WHERE agent_id=? AND excerpt LIKE ? ESCAPE '\\'
                       ORDER BY date DESC LIMIT ?""",
                    (agent_id, like, limit),
                ).fetchall():
                    hits.append({"source": "diary", "date": r["date"], "excerpt": r["excerpt"]})
                for r in conn.execute(
                    """SELECT title, content FROM tutor_teacher_knowledge
                       WHERE title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\'
                       ORDER BY id DESC LIMIT ?""",
                    (like, like, limit),
                ).fetchall():
                    hits.append(
                        {
                            "source": "knowledge",
                            "title": r["title"],
                            "excerpt": (r["content"] or "")[:200].replace("\n", " "),
                        }
                    )
            except sqlite3.Error:
                pass
        if hits:
            return hits[:limit]

    # 无查询或检索失败 → 最近 2 条日记
    try:
        rows = conn.execute(
            """SELECT date, excerpt FROM tutor_diary_entries
               WHERE agent_id=? ORDER BY date DESC LIMIT 2""",
            (agent_id,),
        ).fetchall()
        return [{"source": "diary", "date": r["date"], "excerpt": r["excerpt"]} for r in rows]
    except sqlite3.Error:
        return []
