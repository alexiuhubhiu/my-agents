#!/usr/bin/env python3
"""
scripts.import_v4_data — 旧 tutor.db → 新 agents.db 全量数据导入
=================================================================
功能：
- 15 张表映射（旧表 → 新表，含列差异处理）
- UNIQUE 键差异 upsert（memory_facts/learning_progress/diary_entries/core_memory）
- persona 列回填 'tutor'；agent_id 回填 'alex'
- diary 文件复制（54 篇 → diary/alex/，保留 mtime）+ filepath 回写
- import_log 幂等标记表（重跑自动跳过，--force 强制重导）
- --verify 只读对比模式

用法：
    python scripts/import_v4_data.py                      # 导入
    python scripts/import_v4_data.py --force              # 强制重导
    python scripts/import_v4_data.py --verify             # 只读对比新旧 COUNT
    python scripts/import_v4_data.py --src D:/path/tutor.db --dst D:/path/agents.db

安全：导入前自动备份目标库到 backups/pre_import_<ts>.db；源库只读 ATTACH。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# 确保项目根在 sys.path（脚本以 python scripts/xxx.py 运行时）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── 默认路径 ──
DEFAULT_SRC = Path(r"D:\my_tutor\AI导师系统\tutor.db")
DEFAULT_DST = Path(__file__).resolve().parent.parent / "data" / "agents.db"
DEFAULT_SRC_DIARY = Path(r"D:\my_tutor\AI导师系统\diary")
AGENT_ID = "alex"
PERSONA = "tutor"


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_import_log(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS import_log (
               table_name TEXT PRIMARY KEY,
               source_path TEXT NOT NULL,
               rows INTEGER NOT NULL,
               ts TEXT NOT NULL
           )"""
    )
    conn.commit()


def _backup_dst(dst: Path) -> Path | None:
    """导入前备份目标库（若已有数据）。备份目录可用 AGENTS_BACKUP_DIR 覆盖（测试隔离）。"""
    if not dst.exists() or dst.stat().st_size == 0:
        return None
    backup_dir = Path(__file__).resolve().parent.parent / "backups"
    override = __import__("os").environ.get("AGENTS_BACKUP_DIR")
    if override:
        backup_dir = Path(override)
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"pre_import_{ts}.db"
    src_conn = sqlite3.connect(str(dst))
    dst_conn = sqlite3.connect(str(backup))
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    return backup


def _copy_diary_files(src_dir: Path, dst_dir: Path, agent_id: str) -> tuple[int, int]:
    """复制日记文件到 diary/<agent>/，保留 mtime。返回 (copied, skipped)。"""
    if not src_dir.exists():
        return 0, 0
    target = dst_dir / agent_id
    target.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for f in sorted(src_dir.glob("*.md")):
        if f.name.startswith("_"):
            continue  # 排除模板/系统文件
        dest = target / f.name
        if dest.exists() and dest.stat().st_mtime == f.stat().st_mtime:
            skipped += 1
            continue
        shutil.copy2(f, dest)
        copied += 1
    return copied, skipped


# ── 表映射定义 ──
# (旧表, 新表, 列映射 {新列: 源列或常量}, 冲突键, upsert 更新列)
# 列映射中 None 值 = 该列跳过（由特殊处理填充）
TABLE_MAPS: list[dict] = [
    # core 表
    {"src": "sessions", "dst": "sessions", "cols": {"persona": lambda r: PERSONA}, "conflict": "id",
     "upsert": ["subject", "topic", "summary", "status"]},
    {"src": "episodes", "dst": "episodes", "cols": {}, "conflict": "id", "upsert": []},
    {"src": "core_memory", "dst": "core_memory", "cols": {"agent_id": lambda r: AGENT_ID}, "conflict": "agent_id, block_key",
     "upsert": ["block_value", "priority"]},
    {"src": "memory_facts", "dst": "memory_facts",
     "cols": {"agent_id": lambda r: AGENT_ID, "persona": lambda r: PERSONA, "subject": lambda r: r["subject"] or ""},
     "conflict": "agent_id, entity, fact",
     "upsert": ["importance", "confidence", "last_confirmed_at"]},
    {"src": "evolution_events", "dst": "evolution_events", "cols": {"agent_id": lambda r: AGENT_ID}, "conflict": "id", "upsert": []},
    {"src": "retrieval_log", "dst": "retrieval_log",
     "cols": {"agent_id": lambda r: r["agent_id"] or AGENT_ID, "persona": lambda r: PERSONA}, "conflict": "id", "upsert": []},
    # tutor 扩展表
    {"src": "learning_progress", "dst": "tutor_learning_progress",
     "cols": {"agent_id": lambda r: AGENT_ID}, "conflict": "agent_id, subject, topic",
     "upsert": ["mastery_level", "review_count", "next_review_at", "status"]},
    {"src": "error_patterns", "dst": "tutor_error_patterns",
     "cols": {"agent_id": lambda r: AGENT_ID}, "conflict": "id", "upsert": []},
    {"src": "pitfall_triggers", "dst": "tutor_pitfall_triggers",
     "cols": {"agent_id": lambda r: AGENT_ID}, "conflict": "id", "upsert": []},
    {"src": "teacher_knowledge", "dst": "tutor_teacher_knowledge", "cols": {}, "conflict": "id", "upsert": []},
    {"src": "teaching_metrics", "dst": "tutor_teaching_metrics",
     "cols": {"agent_id": lambda r: AGENT_ID, "session_id": lambda r: ""}, "conflict": "id", "upsert": []},
]

