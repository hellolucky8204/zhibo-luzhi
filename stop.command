#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ -f data/proxy/system-backup.json ]; then sudo .venv/bin/python system_proxy.py restore; fi
curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8769/api/shutdown
