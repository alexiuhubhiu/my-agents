# 阶段2验收脚本
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import registry
from core.api import MemoryAPI

api = MemoryAPI()
registry.load_persona("tutor", api)

from personas.tutor.tools.diary import tool_write_diary
from personas.tutor.tools.interaction import tool_analyze_session_errors, tool_record_interaction
from personas.tutor.tools.query import tool_query_errors
from personas.tutor.tools.session import tool_end_session

conn = api.conn
conn.execute(
    """INSERT INTO tutor_pitfall_triggers
       (agent_id, name, trigger_keywords, context_pattern, mandatory_action, severity, cooldown_turns)
       VALUES ('alex', '崩溃信号', '["崩溃","放弃"]', '', '先安抚再复盘', 'high', 5)"""
)
conn.commit()
s = api.start_session("alex", "tutor", subject="HCIE", topic="ISIS")
sid = s["session_id"]

# 1) 全角问号 + 心流
r1 = tool_record_interaction(api, {"agent_id": "alex", "user_message": "ISIS 泛洪流程是什么？", "session_id": sid})
print("1. signals:", {k: r1["signals"][k] for k in ("question_frequency", "flow_state", "turn_count", "questions_in_message")})

# 2) 触发器命中
r2 = tool_record_interaction(api, {"agent_id": "alex", "user_message": "我崩溃了，这题好难放弃吧", "session_id": sid})
print("2. triggers:", [(t["name"], t["severity"]) for t in r2["triggers"]])

# 3) 错误入库
r3 = tool_analyze_session_errors(api, {"agent_id": "alex", "error_patterns": [{"pattern": "LSP泛洪顺序混淆", "category": "err-lsp-flood"}]})
print("3. errors:", r3["applied_count"], "applied,", r3["skipped_count"], "skipped")

# 4) 下课 7 步
r4 = tool_end_session(
    api,
    {
        "agent_id": "alex",
        "session_id": sid,
        "session_summary": {
            "subject": "HCIE",
            "turns_total": 6,
            "concepts_introduced": 2,
            "notes": "讲了ISIS泛洪",
            "facts": [{"entity": "ISIS", "fact": "掌握泛洪原理", "fact_type": "strength", "importance": 0.8}],
        },
    },
)
print("4. end_session steps:", list(r4["steps"].keys()), "| failed:", r4["failed_steps"])

# 5) 错题查询全字段
r5 = tool_query_errors(api, {"agent_id": "alex"})
print("5. query_errors keys:", sorted(r5.keys()), "| total_active:", r5["total_active"])

# 6) 日记落盘 diary/alex/
r6 = tool_write_diary(api, {"agent_id": "alex", "content": "## 今日事实\n今天讲了 ISIS 泛洪，效果不错。\n\n心情：平静"})
mood_row = conn.execute("SELECT mood_summary FROM tutor_diary_entries WHERE agent_id='alex'").fetchone()
print("6. diary:", os.path.exists(r6["filepath"]), "| excerpt:", r6["excerpt"][:16], "| mood 正则:", "平静" in (mood_row[0] if mood_row else ""))

print("阶段2 OK")
