# 提示词迁移脚本：system/ → personas/tutor/prompts/（工具名 + 路径改写）
import re
import shutil
from pathlib import Path

SRC = Path(r"D:\my_tutor\AI导师系统\system")
DST = Path(r"D:\my_agents\personas\tutor\prompts")

# 16 旧工具名 → 新名（长名在前，re.sub alternation 只处理一次）
TOOL_MAP = {
    "start_session": "mem_start_session",
    "get_context": "mem_get_context",
    "record_interaction": "tutor_record_interaction",
    "recall_episodes": "mem_recall_episodes",
    "distill_memory": "mem_distill",
    "revert_evolution": "mem_revert_evolution",
    "update_state": "mem_update_state",
    "query_errors": "tutor_query_errors",
    "run_evolution": "mem_evolve",
    "health_check": "mem_health",
    "write_diary": "tutor_write_diary",
    "end_session": "tutor_end_session",
    "log_episode": "mem_log_episode",
    "db_execute": "mem_db_execute",
    "db_query": "mem_db_query",
    "schema": "mem_schema",
}
# 长名在前
_ALT = "|".join(sorted(TOOL_MAP, key=len, reverse=True))
_TOOL_RE = re.compile(rf"\b({_ALT})\b")


def rewrite(text: str) -> str:
    text = _TOOL_RE.sub(lambda m: TOOL_MAP[m.group(1)], text)
    # 路径改写：system/xxx.md → personas/tutor/prompts/xxx.md
    text = re.sub(r"system/(teacher_persona_v2|init-prompt-v3|persona-notes|distill-template|diary-template|workflow|methodology|db-dictionary|directory-conventions)\.md", r"personas/tutor/prompts/\1.md", text)
    # 旧的蒸馏模板引用（不带 system/ 前缀的裸名）
    text = text.replace("distill-template.md", "personas/tutor/prompts/distill-template.md")
    return text


FILES = {
    "init-prompt-v3.md": "init.md",
    "teacher_persona_v2.md": "persona.md",
    "methodology.md": "methodology.md",
    "workflow.md": "workflow.md",
    "diary-template.md": "diary-template.md",
    "persona-notes.md": "persona-notes.md",
    "db-dictionary.md": "db-dictionary.md",
    "directory-conventions.md": "directory-conventions.md",
    "distill-template.md": "distill-template.md",
}

DST.mkdir(parents=True, exist_ok=True)
for src_name, dst_name in FILES.items():
    src = SRC / src_name
    if not src.exists():
        print(f"SKIP(缺失): {src_name}")
        continue
    content = rewrite(src.read_text(encoding="utf-8"))
    (DST / dst_name).write_text(content, encoding="utf-8")
    print(f"OK: {src_name} -> {dst_name} ({len(content)} 字符)")

# 校验：旧工具名零残留
import io

leftover = []
for p in DST.glob("*.md"):
    text = p.read_text(encoding="utf-8")
    for old in TOOL_MAP:
        if re.search(rf"\b{old}\b", text):
            leftover.append((p.name, old))
print("\n旧工具名残留:", leftover if leftover else "无 ✅")
