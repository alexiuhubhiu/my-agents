#!/usr/bin/env python3
"""
my_agents — 数据库自动备份工具（v4.0 backup.py 适配：data/agents.db）
=====================================================================
用法:
  python scripts/backup.py              # 创建备份
  python scripts/backup.py --list       # 列出所有备份
  python scripts/backup.py --restore <file>  # 从备份恢复
  python scripts/backup.py --keep 7     # 保留最近 7 份（默认）
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "agents.db"
BACKUP_DIR = BASE_DIR / "backups"
DEFAULT_KEEP = 7


def create_backup(keep: int = DEFAULT_KEEP) -> str:
    if not DB_PATH.exists():
        print(f"[ERROR] 数据库不存在: {DB_PATH}")
        sys.exit(1)
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"agents_{timestamp}.db"
    source = sqlite3.connect(str(DB_PATH))
    dest = sqlite3.connect(str(backup_file))
    source.backup(dest)
    dest.close()
    source.close()
    size_kb = backup_file.stat().st_size / 1024
    print(f"[OK] 备份已创建: {backup_file.name} ({size_kb:.1f} KB)")
    clean_old_backups(keep)
    return str(backup_file)


def list_backups():
    if not BACKUP_DIR.exists():
        print("暂无备份。")
        return
    backups = sorted(BACKUP_DIR.glob("agents_*.db"), reverse=True)
    if not backups:
        print("暂无备份。")
        return
    print(f"{'序号':<5} {'文件名':<35} {'大小':>10} {'修改时间':<20}")
    print("-" * 75)
    for i, f in enumerate(backups, 1):
        size = f.stat().st_size / 1024
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{i:<5} {f.name:<35} {size:>8.1f}KB {mtime:<20}")


def restore_backup(backup_file: str):
    backup_path = Path(backup_file)
    if not backup_path.is_absolute():
        backup_path = BACKUP_DIR / backup_file
    if not backup_path.exists():
        print(f"[ERROR] 备份文件不存在: {backup_path}")
        sys.exit(1)
    if DB_PATH.exists():
        pre_restore = BACKUP_DIR / f"agents_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        BACKUP_DIR.mkdir(exist_ok=True)
        shutil.copy2(str(DB_PATH), str(pre_restore))
        print(f"[OK] 恢复前已备份当前数据库到: {pre_restore.name}")
    shutil.copy2(str(backup_path), str(DB_PATH))
    print(f"[OK] 已从 {backup_path.name} 恢复数据库")
    conn = sqlite3.connect(str(DB_PATH))
    tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    conn.close()
    print(f"[OK] 验证: 数据库包含 {tables} 张表")


def clean_old_backups(keep: int = DEFAULT_KEEP):
    if not BACKUP_DIR.exists():
        return
    backups = sorted(BACKUP_DIR.glob("agents_*.db"), reverse=True)
    regular_backups = [f for f in backups if not f.name.startswith("agents_pre_restore")]
    if len(regular_backups) > keep:
        for old_file in regular_backups[keep:]:
            old_file.unlink()
            print(f"[CLEAN] 已删除旧备份: {old_file.name}")
    print(f"[INFO] 当前保留 {min(len(regular_backups), keep)} 份备份")


def main():
    parser = argparse.ArgumentParser(description="my_agents — 数据库备份工具")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--restore", type=str)
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help=f"保留最近 N 份备份（默认 {DEFAULT_KEEP}）")
    args = parser.parse_args()
    if args.list:
        list_backups()
    elif args.restore:
        restore_backup(args.restore)
    else:
        create_backup(keep=args.keep)


if __name__ == "__main__":
    main()