# diary 单独处理（UNIQUE(agent_id,date) + filepath 回写）
DIARY_MAP = {"src": "diary_entries", "dst": "tutor_diary_entries",
             "conflict": "agent_id, date", "upsert": ["filepath", "excerpt", "has_romance", "mood_summary"]}


def _build_insert(conn: sqlite3.Connection, spec: dict, src_cols: list[str]) -> str:
    """构造 INSERT ... ON CONFLICT DO UPDATE 语句。"""
    dst_table = spec["dst"]
    dst_cols = [c[1] for c in conn.execute(f"PRAGMA table_info({dst_table})").fetchall()]
    cols = [c for c in dst_cols if c in src_cols or c in spec.get("cols", {})]
    col_list = ", ".join(cols)
    ph = ", ".join("?" * len(cols))
    conflict = spec["conflict"]
    upsert = spec.get("upsert", [])
    if upsert:
        set_sql = ", ".join(
            f"{c}=CASE WHEN excluded.{c} > {c} OR {c} IS NULL THEN excluded.{c} ELSE {c} END" if c in ("importance", "confidence", "mastery_level", "review_count")
            else f"{c}=excluded.{c}"
            for c in upsert if c in cols
        )
        if set_sql:
            return f"INSERT INTO {dst_table} ({col_list}) VALUES ({ph}) ON CONFLICT({conflict}) DO UPDATE SET {set_sql}"
    return f"INSERT OR IGNORE INTO {dst_table} ({col_list}) VALUES ({ph})"


def import_table(conn_src: sqlite3.Connection, conn_dst: sqlite3.Connection, spec: dict, force: bool = False) -> dict:
    """导入单张表（幂等：import_log 标记 + upsert）。"""
    src_t, dst_t = spec["src"], spec["dst"]
    log = conn_dst.execute("SELECT rows FROM import_log WHERE table_name=?", (dst_t,)).fetchone()
    if log and not force:
        return {"table": dst_t, "skipped": True, "rows": log["rows"]}

    src_cols = [r[1] for r in conn_src.execute(f"PRAGMA table_info({src_t})").fetchall()]
    if not src_cols:
        return {"table": dst_t, "skipped": True, "rows": 0, "reason": "源表不存在"}

    insert_sql = _build_insert(conn_dst, spec, src_cols)
    cols_in_stmt = [c.strip() for c in insert_sql.split("(")[1].split(")")[0].split(",")]

    rows = conn_src.execute(f"SELECT * FROM {src_t}").fetchall()
    n = 0
    for r in rows:
        row = dict(r)
        values = []
        for c in cols_in_stmt:
            if c in spec.get("cols", {}):
                values.append(spec["cols"][c](row))
            else:
                values.append(row.get(c))
        conn_dst.execute(insert_sql, values)
        n += 1

    conn_dst.execute(
        "INSERT OR REPLACE INTO import_log (table_name, source_path, rows, ts) VALUES (?, ?, ?, ?)",
        (dst_t, str(DEFAULT_SRC), n, datetime.now().isoformat()),
    )
    conn_dst.commit()
    return {"table": dst_t, "imported": n, "rows": n}


