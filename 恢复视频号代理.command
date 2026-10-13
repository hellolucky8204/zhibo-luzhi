#!/bin/bash
set -e
cd "$(dirname "$0")"
sudo .venv/bin/python system_proxy.py restore
