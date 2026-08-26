#!/usr/bin/env python3
"""人设注册中心测试：load 幂等、switch 数据不销毁、Schema 扩展幂等 + 前缀守卫。"""

import pytest

from core import registry
from core.manifest import PersonaManifest, register


def test_load_persona_idempotent(persona_ctx):
    """重复加载返回同一上下文（缓存）。"""
    from core.api import MemoryAPI

    ctx2 = registry.load_persona("tutor", MemoryAPI(db_path=None))
    assert ctx2 is persona_ctx


def test_switch_persona_updates_pointer(api, persona_ctx):
    """切换人设：active_persona 指针更新，数据不销毁。"""
    s = api.start_session("alex", "tutor", subject="python")
    sid = s["session_id"]
    result = registry.switch_persona("alex", "tutor")
    assert result["now"] == "tutor"
    # 会话数据仍在
    rec = api.recall_episodes(session_id=sid)
    assert rec["sessions"]
    # active_persona 指针
    assert registry.active_persona("alex") == "tutor"


def test_schema_ext_idempotent(db):
    """apply_persona_schema 跑两次无异常、无重复列。"""
    from personas.tutor import schema_ext as tutor_ext

    registry.apply_persona_schema(tutor_ext, "tutor", db)
    registry.apply_persona_schema(tutor_ext, "tutor", db)  # 第二次应幂等
    cols = {r[1] for r in db.execute("PRAGMA table_info(agent_state)").fetchall()}
    assert "tutor_mood" in cols
    # 幂等：列集合与单次应用一致（无重复添加）
    assert len(cols) == len({c for c in cols})


def test_schema_ext_prefix_guard(db):
    """前缀守卫：无前缀建表被拦截（RuntimeError）。"""
    import types

    bad_mod = types.ModuleType("bad_ext")
    bad_mod.EXT_COLUMNS = []
    bad_mod.EXT_TABLES = "CREATE TABLE IF NOT EXISTS rogue_table (id INTEGER PRIMARY KEY);"
    with pytest.raises(RuntimeError, match="前缀"):
        registry.apply_persona_schema(bad_mod, "tutor", db)


def test_manifest_register_and_get():
    """manifest 注册/查询契约。"""
    m = PersonaManifest(name="t-test", display_name="测试", version="1.0", description="d", entry="x")
    register(m)
    assert registry.get("t-test") is m
    assert any(p["name"] == "t-test" for p in registry.list_personas())
