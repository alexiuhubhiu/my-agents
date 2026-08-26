# guide 引导助手全流程验证
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import registry
from core.api import MemoryAPI

api = MemoryAPI()
# 用带时间戳的唯一 agent_id，避免与 data/ 中已持久化的状态冲突（测试隔离）
AGENT = f"guide_verify_{int(time.time() * 1000)}"

# 0) 加载 guide + tutor + coder（推荐/切换校验需要）
registry.load_persona("guide", api)
registry.load_persona("tutor", api)
registry.load_persona("coder", api)

from personas.guide.tools.guide import tool_create_persona, tool_status, tool_switch_persona

# 1) 全新 agent → needs_onboarding
r1 = tool_status(api, {"agent_id": AGENT})
print("1. status(新):", r1["status"], "| 可选:", [p["name"] for p in r1["available_personas"]])
assert r1["status"] == "needs_onboarding"
assert "guide" not in [p["name"] for p in r1["available_personas"]], "可选清单应排除 guide"

# 2) tone 校验拒绝
r2 = tool_create_persona(api, {"agent_id": AGENT, "name": "x", "purpose": "p", "tone": "随意"})
print("2. tone 非法:", r2["success"] == False)
assert r2["success"] is False and "tone" in r2["error"]

# 3) 建档 + 推荐 coder
r3 = tool_create_persona(api, {"agent_id": AGENT, "name": "编程小助手", "purpose": "日常编程代码答疑", "tone": "严谨", "domain": "编程/软件开发"})
print("3. create:", r3["success"], "| 推荐:", r3["recommended_persona"], "| profile:", r3["profile"]["name"])
assert r3["success"] and r3["recommended_persona"] == "coder"

# 4) 切换 + 标记 onboarded
r4 = tool_switch_persona(api, {"agent_id": AGENT, "persona": "coder"})
print("4. switch:", r4["status"], "| active:", r4["active_persona"], "|", r4["message"])
assert r4["success"] and r4["status"] == "onboarded" and r4["active_persona"] == "coder"

# 5) 复检 → already_onboarded
r5 = tool_status(api, {"agent_id": AGENT})
print("5. status(复检):", r5["status"])
assert r5["status"] == "already_onboarded"

# 6) 持久化断言
blocks = api.get_core_blocks(AGENT)
st = api.get_state(AGENT)["state"]
sj = st.get("state_json") or {}
print("6. 档案:", "persona_profile:编程小助手" in blocks, "| onboarded:", sj.get("onboarded"))
assert "persona_profile:编程小助手" in blocks
assert sj.get("onboarded") is True

# 7) 非法切换拒绝（guide 自身 / 未注册）
r7a = tool_switch_persona(api, {"agent_id": AGENT, "persona": "guide"})
r7b = tool_switch_persona(api, {"agent_id": AGENT, "persona": "nope"})
print("7. 切换 guide 拒绝:", r7a["success"] == False, "| 未注册拒绝:", r7b["success"] == False)
assert r7a["success"] is False and r7b["success"] is False

print("\nguide 引导助手验证 OK ✅")
