#!/usr/bin/env python3
"""
cli.py — 人设管理 CLI（不依赖 MCP SDK）
========================================
用法：
  python cli.py init                  # 初始化数据库（core + 全部人设 Schema 扩展）
  python cli.py personas              # 列出人设
  python cli.py switch <agent> <persona>   # 切换人设
  python cli.py context <agent> [persona]  # 预览聚合上下文（验证数据流转）
  python cli.py smoke                  # 端到端冒烟测试（写/读/切换/进化）
"""

from __future__ import annotations

import json
import sys

from core import registry
from core.api import MemoryAPI
from core.db import get_db
from core.schema import CORE_SCHEMA_SQL


def cmd_init() -> None:
    conn = get_db()
    conn.executescript(CORE_SCHEMA_SQL)
    conn.commit()
    # 记录迁移版本（与 core.migrations 序贯机制对齐）
    from core.migrations import SCHEMA_VERSION
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    for name in _personas():
        registry.load_persona(name, api := MemoryAPI())
        print(f"  ✓ persona '{name}' Schema 扩展已应用")
    print("数据库初始化完成:", conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0], "张表", f"(user_version={SCHEMA_VERSION})")


def cmd_personas() -> None:
    api = MemoryAPI()
    for name in _personas():
        registry.load_persona(name, api)  # 触发 manifest 注册
    for p in registry.list_personas():
        print(f"  {p['name']:<12} {p['display_name']:<10} v{p['version']}  tools={p['tools']}  schema_ext={p['schema_ext']}  loaded={p['loaded']}")


def cmd_switch(agent: str, persona: str) -> None:
    registry.load_persona(persona, MemoryAPI())
    result = registry.switch_persona(agent, persona)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_context(agent: str, persona: str = "") -> None:
    api = MemoryAPI()
    if persona:
        registry.load_persona(persona, api)
    ctx = api.get_context(agent, persona)
    print(json.dumps(ctx, ensure_ascii=False, indent=2, default=str))


def cmd_smoke() -> None:
    """端到端验证：会话 → 情节 → 蒸馏 → 检索 → 切换 → 进化 → 健康。"""
    api = MemoryAPI()
    registry.load_persona("tutor", api)
    registry.switch_persona("alex", "tutor")

    # 会话
    s = api.start_session("alex", "tutor", subject="HCIE-Datacom", topic="ISIS")
    sid = s["session_id"]
    print("1. start_session:", s["reused"] and "reused" or "new", sid[:8], "...")

    # 情节
    api.log_episode(sid, "user", "ISIS 的 LSP 泛洪机制讲一下？", agent_id="alex")
    api.log_episode(sid, "assistant", "LSP 泛洪是邻居发现后同步链路状态的过程…", agent_id="alex")
    rec = api.recall_episodes(session_id=sid)
    print("2. episodes:", rec["count"], "回合")

    # 蒸馏
    d = api.distill_facts(
        "alex",
        [{"entity": "ISIS", "fact": "正在备考 HCIE-Datacom，重点学 LSP 泛洪", "fact_type": "goal", "importance": 0.9}],
        persona="tutor",
    )
    print("3. distill:", d["message"])

    # 检索
    hits = api.retrieve("ISIS", "alex", "tutor")
    print("4. retrieve:", len(hits), "命中 ->", hits[0]["title"][:30] if hits else "无")

    # 人设钩子注入
    ctx = api.get_context("alex", "tutor", freshness_level="cold", focus_subject="ISIS")
    print("5. context.persona_ext keys:", list(ctx["persona_ext"].keys()))
    print("5b. context budget:", ctx["token_budget_limit"], "used", ctx["token_budget_used"])

    # 进化（C2/C3）
    evo = api.evolve(["c2_review", "c3_triggers"], dry_run=True, agent_id="alex", persona="tutor")
    print("6. evolve(dry_run):", evo["summary"])

    # 健康（含检索 P95）
    h = api.health()
    print("7. health:", h["healthy"], "retrieval_stats:", h["retrieval_stats"])
    print("\nSMOKE OK ✅")


def _personas() -> list[str]:
    from server import _discover_personas
    return _discover_personas()


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] == "help":
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "init":
        cmd_init()
    elif cmd == "personas":
        cmd_personas()
    elif cmd == "switch" and len(args) >= 3:
        cmd_switch(args[1], args[2])
    elif cmd == "context" and len(args) >= 2:
        cmd_context(args[1], args[2] if len(args) > 2 else "")
    elif cmd == "smoke":
        cmd_smoke()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
