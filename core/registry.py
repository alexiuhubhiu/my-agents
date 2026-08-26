#!/usr/bin/env python3
"""
core.registry — 人设注册中心（动态加载 / 切换的核心）
======================================================
职责：
1. load_persona(name)   — 导入人设包 → 应用 Schema 扩展 → 注册工具 → 返回 PersonaContext
2. switch_persona(...)  — 切换当前激活人设（数据隔离靠 agent_id，工具集靠命名空间前缀）
3. build_app(...)       — 组装 FastMCP：core 通用工具 + 各人设专属工具

加载链路（load_persona）：
  importlib.import_module(personas.tutor)
      → 模块内调用 core.manifest.register(PersonaManifest(...))   ← 声明式注册
  registry 消费 manifest：
      1) schema_ext 存在 → apply_persona_schema(ext)   （幂等：守卫式 ALTER + CREATE IF NOT EXISTS）
      2) tools 非空     → 逐个 import 注册函数，交给 FastMCP 注册
      3) evolution 存在 → 导入能力字典，挂载到进化框架
      4) context_hook   → 记录回调，get_context 时注入

切换语义（重要）：
- 数据层：agent_id 是唯一隔离键。同一 agent 可先后/同时被多人设服务，
  各人设数据并存于同一库（表前缀不同），互不覆盖。
- 工具层：core 工具始终可见（全人设共享）；人设工具按 manifest.tools 注册，
  工具名带 <persona>_ 前缀避免冲突。切换 = 变更 agent_state.active_persona
  + 加载/卸载对应人设工具（FastMCP 支持运行时 add_tool，卸载走路由屏蔽）。
"""

from __future__ import annotations

import importlib
import logging
import sqlite3
from dataclasses import dataclass, field

from . import manifest as mf
from .db import get_db

log = logging.getLogger("agents.registry")

# 已加载的人设上下文缓存
_loaded: dict[str, "PersonaContext"] = {}


@dataclass
class PersonaContext:
    """人设运行时上下文：底层能力 + 该人设专属资源。"""

    manifest: mf.PersonaManifest
    api: "MemoryAPI"                    # 记忆底层稳定接口（见 core.api）
    extra_tools: list[callable] = field(default_factory=list)   # 已解析的专属工具函数
    evolution_caps: dict = field(default_factory=dict)          # {cap_key: EvolutionCapability}
    context_hook: callable | None = None                        # get_context 扩展钩子

    @property
    def name(self) -> str:
        return self.manifest.name


def apply_persona_schema(ext_module, persona: str, conn: sqlite3.Connection | None = None) -> list[str]:
    """幂等地应用人设 Schema 扩展。

    1) EXT_COLUMNS → 守卫式 ALTER TABLE ADD COLUMN（PRAGMA table_info 查重）
    2) EXT_TABLES  → CREATE TABLE IF NOT EXISTS（表名必须带 <persona>_ 前缀，违反即报错）
    """
    conn = conn or get_db()
    applied: list[str] = []

    # ── 扩展列 ──
    for col in getattr(ext_module, "EXT_COLUMNS", []):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({col.table})").fetchall()}
        if col.name in cols:
            continue  # 已存在 → 幂等跳过
        conn.execute(f"ALTER TABLE {col.table} ADD COLUMN {col.name} {col.ddl}")
        applied.append(f"{col.table}.{col.name}")

    # ── 扩展表 ──
    ext_sql = getattr(ext_module, "EXT_TABLES", "")
    if ext_sql:
        # 前缀守卫：防止人设意外创建无前缀表污染通用层
        for line in ext_sql.splitlines():
            stripped = line.strip().upper()
            if stripped.startswith("CREATE TABLE") and f"{persona}_" not in line:
                raise RuntimeError(
                    f"persona '{persona}' 扩展表未带 '{persona}_' 前缀：{line.strip()}"
                )
        conn.executescript(ext_sql)
        applied.append(f"{persona}_* (扩展表)")

    conn.commit()
    return applied


