#!/usr/bin/env python3
"""
server.py — 统一 MCP 入口（组装记忆底层 + 工作人设层）
======================================================
启动方式：
  python server.py                          # 默认加载全部人设
  python server.py --personas tutor         # 只加载导师
  python server.py --personas tutor,coder   # 多个人设共存

注册拓扑：
  core 通用工具（mem_* 前缀，全人设共享）
  + 各人设专属工具（<persona>_ 前缀，按 manifest.tools 动态注册）

切换机制：
  LLM 调用 mem_switch_persona 即可热切换当前激活人设；
  数据按 agent_id 隔离，切换不丢失任何历史。
"""

from __future__ import annotations

import argparse
import sys

from core import registry
from core.api import MemoryAPI
from core.tools import CORE_TOOLS


def build_app(personas: list[str] | None = None):
    """构建 FastMCP 应用（core 工具 + 指定人设工具）。"""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("ERROR: 需要 pip install mcp[cli]", file=sys.stderr)
        sys.exit(1)

    api = MemoryAPI()
    registry.bind_api(api)  # 供 switch_persona 内部使用

    mcp = FastMCP(
        name="my-agents",
        instructions=(
            "my_agents 多工作人设记忆底座。\n"
            "核心工具前缀 mem_（全人设共享）；人设工具带各自前缀（tutor_ 等）。\n"
            "切换人设：mem_switch_persona(persona, agent_id)；数据按 agent_id 隔离。"
        ),
    )

    # ── 注册 core 通用工具 ──
    for name, desc, handler in CORE_TOOLS:
        mcp.add_tool(
            _wrap(handler, api),
            name=name,
            description=desc,
        )

    # ── 加载并注册人设专属工具 ──
    persona_names = personas if personas is not None else _discover_personas()
    for pname in persona_names:
        ctx = registry.load_persona(pname, api)
        for fn in ctx.extra_tools:
            fname = getattr(fn, "__name__", "tool").replace("tool_", "")
            mcp.add_tool(
                _wrap(fn, api),
                name=f"{pname}_{fname}",
                description=(fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else pname,
            )

    return mcp


def _discover_personas() -> list[str]:
    """自动发现 personas/ 下的子包（含 manifest 的目录）。"""
    from pathlib import Path

    root = Path(__file__).parent / "personas"
    return sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and (d / "manifest.py").exists() and not d.name.startswith("_")
    )


def _wrap(fn, api):
    """把 fn(api, params: dict) 包装为 FastMCP 可调用的工具函数。

    注意：真实 MCP 工具需要显式参数注解（FastMCP 用类型签名生成 Schema）。
    完整实现请为每个工具写显式签名（见 AI导师系统 mcp_app.py 模式）；
    此处用 **kwargs 兜底，保证骨架可跑通。
    """

    async def _tool(**kwargs):
        return fn(api, kwargs)

    _tool.__name__ = fn.__name__
    return _tool


def main():
    parser = argparse.ArgumentParser(description="my_agents 多工作人设 MCP 服务")
    parser.add_argument("--personas", default="", help="逗号分隔的人设列表，空=全部")
    args = parser.parse_args()

    personas = [p.strip() for p in args.personas.split(",") if p.strip()] or None
    app = build_app(personas)
    app.run()  # stdio 传输


if __name__ == "__main__":
    main()
