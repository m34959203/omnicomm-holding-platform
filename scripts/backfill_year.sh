#!/usr/bin/env bash
# Помесячная заливка года в локальный архив, бережно к Omnicomm.
# По каждому месяцу (свежие → старые): сначала агрегаты (store_only, диапазон без
# перекрытия) → затем треки (days=m*31, present-skip берёт только фронт месяца).
# Резюмируемо: повторный запуск пропускает уже добранное. Лог — logs/backfill_year.log.
set -u
cd /home/ubuntu/omnicomm-holding-platform
API=127.0.0.1:8810
MONTHS=${MONTHS:-12}
TRACK_CAP=${TRACK_CAP:-43200}      # до 12ч на месячный слайс треков (хватит/добьёт след. месяц)

log(){ echo "[$(date '+%F %T')] $*"; }
jget(){ python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('$1',''))" 2>/dev/null; }

active_sync(){ curl -s "$API/api/sync/incremental" -X POST -H 'Content-Type: application/json' -d '{}' ; }

wait_job(){ # $1=id $2=label
  local id="$1" lbl="$2" st pct msg snap
  [ -z "$id" ] && { log "$lbl: нет job id"; return 1; }
  while :; do
    snap=$(curl -s "$API/api/sync/$id")
    st=$(echo "$snap" | jget status); pct=$(echo "$snap" | jget pct); msg=$(echo "$snap" | jget message)
    log "$lbl: $st ${pct}% — $msg"
    [ "$st" = done ] && return 0
    [ "$st" = error ] && return 1
    sleep 45
  done
}

post_wait(){ # $1=path $2=json $3=label ; обрабатывает single-flight (already_running)
  local path="$1" js="$2" lbl="$3" resp id already
  while :; do
    resp=$(curl -s -X POST "$API$path" -H 'Content-Type: application/json' -d "$js")
    id=$(echo "$resp" | jget id); already=$(echo "$resp" | jget already_running)
    if [ "$already" = "True" ] || [ "$already" = "true" ]; then
      log "$lbl: занят другой задачей ($id) — жду"; wait_job "$id" "  ↳ посторонняя"; sleep 5; continue
    fi
    wait_job "$id" "$lbl"; return $?
  done
}

log "=========== BACKFILL ГОДА: $MONTHS мес., свежие→старые ==========="
for m in $(seq 1 "$MONTHS"); do
  s=$((m*31)); e=$(((m-1)*31)); d=$((m*31)); [ $d -gt 365 ] && d=365
  log "----- Месяц $m/$MONTHS (сутки ${s}..${e} назад) -----"
  post_wait /api/sync/incremental "{\"store_only\":true,\"ingest_start_days\":$s,\"ingest_end_days\":$e}" "Агрегаты M$m"
  post_wait /api/track/backfill "{\"days\":$d,\"max_seconds\":$TRACK_CAP}" "Треки M$m"
  log "Покрытие треков после M$m: $(curl -s "$API/api/track/coverage")"
done
log "=========== BACKFILL ГОДА ЗАВЕРШЁН ==========="
