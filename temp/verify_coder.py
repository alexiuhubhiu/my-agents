# coder 人设插拔验证
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import registry
from core.api import MemoryAPI

api = MemoryAPI()

# 1) 加载 coder（新人设，core 零改动）
ctx = registry.load_persona("coder", api)
print("1. coder 已加载 | 工具:", [f.__name__.replace("tool_", "") for f in ctx.extra_tools])
print("   schema_ext:", bool(ctx.manifest.schema_ext), "| hooks:", bool(ctx.context_hook))

# 2) 切换到 coder
registry.switch_persona("dev1", "coder")
print("2. active_persona(dev1):", registry.active_persona("dev1"))

# 3) coder 专属工具
from personas.coder.tools.tasks import tool_record_task, tool_complete_task
from personas.coder.tools.reviews import tool_record_review

r1 = tool_record_task(api, {"agent_id": "dev1", "title": "重构 my_agents 检索模块", "repo": "my_agents", "priority": "high"})
r2 = tool_record_review(api, {"agent_id": "dev1", "repo": "my_agents", "file_path": "core/engine/retrieval.py", "issues_found": 3, "issues_fixed": 2})
print("3. record_task:", r1["success"], "| record_review:", r2["success"])

# 4) hooks 注入
ctx2 = api.get_context("dev1", "coder", "hot")
pe = ctx2["persona_ext"]
print("4. coder persona_ext:", sorted(pe.keys()))
print("   active_tasks:", [t["title"] for t in pe.get("active_tasks", [])])

# 5) 完成任务
r3 = tool_complete_task(api, {"agent_id": "dev1", "title": "重构 my_agents 检索模块"})
print("5. complete_task:", r3["completed"])

# 6) 与导师人设数据隔离（coder 表 vs tutor 表各自独立）
conn = api.conn
coder_tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'coder_%'").fetchall()]
print("6. coder_ 专属表:", coder_tables)

# 7) 人设列表
for p in registry.list_personas():
    print("   -", p["name"], p["display_name"], "tools=", p["tools"], "loaded=", p["loaded"])

print("\ncoder 插拔验证 OK ✅")
