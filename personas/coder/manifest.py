#!/usr/bin/env python3
"""
personas.coder.manifest — 编程工作人设清单（范例：验证新人设 3 步插拔）
========================================================================
与导师人设完全不同的领域：任务追踪 + 代码审查记录。
演示：多人设共享同一记忆底层，各自维护专属工具/表/钩子，互不干扰。
"""

from __future__ import annotations

from core.manifest import PersonaManifest, register

register(
    PersonaManifest(
        name="coder",
        display_name="编程助手",
        version="1.0.0",
        description="编程工作人设：任务追踪、代码审查记录、技术债管理（范例人设）",
        entry="personas.coder",

        # ── 专属 MCP 工具（coder_ 前缀，与 tutor_ 命名空间隔离）──
        tools=[
            "personas.coder.tools.tasks:tool_record_task",
            "personas.coder.tools.tasks:tool_complete_task",
            "personas.coder.tools.reviews:tool_record_review",
        ],
        core_tools_used=[
            "mem_start_session", "mem_log_episode", "mem_distill",
            "mem_get_context", "mem_update_state", "mem_switch_persona",
        ],

        # ── 专属 Schema 扩展 ──
        schema_ext="personas.coder.schema_ext",

        # ── 提示词 ──
        prompts={
            "init": "personas/coder/prompts/init.md",
        },

        # ── get_context 扩展钩子 ──
        context_hook="personas.coder.hooks:inject_coder_context",

        default_agent_id="default",
    )
)
