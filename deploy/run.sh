#!/usr/bin/env bash
# Запуск/перезапуск платформы + планировщика (идемпотентно).
# Используется при деплое и для ручного рестарта после изменений.
set -euo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH="$PWD/src"
# Подхватить SMTP/прочие ENV из .env (если есть).
[ -f .env ] && { set -a; . ./.env; set +a; }
mkdir -p logs
PORT="${PORT:-8501}"

# Остановить прежние процессы (не трогаем cloudflared-туннель — он смотрит на порт).
pkill -f "streamlit run app.py" 2>/dev/null || true
pkill -f "omnicomm_report.scheduler" 2>/dev/null || true
sleep 2

# Планировщик авторассылки (демон).
nohup python3 -m omnicomm_report.scheduler >> logs/scheduler.log 2>&1 &
echo "scheduler PID $!"

# Платформа (Streamlit).
nohup python3 -m streamlit run app.py \
  --server.port "$PORT" --server.address 0.0.0.0 --server.headless true \
  --server.enableCORS false --server.enableXsrfProtection false \
  --browser.gatherUsageStats false >> logs/streamlit.log 2>&1 &
echo "streamlit PID $! on :$PORT"
echo "OK — логи в logs/"
