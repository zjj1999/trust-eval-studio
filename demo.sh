#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$PROJECT_DIR/runs/team-demo"

if ! command -v python3 >/dev/null 2>&1; then
  echo "TrustEval Studio 需要 Python 3.9 或更高版本。" >&2
  exit 1
fi

PYTHONPATH="$PROJECT_DIR/src" python3 -m trust_eval demo --workspace "$WORKSPACE_DIR"

REPORT_PATH="$WORKSPACE_DIR/report.html"

echo
echo "Demo 已完成。"
echo "可视化报告：$REPORT_PATH"
echo "算法报告：$WORKSPACE_DIR/algorithm-report.md"

if command -v open >/dev/null 2>&1; then
  open "$REPORT_PATH"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$REPORT_PATH" >/dev/null 2>&1 || true
fi
