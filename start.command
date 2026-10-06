#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
  echo '先にREADMEの初回設定を行ってください。'
  read -r -p 'Enterで終了'
  exit 1
fi
.venv/bin/python fancrew_notifier.py "$@"
