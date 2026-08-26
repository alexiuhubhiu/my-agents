#!/usr/bin/env python3
"""
personas.tutor.manifest — AI导师人设清单（声明式注册）
========================================================
从 AI导师系统 v4.0 迁移：教学专属工具 / 表 / 提示词全部收拢到本包，
记忆底层只保留通用部分（sessions/episodes/facts/state/evolution）。
"""

from __future__ import annotations

from core.manifest import PersonaManifest, register

# 导入即触发 register()；registry.load_persona("tutor") 后可用
register(
    PersonaManifest(
        name="tutor",
        display_name="AI导师",
        version="1.0.0",
        description="一对一教学助手：学生状态感知、错题追踪、复习计划、教学日记",
        entry="personas.tutor",

        # ── 专属 MCP 工具（带 tutor_ 前缀）──
        tools=[
            "personas.tutor.tools.interaction:tool_record_interaction",
            "personas.tutor.tools.query:tool_query_errors",
            "personas.tutor.tools.diary:tool_write_diary",
            "personas.tutor.tools.session:tool_end_session",
        ],
        # 依赖的记忆底层通用工具（可读性声明）
        core_tools_used=[
            "mem_start_session", "mem_log_episode", "mem_recall_episodes",
            "mem_distill", "mem_get_context", "mem_update_state", "mem_evolve",
        ],

        # ── 专属 Schema 扩展 ──
        schema_ext="personas.tutor.schema_ext",

        # ── 提示词（从 system/ 迁移，9 个）──
        prompts={
            "init": "personas/tutor/prompts/init.md",
            "persona": "personas/tutor/prompts/persona.md",
            "methodology": "personas/tutor/prompts/methodology.md",
            "workflow": "personas/tutor/prompts/workflow.md",
            "diary_template": "personas/tutor/prompts/diary-template.md",
            "persona_notes": "personas/tutor/prompts/persona-notes.md",
            "db_dictionary": "personas/tutor/prompts/db-dictionary.md",
            "directory_conventions": "personas/tutor/prompts/directory-conventions.md",
            "distill_template": "personas/tutor/prompts/distill-template.md",
        },

        # ── 专属进化能力 ──
        evolution="personas.tutor.evolution",

        # ── get_context 扩展钩子 ──
        context_hook="personas.tutor.hooks:inject_tutor_context",

        default_agent_id="alex",
    )
)
