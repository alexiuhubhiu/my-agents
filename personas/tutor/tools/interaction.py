#!/usr/bin/env python3
"""
personas.tutor.tools.interaction — 每轮观察 / 错误模式入库 / 触发器匹配
=======================================================================
v4.0 tool_record_interaction / tool_analyze_session_errors / _match_triggers 完整平移。
适配：student_state→agent_state(agent_id)、error_patterns→tutor_error_patterns、
pitfall_triggers→tutor_pitfall_triggers、_write_episode→api.log_episode、
log_event→core.engine.evolution.log_event(带 agent_id)。

缺陷修复（相对 v4.0）：
- 空消息分支的短回复计数与主分支语义一致（主分支有短才 +1，空消息不再无条件 +1）。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from core.api import MemoryAPI

CST = timezone(timedelta(hours=8))
logger = logging.getLogger("tutor")

# 场景触发器缓存（60s TTL，避免每轮重复全量查询；无外部依赖的简易实现）
_TRIGGER_CACHE: dict[str, Any] = {"ts": 0.0, "rows": None}
_TRIGGER_TTL = 60.0


def tool_record_interaction(api: MemoryAPI, p: dict) -> dict:
    """每轮唯一观察入口（v4.0 完整算法）。

    params:
      user_message 学生消息原文
      current_topic 当前主题
      session_id   会话ID（传入自动写 user 回合）
      agent_id     实例标识（默认 alex）
    """
    agent_id = p.get("agent_id", "alex")
    user_message = p.get("user_message", "")
    current_topic = p.get("current_topic", "")
    session_id = p.get("session_id", "")
    db = api.conn

    # ── 空消息分支（独立，返回早）──
    if not user_message:
        return _handle_empty_message(db, agent_id)

    now = datetime.now(CST)
    now_iso = now.isoformat()

    state = _state_row(db, agent_id)

    # 1. 回复间隔（默认 30s）
    reply_interval = 30.0
    if state and state["tutor_ds_last_interaction_at"]:
        try:
            last_dt = datetime.fromisoformat(state["tutor_ds_last_interaction_at"])
            reply_interval = (now - last_dt).total_seconds()
        except Exception:  # noqa: BLE001
            pass

    # 2. 代码速度（fenced 块 + 缩进块双正则）
    code_blocks = re.findall(r"```(?:[^\n`]*\n)?(.*?)```", user_message, re.DOTALL)
    if not code_blocks:
        code_blocks = re.findall(
            r"(?m)^([ \t]{2,}[^\n]+(?:[ \t]*\n[ \t]{2,}[^\n]+)+)", user_message
        )
    total_code_chars = sum(len(b) for b in code_blocks)
    if reply_interval > 0 and total_code_chars > 0:
        chars_per_min = total_code_chars / (reply_interval / 60.0)
        code_speed = "burst" if chars_per_min > 500 else ("slow" if chars_per_min < 100 else "normal")
    else:
        code_speed = "normal"

    # 3. 短回复（<10 字符连续计数）
    msg_len = len(user_message.strip())
    is_short = msg_len < 10
    prev_short = state["tutor_ds_consecutive_short_replies"] if state else 0
    new_short_count = prev_short + 1 if is_short else 0

    # 4. 提问频率（ASCII + 全角）
    question_marks = user_message.count("?") + user_message.count("？")
    prev_questions = state["tutor_ds_total_questions"] if state else 0
    new_total_questions = prev_questions + question_marks
    new_turn = (state["turn_count"] if state else 0) + 1
    question_frequency = new_total_questions / max(new_turn, 1)

    # 5. 心流判定（顺序严格：flow → struggle → distracted → neutral）
    if reply_interval < 15 and not is_short and code_speed != "burst":
        flow_state = "flow"
    elif new_short_count >= 3 or question_frequency > 0.5:
        flow_state = "struggle"
    elif reply_interval > 120:
        flow_state = "distracted"
    else:
        flow_state = "neutral"

    # 6. 写回状态（扩展列 + turn_count）
    updates = {
        "ds_reply_interval_sec": round(reply_interval, 1),
        "ds_code_paste_speed": code_speed,
        "ds_consecutive_short_replies": new_short_count,
        "ds_question_frequency": round(question_frequency, 3),
        "ds_flow_state": flow_state,
        "ds_last_interaction_at": now_iso,
        "ds_total_questions": new_total_questions,
        "turn_count": new_turn,
    }
    _apply_signal_updates(db, agent_id, updates)

    # 7. 触发器匹配
    trigger_result = _match_triggers(api, user_message, current_topic, agent_id)

    # 8. 情节沉淀（user 回合）
    episode_id = None
    if session_id:
        try:
            episode_id = api.log_episode(
                session_id=session_id,
                role="user",
                content=user_message,
                agent_id=agent_id,
                topic=current_topic,
            ).get("id")
        except Exception as e:  # noqa: BLE001
            logger.warning("record_interaction 写 episode 失败（不影响主流程）: %s", e)

    return {
        "success": True,
        "signals": {
            "reply_interval_sec": updates["ds_reply_interval_sec"],
            "code_paste_speed": code_speed,
            "consecutive_short_replies": new_short_count,
            "question_frequency": updates["ds_question_frequency"],
            "flow_state": flow_state,
            "turn_count": new_turn,
            "message_length": msg_len,
            "code_chars": total_code_chars,
            "questions_in_message": question_marks,
        },
        "triggers": trigger_result["triggers"] if trigger_result["triggered"] else [],
        "episode_id": episode_id,
        "episode_recorded": episode_id is not None,
    }


def _handle_empty_message(db, agent_id: str) -> dict:
    """空消息分支：仅更新时间戳/间隔/计数（修复 v4.0 短回复无条件 +1）。"""
    now = datetime.now(CST)
    now_iso = now.isoformat()
    state = _state_row(db, agent_id)
    reply_interval = 30.0
    if state and state["tutor_ds_last_interaction_at"]:
        try:
            reply_interval = (now - datetime.fromisoformat(state["tutor_ds_last_interaction_at"])).total_seconds()
        except Exception:  # noqa: BLE001
            pass
    # 修复：空消息不算短回复（与主分支「有短才 +1」语义一致）
    prev_short = state["tutor_ds_consecutive_short_replies"] if state else 0
    new_short = prev_short if prev_short == 0 else 0
    new_turn = (state["turn_count"] if state else 0) + 1
    _apply_signal_updates(
        db,
        agent_id,
        {
            "ds_reply_interval_sec": round(reply_interval, 1),
            "ds_code_paste_speed": "normal",
            "ds_consecutive_short_replies": new_short,
            "ds_flow_state": "neutral",
            "ds_last_interaction_at": now_iso,
            "turn_count": new_turn,
        },
    )
    return {
        "success": True,
        "signals": {
            "reply_interval_sec": round(reply_interval, 1),
            "code_paste_speed": "normal",
            "consecutive_short_replies": new_short,
            "question_frequency": 0.0,
            "flow_state": "neutral",
            "turn_count": new_turn,
        },
        "triggers": [],
    }


def _state_row(db, agent_id: str):
    row = db.execute(
        "SELECT tutor_ds_last_interaction_at, tutor_ds_consecutive_short_replies, "
        "tutor_ds_total_questions, turn_count FROM agent_state WHERE agent_id=?",
        (agent_id,),
    ).fetchone()
    # dict 化：缺失扩展列时安全返回 None（sqlite3.Row 访问缺失键会抛 IndexError）
    return dict(row) if row else None


def _apply_signal_updates(db, agent_id: str, updates: dict) -> None:
    """写回信号字段（tutor_ 前缀列 + turn_count），乐观锁 version+1。"""
    set_clause = ", ".join(f"tutor_{k}=?" for k in updates if not k.startswith("turn"))
    values = [updates[k] for k in updates if not k.startswith("turn")]
    if "turn_count" in updates:
        set_clause = f"{set_clause}, turn_count=?" if set_clause else "turn_count=?"
        values.append(updates["turn_count"])
    set_clause += ", updated_at=datetime('now'), version=version+1"
    values.append(agent_id)
    db.execute(f"UPDATE agent_state SET {set_clause} WHERE agent_id=?", values)
    db.commit()


def tool_analyze_session_errors(api: MemoryAPI, p: dict) -> dict:
    """LLM 辅助错误模式入库（v4.0 完整平移：去重 + evolution_events 记录）。"""
    db = api.conn
    error_patterns = p.get("error_patterns", [])
    agent_id = p.get("agent_id", "alex")

    if not error_patterns:
        return {"success": False, "error": "error_patterns 不能为空"}

    existing = db.execute(
        "SELECT pattern, category FROM tutor_error_patterns WHERE agent_id=?", (agent_id,)
    ).fetchall()
    existing_patterns = {(r["pattern"].lower(), r["category"]) for r in existing}

    applied, skipped = [], []
    for ep in error_patterns:
        pattern = ep.get("pattern", "")
        category = ep.get("category", "")
        root_cause = ep.get("root_cause", "")
        subject = ep.get("subject", "")
        confidence = ep.get("confidence", 0.8)
        remedy = ep.get("remedy", "")

        if not pattern or not category:
            skipped.append({"pattern": pattern, "reason": "缺少 pattern 或 category"})
            continue
        if (pattern.lower(), category) in existing_patterns:
            skipped.append({"pattern": pattern, "reason": "已存在相同模式"})
            continue

        db.execute(
            """
            INSERT INTO tutor_error_patterns
                (agent_id, pattern, category, root_cause, subject, first_seen_at, last_seen_at,
                 frequency_history, status, remedy)
            VALUES (?, ?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'), ?, 'active', ?)
            """,
            (agent_id, pattern, category, root_cause, subject, json.dumps([1]), remedy),
        )
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        from core.engine.evolution import log_event

        log_event(
            db,
            "tutor_llm_pattern_discovery",
            "llm_pattern_discovery",
            "tutor_error_patterns",
            new_id,
            {},
            {
                "pattern": pattern,
                "category": category,
                "root_cause": root_cause,
                "subject": subject,
                "confidence": confidence,
                "remedy": remedy,
            },
            confidence,
            f"LLM 辅助发现: {pattern} (置信度 {confidence:.0%})",
            applied=True,
            dry_run=False,
            agent_id=agent_id,
        )
        applied.append({"id": new_id, "pattern": pattern, "category": category, "confidence": confidence})
        existing_patterns.add((pattern.lower(), category))

    db.commit()
    return {
        "success": True,
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "applied": applied,
        "skipped": skipped,
        "message": f"LLM 分析完成: {len(applied)} 个新错误模式入库, {len(skipped)} 个跳过",
    }


def _match_triggers(api: MemoryAPI, context_text: str, current_topic: str = "", agent_id: str = "alex") -> dict:
    """场景触发器匹配（v4.0 完整平移：关键词三分支 + 冷却 + severity 排序）。

    适配：tutor_pitfall_triggers 按 agent_id 过滤；TTLCache 改为简易时间戳缓存。
    """
    if not context_text:
        return {"triggered": False, "triggers": []}

    db = api.conn
    state = db.execute("SELECT turn_count FROM agent_state WHERE agent_id=?", (agent_id,)).fetchone()
    current_turn = state["turn_count"] if state else 0

    # 60s TTL 缓存（C3 改动后由 TTL 自然失效）
    global _TRIGGER_CACHE
    if _TRIGGER_CACHE["rows"] is None or (time.time() - _TRIGGER_CACHE["ts"]) > _TRIGGER_TTL:
        _TRIGGER_CACHE["rows"] = db.execute(
            """
            SELECT id, name, trigger_keywords, mandatory_action,
                   severity, cooldown_turns, last_triggered_at_turn
            FROM tutor_pitfall_triggers
            WHERE agent_id=? AND active=1
            """,
            (agent_id,),
        ).fetchall()
        _TRIGGER_CACHE["ts"] = time.time()
    triggers = _TRIGGER_CACHE["rows"]

    triggered_list = []
    for trig in triggers:
        keywords_str = trig["trigger_keywords"]
        try:
            keywords = json.loads(keywords_str)
        except Exception:  # noqa: BLE001
            keywords = keywords_str.split(",") if isinstance(keywords_str, str) else []

        # 关键词匹配（中文子串 / \w 词边界 / 纯标点）
        matched_kw = None
        for kw in keywords:
            if re.search(r"[一-鿿]", kw):
                if kw in context_text:
                    matched_kw = kw
                    break
                continue
            if re.search(r"\w", kw):
                pattern = re.escape(kw)
                if re.search(
                    r"(?<![A-Za-z0-9_])" + pattern + r"(?![A-Za-z0-9_])",
                    context_text,
                    re.IGNORECASE,
                ):
                    matched_kw = kw
                    break
            else:
                if kw in context_text:
                    matched_kw = kw
                    break
        if not matched_kw:
            continue

        # 冷却检测（从未触发过的不参与冷却）
        last_turn = trig["last_triggered_at_turn"] or 0
        cooldown = trig["cooldown_turns"] or 10
        cooldown_remaining = max(0, cooldown - (current_turn - last_turn))
        if last_turn > 0 and cooldown_remaining > 0:
            continue

        triggered_list.append(
            {
                "id": trig["id"],
                "name": trig["name"],
                "matched_keyword": matched_kw,
                "mandatory_action": trig["mandatory_action"],
                "severity": trig["severity"],
                "cooldown_remaining": cooldown_remaining,
            }
        )
        db.execute(
            "UPDATE tutor_pitfall_triggers SET last_triggered_at_turn=? WHERE id=?",
            (current_turn, trig["id"]),
        )

    db.commit()
    if triggered_list:
        severity_order = {"critical": 0, "high": 1, "medium": 2, "warning": 3, "info": 4}
        triggered_list.sort(key=lambda x: severity_order.get(x["severity"], 9))
        return {"triggered": True, "triggers": triggered_list}
    return {"triggered": False, "triggers": []}
