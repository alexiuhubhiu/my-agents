#!/usr/bin/env python3
"""
personas.guide.manifest — 系统引导助手人设清单
===============================================
定位：系统管理层的入口人设，仅引导与调度，不执行实际任务。
刻意不设置 context_hook / schema_ext / evolution（token 最小化）。
"""

from __future__ import annotations

from core.manifest import PersonaManifest, register

register(
    PersonaManifest(
        name="guide",
        display_name="系统引导助手",
        version="1.0.0",
        description="系统引导助手：新用户人格创建/切换的引导与调度入口（轻量，不执行任务）",
        entry="personas.guide",
        tools=[
            "personas.guide.tools.guide:tool_status",
            "personas.guide.tools.guide:tool_create_persona",
            "personas.guide.tools.guide:tool_switch_persona",
        ],
        core_tools_used=["mem_get_state", "mem_update_state"],
        prompts={"init": "personas/guide/prompts/init.md"},
        default_agent_id="default",
        # context_hook=None（引导期 active_persona 为空时 hook 不触发，判定统一走 guide_status）
        # schema_ext=None（onboarded 走 state_json，人格档案走 core_memory）
        # evolution=None
    )
)
