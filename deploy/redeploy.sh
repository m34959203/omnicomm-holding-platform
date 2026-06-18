#!/usr/bin/env bash
# Деплой: подтянуть код, обновить зависимости, перезапустить процессы.
# Один шаг после `git push`: на сервере `deploy/redeploy.sh`.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
pip install -q -r requirements.txt || true
exec deploy/run.sh
