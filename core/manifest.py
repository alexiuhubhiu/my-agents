#!/usr/bin/env python3
"""
core.manifest — 工作人设清单模型（声明式注册的核心契约）
===========================================================
每个工作人设 = 一个 manifest.py，声明其：
- 元信息（name / version / 默认 agent_id）
- 专属工具集（entry 模块下的工具注册函数）
- 专属 Schema 扩展（schema_ext 模块）
- 提示词清单（prompts 目录）
- 进化能力（evolution 模块的自定义能力）

记忆底层不感知任何具体人设，只消费 PersonaManifest 这个契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PersonaManifest:
    # ── 元信息 ──
    name: str                       # 唯一标识：tutor / coder / writer ...
    display_name: str               # 展示名：AI导师
    version: str
    description: str
    entry: str                      # 人设包路径：personas.tutor

    # ── 工具集（领域层专属，区别于 core 通用工具）──
    # 每个元素 = 模块路径 + 注册函数名，如 "personas.tutor.tools.interaction:tool_record_interaction"
    tools: list[str] = field(default_factory=list)
    # 声明依赖哪些 core 通用工具（可读性/校验用，不影响注册）
    core_tools_used: list[str] = field(default_factory=list)

    # ── Schema 扩展 ──
    schema_ext: str | None = None   # 模块路径，如 "personas.tutor.schema_ext"
    # schema_ext 模块需导出：
    #   EXT_COLUMNS: list[ExtColumn]  → 对 core 表追加列（带 <persona>_ 前缀）
    #   EXT_TABLES:  str              → 建表 SQL 片段（带 <persona>_ 前缀表名）

    # ── 提示词 ──
    # {role: 文件路径}，如 {"init": "personas/tutor/prompts/init.md", ...}
    prompts: dict[str, str] = field(default_factory=dict)

    # ── 进化能力 ──
    # 自定义能力注册模块，需导出 dict[str, EvolutionCapability]
    # {"c1_errors": {...}, "c2_review": {...}}
    evolution: str | None = None

    # ── 默认实例 ──
    default_agent_id: str = "default"

    # ── 运行时上下文钩子 ──
    # get_context 时人设层扩展注入入口：模块路径:函数名
    context_hook: str | None = None


@dataclass(frozen=True)
class ExtColumn:
    """对 core 表追加的扩展列（SQLite ALTER TABLE ADD COLUMN）。"""

    table: str      # core 表名：agent_state / sessions / episodes ...
    name: str       # 列名（建议 <persona>_ 前缀）：tutor_mood
    ddl: str        # 完整列定义：TEXT NOT NULL DEFAULT 'neutral'


@dataclass(frozen=True)
class EvolutionCapability:
    """人设自定义进化能力（挂载到 core 进化框架）。"""

    key: str                     # 能力键：c1_errors
    description: str
    # 执行函数签名：fn(db, agent_id, dry_run) -> dict
    # 结果 {"applied": [...], "skipped": [...], "warnings": [...]}
    run: callable


# 全局注册表（进程内）
_REGISTRY: dict[str, PersonaManifest] = {}


def register(manifest: PersonaManifest) -> None:
    """登记一个人设清单（幂等，重名覆盖）。"""
    _REGISTRY[manifest.name] = manifest


def get(name: str) -> PersonaManifest | None:
    return _REGISTRY.get(name)


def all_manifests() -> list[PersonaManifest]:
    return list(_REGISTRY.values())


def clear() -> None:
    _REGISTRY.clear()