def import_diary(conn_src: sqlite3.Connection, conn_dst: sqlite3.Connection, src_dir: Path, dst_dir: Path, force: bool = False) -> dict:
    """导入日记：复制文件 + 回填 filepath + upsert 索引行。"""
    log = conn_dst.execute("SELECT rows FROM import_log WHERE table_name=?", (DIARY_MAP["dst"],)).fetchone()
    if log and not force:
        return {"table": DIARY_MAP["dst"], "skipped": True, "rows": log["rows"]}

    copied, skipped_files = _copy_diary_files(src_dir, dst_dir, AGENT_ID)

    src_cols = [r[1] for r in conn_src.execute(f"PRAGMA table_info({DIARY_MAP['src']})").fetchall()]
    rows = conn_src.execute(f"SELECT * FROM {DIARY_MAP['src']}").fetchall()
    n = 0
    for r in rows:
        row = dict(r)
        date = row.get("date", "")
        filepath = f"diary/{AGENT_ID}/{date}.md"
        conn_dst.execute(
            f"""INSERT INTO {DIARY_MAP['dst']} (agent_id, date, filepath, excerpt, has_romance, mood_summary)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT({DIARY_MAP['conflict']}) DO UPDATE SET
                    filepath=excluded.filepath, excerpt=excluded.excerpt,
                    has_romance=excluded.has_romance, mood_summary=excluded.mood_summary""",
            (AGENT_ID, date, filepath, row.get("excerpt"), row.get("has_romance", 0), row.get("mood_summary", "")),
        )
        n += 1
    conn_dst.execute(
        "INSERT OR REPLACE INTO import_log (table_name, source_path, rows, ts) VALUES (?, ?, ?, ?)",
        (DIARY_MAP["dst"], str(src_dir), n, datetime.now().isoformat()),
    )
    conn_dst.commit()
    return {"table": DIARY_MAP["dst"], "imported": n, "rows": n, "files_copied": copied, "files_skipped": skipped_files}


