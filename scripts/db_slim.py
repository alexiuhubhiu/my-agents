#!/usr/bin/env python3
"""
my_agents — 数据库瘦身工具（v4.0 db_slim.py 适配：tutor_ 前缀）
=================================================================
功能：列出 deprecated 字段并可选物理删除（执行前自动备份）。
用法:
  python scripts/db_slim.py --dry-run    # 预览（默认）
  python scripts/db_slim.py --drop-deprecated  # 物理删列（先备份）
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "agents.db"

# deprecated 列（v4.0 遗留，若存在则建议删除）
DEPRECATED_COLUMNS = {
    "agent_state": [],  # 新架构已无旧 rsc_*/ritual_* 列（迁移时未建）
    "tutor_diary_entries": [],
}


def _backup():
    backups = Path(__file__).resolve().parent.parent / "backups"
    backups.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backups / f"agents_pre_slim_{ts}.db"
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(dest))
    src.backup(dst)
    dst.close()
    src.close()
    print(f"[OK] 已备份到 {dest.name}")


def main():
    parser = argparse.ArgumentParser(description="my_agents 数据库瘦身")
    parser.add_argument("--dry-run", action="store_true", default=True, help="预览模式（默认）")
    parser.add_argument("--drop-deprecated", action="store_true", help="物理删除 deprecated 列")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    found = False
    for table, cols in DEPRECATED_COLUMNS.items():
        try:
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except sqlite3.Error:
            continue
        for col in cols:
            if col in existing:
                found = True
                print(f"  {table}.{col} 存在")
                if args.drop_deprecated:
                    _backup()
                    conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
                    conn.commit()
                    print(f"  [DROP] {table}.{col}")
    if not found:
        print("无 deprecated 字段，数据库已干净 ✅")
    conn.close()


if __name__ == "__main__":
    main()
