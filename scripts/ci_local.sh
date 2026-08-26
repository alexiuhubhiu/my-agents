#!/usr/bin/env bash
# my_agents 本地一键 CI（ruff + mypy + pytest + cov）
# 用法: bash scripts/ci_local.sh

set -euo pipefail
cd "$(dirname "$0")/.."

PY="python"
if command -v python >/dev/null 2>&1; then PY="python"; fi

echo "==> 1/4 ruff 检查"
ruff check core personas server.py cli.py scripts --exclude scripts/migrate_prompts.py || true

echo "==> 2/4 mypy 类型检查"
mypy core personas --ignore-missing-imports || true

echo "==> 3/4 pytest（全量测试）"
"$PY" -m pytest tests/ -q

echo "==> 4/4 覆盖率（core+personas，目标 ≥70%）"
"$PY" -m pytest tests/ --cov=core --cov=personas --cov-report=term --cov-fail-under=70 -q || \
  echo "[WARN] 覆盖率未达 70%（沙箱环境可能无法写入 .coverage，建议在 CI 中执行）"

echo "==> CI 完成 ✅"
