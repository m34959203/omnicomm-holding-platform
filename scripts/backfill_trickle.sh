#!/usr/bin/env bash
# Бережный авто-трикл бэкфилла года: health-gate → микро-слайс агрегатов → треков.
# Грузит копю ТОЛЬКО когда она здорова; иначе пропускает прогон. Резюм-логика
# (ingest_progress + present-skip) копит год за много прогонов. Под flock в cron.
# Лог — logs/backfill_trickle.log.
set -u
cd /home/ubuntu/omnicomm-holding-platform
API=127.0.0.1:8810
AGG_CAP=${AGG_CAP:-900}        # сек на слайс агрегатов (микро)
TRK_CAP=${TRK_CAP:-900}        # сек на слайс треков (микро)
YEAR=${YEAR:-365}

log(){ echo "[$(date '+%F %T')] $*"; }
jget(){ python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null; }

# 1) HEALTH-GATE — грузим только при ok=True
h=$(curl -s -m90 "$API/api/omnicomm/health")
ok=$(echo "$h" | jget ok)
if [ "$ok" != "True" ]; then
  log "копя НЕ здорова → пропускаю прогон: $h"
  exit 0
fi
log "копя здорова ($h) — слайс пошёл"

wait_job(){ # $1=id $2=label
  local id="$1" lbl="$2" st
  [ -z "$id" ] && { log "$lbl: нет job id"; return 1; }
  while :; do
    st=$(curl -s "$API/api/sync/$id" | jget status)
    [ "$st" = done ] && { log "$lbl: done"; return 0; }
    [ "$st" = error ] && { log "$lbl: ERROR — $(curl -s "$API/api/sync/$id" | jget message)"; return 1; }
    [ -z "$st" ] && { log "$lbl: задача пропала"; return 1; }
    sleep 20
  done
}

# 2) микро-слайс АГРЕГАТОВ за весь год (store_only, резюм: тянет только дыры)
id=$(curl -s -X POST "$API/api/sync/incremental" -H 'Content-Type: application/json' \
  -d "{\"store_only\":true,\"ingest_start_days\":$YEAR,\"ingest_end_days\":0,\"max_seconds\":$AGG_CAP}" | jget id)
log "агрегаты слайс job=$id"; wait_job "$id" "Агрегаты"

# 3) микро-слайс ТРЕКОВ за весь год (адаптивно, present-skip фронта)
id=$(curl -s -X POST "$API/api/track/backfill" -H 'Content-Type: application/json' \
  -d "{\"days\":$YEAR,\"max_seconds\":$TRK_CAP,\"adaptive\":true}" | jget id)
log "треки слайс job=$id"; wait_job "$id" "Треки"

log "покрытие: агрегаты=$(curl -s $API/api/track/coverage)"
log "=== прогон завершён ==="
