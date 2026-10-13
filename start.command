#!/bin/bash
set -e
cd "$(dirname "$0")"
export PATH="$PWD/.venv/bin:$PATH"
if [ ! -x .venv/bin/python ]; then echo '请先按 README.md 安装依赖。'; exit 1; fi
if curl -fsS http://127.0.0.1:8769/api/state >/dev/null 2>&1; then open http://127.0.0.1:8769; exit 0; fi
nohup .venv/bin/python app.py 8769 > service.log 2>&1 &
sleep 1
curl -fsS http://127.0.0.1:8769/api/state >/dev/null || { echo '启动失败，请查看 service.log。'; exit 1; }
open http://127.0.0.1:8769