def load_persona(name: str, api: "MemoryAPI") -> PersonaContext:
    """加载一个人设（幂等：已加载直接返回）。"""
    if name in _loaded:
        return _loaded[name]

    # 1) 导入人设包 → 触发 manifest.register()
    importlib.import_module(f"personas.{name}")
    man = mf.get(name)
    if man is None:
        raise LookupError(f"persona '{name}' 未调用 core.manifest.register() 完成声明")

    # 2) Schema 扩展（用 api 的真实连接，避免 get_db() 单例在测试里指向错误库）
    if man.schema_ext:
        ext_mod = importlib.import_module(man.schema_ext)
        applied = apply_persona_schema(ext_mod, name, api.conn)
        log.info("persona %s schema 扩展应用: %s", name, applied)

    ctx = PersonaContext(manifest=man, api=api)

    # 3) 专属工具解析（函数对象延迟绑定，注册交给 server 层）
    for tool_ref in man.tools:
        mod_path, _, fn_name = tool_ref.partition(":")
        mod = importlib.import_module(mod_path)
        ctx.extra_tools.append(getattr(mod, fn_name))

    # 4) 进化能力挂载
    if man.evolution:
        evo_mod = importlib.import_module(man.evolution)
        ctx.evolution_caps = getattr(evo_mod, "CAPABILITIES", {})

    # 5) get_context 扩展钩子
    if man.context_hook:
        mod_path, _, fn_name = man.context_hook.partition(":")
        ctx.context_hook = getattr(importlib.import_module(mod_path), fn_name)

    _loaded[name] = ctx
    return ctx


def switch_persona(agent_id: str, persona: str, conn: sqlite3.Connection | None = None) -> dict:
    """切换 agent 的当前激活人设（不销毁任何数据，仅更新 active_persona 指针）。

    - 目标人设须已 load_persona（未加载则自动加载）
    - 旧人设数据原样保留（表前缀/agent_id 隔离，可随时切回）
    - 返回切换前后状态
    """
    ctx = _loaded.get(persona) or load_persona(persona, _active_api)
    conn = conn or get_db()
    before = conn.execute(
        "SELECT active_persona FROM agent_state WHERE agent_id=?", (agent_id,)
    ).fetchone()
    before = before["active_persona"] if before else ""
    conn.execute(
        """INSERT INTO agent_state (agent_id, active_persona, updated_at, version)
           VALUES (?, ?, datetime('now'), 1)
           ON CONFLICT(agent_id) DO UPDATE SET
               active_persona=excluded.active_persona,
               updated_at=datetime('now'),
               version=version+1""",
        (agent_id, persona),
    )
    conn.commit()
    return {"agent_id": agent_id, "before": before, "now": persona, "loaded": ctx.name}


def active_persona(agent_id: str, conn: sqlite3.Connection | None = None) -> str:
    """查询 agent 当前激活人设（空则返回 ''）。"""
    conn = conn or get_db()
    row = conn.execute(
        "SELECT active_persona FROM agent_state WHERE agent_id=?", (agent_id,)
    ).fetchone()
    return row["active_persona"] if row else ""


def list_personas() -> list[dict]:
    """列出全部已加载人设（registry + 进程内上下文）。"""
    return [
        {
            "name": m.name,
            "display_name": m.display_name,
            "version": m.version,
            "tools": len(m.tools),
            "schema_ext": bool(m.schema_ext),
            "loaded": m.name in _loaded,
        }
        for m in mf.all_manifests()
    ]


def get(name: str) -> mf.PersonaManifest | None:
    """按名查询人设清单（转发 manifest 注册表）。"""
    return mf.get(name)


# 供 switch_persona 内部引用的当前 api（server 层启动时注入）
_active_api: "MemoryAPI" = None  # type: ignore[assignment]


def bind_api(api: "MemoryAPI") -> None:
    global _active_api
    _active_api = api
