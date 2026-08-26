#!/usr/bin/env python3
"""
personas.guide.tools.guide — 引导助手 3 个核心工具（轻量，仅引导与调度）
=========================================================================
guide_status         判定是否需要引导（纯读）
guide_create_persona 收集参数建档（core_memory 配置档案）+ 推荐已部署人格
guide_switch_persona 切换人格 + 标记 onboarded + 状态确认（自包含 SQL）

设计原则：
- 不做实际任务：不调 start_session/log_episode/distill，不承载会话
- 不动态生成 manifest/代码：档案仅存 core_memory（persona_profile:<name>）
- 返回精简：available_personas 只带 name+display_name
- 自包含：switch 复制 registry 的 UPSERT SQL 走 api.conn（避开 db_path 分裂坑）
"""

from __future__ import annotations

import json
from datetime import datetime

from core.api import MemoryAPI
from core import manifest as mf

ALLOWED_TONES = ("严谨", "轻松", "鼓励型")

# 关键词推荐规则：(可执行人格, 触发关键词元组)，按序匹配
_RECOMMEND_RULES = [
    ("coder", ("编程", "代码", "开发", "软件", "工程", "debug", "任务", "项目", "技术", "bug")),
    ("tutor", ("学习", "教学", "辅导", "课程", "答疑", "考试", "知识", "教育", "导师")),
]


def _agent_state(api: MemoryAPI, agent_id: str) -> dict:
    """读取 agent 状态（active_persona + onboarded），无行时按未引导处理。"""
    st = api.get_state(agent_id)
    if not st["exists"]:
        return {"active_persona": "", "onboarded": False}
    s = st["state"]
    state_json = s.get("state_json") or {}
    if isinstance(state_json, str):
        try:
            state_json = json.loads(state_json)
        except (json.JSONDecodeError, TypeError):
            state_json = {}
    return {
        "active_persona": s.get("active_persona", ""),
        "onboarded": bool(state_json.get("onboarded")),
    }


def _available_personas() -> list[dict]:
    """已注册的可选人格（排除 guide 自身），只带 name+display_name 省 token。"""
    return [
        {"name": m.name, "display_name": m.display_name}
        for m in mf.all_manifests()
        if m.name != "guide"
    ]


def _recommend(api: MemoryAPI, text: str) -> str | None:
    """按关键词推荐已部署人格；未命中返回 None（由 LLM 引导用户选择）。"""
    hay = (text or "").lower()
    for persona, keywords in _RECOMMEND_RULES:
        if any(k in hay for k in keywords):
            try:
                m = mf.get(persona)
            except LookupError:
                m = None
            if m is not None:
                return persona
    return None


def tool_status(api: MemoryAPI, p: dict) -> dict:
    """判定当前 agent 是否需要引导（只读，无副作用）。

    params: agent_id（默认 "default"）
    """
    agent_id = p.get("agent_id", "default")
    state = _agent_state(api, agent_id)
    onboarded = state["onboarded"] and bool(state["active_persona"])
    return {
        "success": True,
        "status": "already_onboarded" if onboarded else "needs_onboarding",
        "active_persona": state["active_persona"],
        "available_personas": _available_personas(),
        "next_steps": (
            "按当前人格继续工作"
            if onboarded
            else "收集用途/语气/领域参数 → guide_create_persona → guide_switch_persona"
        ),
    }


def tool_create_persona(api: MemoryAPI, p: dict) -> dict:
    """创建人格配置档案（core_memory）+ 推荐已部署人格。

    params:
      agent_id（默认 default）, name(必填 ≤50), purpose(必填), tone(必填枚举), domain(可选)
    """
    agent_id = p.get("agent_id", "default")
    name = (p.get("name") or "").strip()
    purpose = (p.get("purpose") or "").strip()
    tone = (p.get("tone") or "").strip()
    domain = (p.get("domain") or "").strip()

    # 校验
    if not name or not purpose:
        return {"success": False, "error": "name 与 purpose 不能为空"}
    if len(name) > 50:
        return {"success": False, "error": f"name 超过 50 字符（当前 {len(name)}）"}
    if tone not in ALLOWED_TONES:
        return {"success": False, "error": f"tone 必须为 {'/'.join(ALLOWED_TONES)} 之一"}

    profile = {
        "name": name,
        "purpose": purpose,
        "tone": tone,
        "domain": domain,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    api.set_core_block(agent_id, f"persona_profile:{name}", json.dumps(profile, ensure_ascii=False))

    recommended = _recommend(api, f"{domain} {purpose}")
    return {
        "success": True,
        "profile": profile,
        "recommended_persona": recommended,
        "next_step": f"guide_switch_persona(agent_id, persona=\"{recommended or '<选择人格>'}\")",
    }


def tool_switch_persona(api: MemoryAPI, p: dict) -> dict:
    """切换到目标人格 + 标记 onboarded + 状态确认。

    params:
      agent_id（默认 default）, persona(必填，须已注册且非 guide)
    """
    agent_id = p.get("agent_id", "default")
    persona = (p.get("persona") or "").strip()

    if not persona:
        return {"success": False, "error": "persona 不能为空"}
    if persona == "guide":
        return {"success": False, "error": "不能切换到引导助手自身"}
    try:
        m = mf.get(persona)
    except LookupError:
        return {"success": False, "error": f"人格 '{persona}' 未注册"}
    if m is None:
        return {"success": False, "error": f"人格 '{persona}' 未注册"}

    conn = api.conn
    before_row = conn.execute(
        "SELECT active_persona FROM agent_state WHERE agent_id=?", (agent_id,)
    ).fetchone()
    before = before_row["active_persona"] if before_row else ""

    # 自包含 UPSERT（与 registry.switch_persona 一致，但走 api.conn 尊重 db_path）
    conn.execute(
        """INSERT INTO agent_state (agent_id, active_persona, updated_at, version)
           VALUES (?, ?, datetime('now'), 1)
           ON CONFLICT(agent_id) DO UPDATE SET
               active_persona=excluded.active_persona,
               updated_at=datetime('now'),
               version=version+1""",
        (agent_id, persona),
    )
    # 标记引导完成（state_json，update_state 自动路由）
    api.update_state(agent_id, {"onboarded": True})
    conn.commit()

    return {
        "success": True,
        "status": "onboarded",
        "agent_id": agent_id,
        "before": before,
        "active_persona": persona,
        "message": f"已切换到「{m.display_name}」人格。引导完成。",
    }