def import_agent_state(conn_src: sqlite3.Connection, conn_dst: sqlite3.Connection, force: bool = False) -> dict:
    """student_state → agent_state（列映射 + 教学列 → tutor_ 扩展列 + 其余 → state_json）。"""
    log = conn_dst.execute("SELECT rows FROM import_log WHERE table_name='agent_state'").fetchone()
    if log and not force:
        return {"table": "agent_state", "skipped": True, "rows": log["rows"]}

    row = conn_src.execute("SELECT * FROM student_state WHERE id=1").fetchone()
    if not row:
        return {"table": "agent_state", "skipped": True, "rows": 0}
    r = dict(row)

    # 直接映射列
    direct = {
        "ritual_state": r.get("ritual_state", "IDLE"),
        "turn_count": r.get("turn_count", 0),
        "session_count": r.get("session_count", 0),
        "last_session_at": r.get("last_session_at"),
        "updated_at": r.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # tutor_ 扩展列映射
    ext_cols = {
        "tutor_mood": r.get("mood", "neutral"),
        "tutor_energy": r.get("energy", 7),
        "tutor_focus": r.get("focus", 0.6),
        "tutor_ds_reply_interval_sec": r.get("ds_reply_interval_sec", 30.0),
        "tutor_ds_code_paste_speed": r.get("ds_code_paste_speed", "normal"),
        "tutor_ds_consecutive_short_replies": r.get("ds_consecutive_short_replies", 0),
        "tutor_ds_question_frequency": r.get("ds_question_frequency", 0.3),
        "tutor_ds_flow_state": r.get("ds_flow_state", "neutral"),
        "tutor_ds_total_questions": r.get("ds_total_questions", 0),
        "tutor_ds_last_interaction_at": r.get("ds_last_interaction_at"),
        "tutor_post_class_mode": r.get("rsc_post_class_mode", 0),
        "tutor_post_class_rounds_left": r.get("rsc_post_class_rounds_left", 0),
    }
    # 其余 → state_json
    skip_keys = set(direct) | set(ext_cols) | {"id", "version", "mood", "energy", "focus",
                                               "ds_reply_interval_sec", "ds_code_paste_speed",
                                               "ds_consecutive_short_replies", "ds_question_frequency",
                                               "ds_flow_state", "ds_total_questions", "ds_last_interaction_at",
                                               "rsc_post_class_mode", "rsc_post_class_rounds_left", "current_subject", "current_topic"}
    state_json = {k: v for k, v in r.items() if k not in skip_keys and v is not None}
    # current_subject/current_topic → current_task
    if r.get("current_subject"):
        direct["current_task"] = f"{r['current_subject']} {r.get('current_topic', '')}".strip()

    cols = ["agent_id", "active_persona"] + list(direct.keys()) + list(ext_cols.keys()) + ["state_json"]
    values = [AGENT_ID, PERSONA] + list(direct.values()) + list(ext_cols.values()) + [json.dumps(state_json, ensure_ascii=False)]
    col_list = ", ".join(cols)
    ph = ", ".join("?" * len(cols))
    conn_dst.execute(
        f"""INSERT INTO agent_state ({col_list}) VALUES ({ph})
            ON CONFLICT(agent_id) DO UPDATE SET
                active_persona=excluded.active_persona, state_json=excluded.state_json,
                updated_at=excluded.updated_at, version=version+1""",
        values,
    )
    conn_dst.execute(
        "INSERT OR REPLACE INTO import_log (table_name, source_path, rows, ts) VALUES ('agent_state', ?, 1, ?)",
        (str(DEFAULT_SRC), datetime.now().isoformat()),
    )
    conn_dst.commit()
    return {"table": "agent_state", "imported": 1, "rows": 1}


def run_import(src_path: Path, dst_path: Path, force: bool = False, src_diary: Path | None = None, diary_dst: Path | None = None) -> dict:
    """执行全量导入，返回每表结果。diary_dst 可覆盖（测试隔离）。"""
    src_diary = src_diary or Path(r"D:\my_tutor\AI导师系统\diary")
    diary_dst = diary_dst or (Path(__file__).resolve().parent.parent / "diary")
    backup = _backup_dst(dst_path)
    print(f"备份: {backup or '无（目标库为空）'}")

    conn_src = _open(src_path)
    conn_dst = _open(dst_path)
    _ensure_import_log(conn_dst)

    # 前置：目标库 schema 就绪（core 表 + tutor 扩展）
    from core.schema import CORE_SCHEMA_SQL
    conn_dst.executescript(CORE_SCHEMA_SQL)
    from personas.tutor import schema_ext as tutor_ext
    from core import registry
    registry.apply_persona_schema(tutor_ext, "tutor", conn_dst)
    conn_dst.commit()

    results = []
    # 1) agent_state（特殊映射）
    results.append(import_agent_state(conn_src, conn_dst, force))
    # 2) core 表 + tutor 表（通用映射）
    for spec in TABLE_MAPS:
        results.append(import_table(conn_src, conn_dst, spec, force))
    # 3) diary（文件复制 + 索引）
    results.append(import_diary(conn_src, conn_dst, src_diary, diary_dst, force))

    conn_dst.close()
    conn_src.close()
    return {"backup": str(backup) if backup else None, "results": results}


def verify(src_path: Path, dst_path: Path) -> dict:
    """只读对比新旧库各表 COUNT。"""
    conn_src = _open(src_path)
    conn_dst = _open(dst_path)
    pairs = [
        ("student_state", "agent_state"), ("learning_progress", "tutor_learning_progress"),
        ("error_patterns", "tutor_error_patterns"), ("pitfall_triggers", "tutor_pitfall_triggers"),
        ("teacher_knowledge", "tutor_teacher_knowledge"), ("teaching_metrics", "tutor_teaching_metrics"),
        ("diary_entries", "tutor_diary_entries"), ("sessions", "sessions"), ("episodes", "episodes"),
        ("core_memory", "core_memory"), ("memory_facts", "memory_facts"),
        ("evolution_events", "evolution_events"), ("retrieval_log", "retrieval_log"),
    ]
    report = []
    for s, d in pairs:
        try:
            sc = conn_src.execute(f"SELECT COUNT(*) FROM {s}").fetchone()[0]
        except sqlite3.Error:
            sc = "N/A"
        try:
            dc = conn_dst.execute(f"SELECT COUNT(*) FROM {d}").fetchone()[0]
        except sqlite3.Error:
            dc = "N/A"
        ok = (sc == dc) if isinstance(sc, int) and isinstance(dc, int) else None
        report.append({"src": s, "dst": d, "src_count": sc, "dst_count": dc, "match": ok})
    conn_dst.close()
    conn_src.close()
    return {"report": report}


def main() -> None:
    parser = argparse.ArgumentParser(description="旧 tutor.db → 新 agents.db 数据导入")
    parser.add_argument("--src", default=str(DEFAULT_SRC))
    parser.add_argument("--dst", default=str(DEFAULT_DST))
    parser.add_argument("--src-diary", default=str(DEFAULT_SRC_DIARY))
    parser.add_argument("--force", action="store_true", help="强制重导（忽略 import_log）")
    parser.add_argument("--verify", action="store_true", help="只读对比新旧 COUNT")
    args = parser.parse_args()

    if args.verify:
        rep = verify(Path(args.src), Path(args.dst))
        for r in rep["report"]:
            mark = "✅" if r["match"] is True else ("⚠️" if r["match"] is None else "❌")
            print(f"{mark} {r['src']:20} -> {r['dst']:24} {r['src_count']} vs {r['dst_count']}")
        return

    result = run_import(Path(args.src), Path(args.dst), args.force, Path(args.src_diary))
    print(f"备份: {result['backup']}")
    for r in result["results"]:
        if r.get("skipped"):
            print(f"⏭️  {r['table']:26} 已导入过（{r.get('rows')} 行），--force 强制重导")
        else:
            extra = f"，文件复制 {r.get('files_copied')}/{r.get('files_copied', 0) + r.get('files_skipped', 0)}" if "files_copied" in r else ""
            print(f"✅ {r['table']:26} 导入 {r.get('imported', r.get('rows', 0))} 行{extra}")
    print("\n导入完成。用 --verify 检查一致性。")


if __name__ == "__main__":
    main()
