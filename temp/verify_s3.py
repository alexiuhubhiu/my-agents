# 阶段3验收脚本
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import registry
from core.api import MemoryAPI

api = MemoryAPI()
registry.load_persona("tutor", api)
conn = api.conn

# 种子数据
conn.execute("""INSERT INTO tutor_learning_progress (agent_id, subject, status, mastery_level, next_review_at)
                VALUES ('alex', 'HCIE', 'in_progress', 60, date('now','-3 days'))""")
conn.execute("""INSERT INTO tutor_learning_progress (agent_id, subject, status, mastery_level, next_review_at)
                VALUES ('alex', '英语', 'in_progress', 90, date('now','-7 days'))""")
conn.execute("""INSERT INTO tutor_error_patterns (agent_id, pattern, category, root_cause, subject, status)
                VALUES ('alex', '泛洪顺序混淆', 'err-flood', '概念不清', 'HCIE', 'active')""")
conn.execute("""INSERT INTO tutor_pitfall_triggers (agent_id, name, trigger_keywords, context_pattern, mandatory_action, severity, applicable_subjects)
                VALUES ('alex', '无人用触发器', '["zzz"]', '', '无', 'warning', '["不存在的科目"]')""")
conn.execute("""INSERT INTO tutor_teaching_metrics (agent_id, session_date, subject, turns_total, independence_pct)
                VALUES ('alex', date('now','localtime'), 'HCIE', 20, 0.65)""")
conn.execute("""INSERT INTO tutor_teacher_knowledge (category, title, content)
                VALUES ('isis_concepts', 'LSP 泛洪', 'LSP 泛洪是 ISIS 邻居同步链路状态的机制，用 trigram 检索可命中')""")
conn.commit()

# 1) C2/C3 dry_run
evo = api.evolve(["c2_review", "c3_triggers"], dry_run=True, agent_id="alex", persona="tutor")
print("1. evolve(dry_run):", evo["summary"])
for r in evo["results"]:
    print("   ", r.get("capability"), "| adj:", r.get("adjustments_made", 0), "changes:", r.get("changes_made", 0))

# 2) C2/C3 真实应用
evo2 = api.evolve(["c2_review", "c3_triggers"], dry_run=False, agent_id="alex", persona="tutor")
print("2. evolve(applied):", evo2["summary"])
nxt = conn.execute("SELECT next_review_at FROM tutor_learning_progress WHERE agent_id='alex' AND subject='HCIE'").fetchone()
print("   HCIE next_review(有错→3d→减半→1d):", nxt[0])
sleep = conn.execute("SELECT active FROM tutor_pitfall_triggers WHERE agent_id='alex' AND name='无人用触发器'").fetchone()
print("   无人用触发器休眠:", sleep[0] == 0)

# 3) hooks 全字段
ctx = api.get_context("alex", "tutor", freshness_level="cold", focus_subject="HCIE")
pe = ctx["persona_ext"]
print("3. persona_ext keys:", sorted(pe.keys()))
print("   active_subjects:", [s["subject"] for s in pe.get("active_subjects", [])])
print("   recent_errors:", [e["pattern"] for e in pe.get("recent_errors", [])])
print("   today_summary:", pe.get("today_summary"))
print("   today_plan_suggestion:", pe.get("today_plan_suggestion"))
print("   knowledge_index:", [k["category"] for k in pe.get("knowledge_index", [])])

# 4) tutor FTS 检索（diary + knowledge）
conn.execute("""INSERT INTO tutor_diary_entries (agent_id, date, filepath, excerpt)
                VALUES ('alex', '2026-08-20', 'diary/alex/2026-08-20.md', '今天复习了 ISIS 泛洪原理')""")
conn.commit()
snips = ctx2 = None
ctx2 = api.get_context("alex", "tutor", freshness_level="cold", focus_subject="泛洪")
snips = ctx2["persona_ext"].get("tutor_memory_snippets", [])
print("4. tutor_memory_snippets(泛洪):", [(s["source"], s.get("title") or s.get("date")) for s in snips])

print("\n阶段3 OK")
