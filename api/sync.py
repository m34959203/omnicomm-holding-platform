"""Оркестрация синка: Omnicomm → расчёт → снапшот в кэш.

Один проход считает ГОТОВЫЙ снапшот дашборда (KPI-дерево + экономика холдинга +
рекомендации СТ КАП + геозоны) и кладёт в `cache`. Все чтения фронта берут его
оттуда мгновенно. Запускается фоновой задачей (`jobs`), репортит прогресс.

`demo=True` — без сети (демо-парк), поэтому пайплайн целиком прогоняется и
тестируется в любой среде. Live-путь забирает телеметрию КОНКУРЕНТНО (`fetch`).
"""

from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout, as_completed
from datetime import datetime, timezone
from typing import Callable, Optional

from omnicomm_report import (
    classify, config, data_loader, demo_data, economics, geozones, org as org_mod,
    recommendations, reports, rollup, speeding, validator)
from omnicomm_report.api_client import MAX_VEHICLES_PER_REPORT
from omnicomm_report.models import ReportPeriod

from . import cache, fetch, fleet_cache, health, serialize, tyres

ProgressCb = Callable[[float, str], None]

DEFAULT_REGISTRY = "data/org_registry.db"


def _period_key(period: ReportPeriod) -> str:
    return f"{period.start:%Y-%m-%d}_{period.end:%Y-%m-%d}"


def _dedup_records(records: list) -> list:
    """Оставить одну строку на (ТС, сутки) — защита от задвоения граничных дней
    при оконном чанкинге (агрегация суммирует суточные строки)."""
    seen: set = set()
    out = []
    for r in records or []:
        cr = r.get("consolidatedReport") if isinstance(r.get("consolidatedReport"), dict) else r
        key = (cr.get("vehicleId") or cr.get("id"), cr.get("date"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _batch_key(chunk) -> str:
    """Стабильный ключ пачки ТС — хэш отсортированных terminal_id (не зависит от порядка)."""
    return hashlib.md5(",".join(map(str, sorted(chunk))).encode()).hexdigest()[:16]


def _aligned_windows(start_ts: int, end_ts: int, window_days: int) -> list:
    """Окна забора по ФИКСИРОВАННОЙ сетке (кратной window_days от эпохи), а НЕ от `now`.

    Критично для resume: границы окон должны совпадать между запусками, иначе ключи
    чекпоинтов не сойдутся. Привязка к сетке `(ts // W) * W` даёт одни и те же окна
    при любом `now`."""
    W = max(1, window_days) * 86400
    sd = (int(start_ts) // 86400) * 86400
    ed = (int(end_ts) // 86400) * 86400
    out, w = [], (sd // W) * W
    while w < ed:
        out.append((w, min(w + W, ed)))
        w += W
    return out


def _resumable_ingest(progress: ProgressCb, ids: list, ing_start: int, ing_end: int, *,
                      raw_path: str, workers: int, max_seconds: float,
                      refresh_floor: int, pct_from: float = 4.0,
                      pct_to: float = 90.0, make_client=None) -> dict:
    """Поштучно-резюмируемый забор агрегатов: единица = (окно сетки × пачка ≤50 ТС).

    Пропускает уже забранные единицы (журнал `ingest_progress`), тянет только дыры,
    upsert + чекпоинт на КАЖДУЮ единицу (durable при капе). Свежие окна (`end > refresh_floor`)
    всегда тянем заново и НЕ чекпоинтим (данные ещё оседают). Кап по времени = просто
    «достроим в следующий слайс», не обрезка."""
    from . import raw_store
    make_client = make_client or _new_live_client
    windows = _aligned_windows(ing_start, ing_end, config.REPORT_WINDOW_DAYS)
    chunks = [ids[i:i + MAX_VEHICLES_PER_REPORT]
              for i in range(0, len(ids), MAX_VEHICLES_PER_REPORT)]
    total_all = len(chunks) * len(windows)
    if not windows or not chunks:
        return {"ingested": 0, "units_total": 0, "units_run": 0, "already_done": 0,
                "stopped": False}
    done = raw_store.done_units(windows[0][0], windows[-1][1], raw_path)

    units = []
    for ch in chunks:
        bk = _batch_key(ch)
        for (wb, we) in windows:
            fresh = we > refresh_floor                 # свежее окно — всегда тянем
            if not fresh and (wb, we, bk) in done:
                continue                               # уже забрано — resume-skip
            units.append((ch, wb, we, bk, fresh))

    deadline = time.monotonic() + max_seconds
    tls = threading.local()

    def _client():
        c = getattr(tls, "client", None)
        if c is None:
            c = make_client()
            tls.client = c
        return c

    def _work(u):
        ch, wb, we, bk, fresh = u
        if time.monotonic() >= deadline:
            return None
        per = ReportPeriod(start=datetime.fromtimestamp(wb, timezone.utc),
                           end=datetime.fromtimestamp(we, timezone.utc))
        try:
            return (u, _client().get_consolidated_report(ch, per) or [])
        except Exception:                              # noqa: BLE001 — сбой единицы не валит забор
            return None

    ingested = 0
    stopped = False
    progress(pct_from, f"Агрегаты (резюм): {len(units)} ед. к забору, "
                       f"{total_all - len(units)} уже есть")
    ex = ThreadPoolExecutor(max_workers=max(1, min(workers, len(units))))
    futures = [ex.submit(_work, u) for u in units]
    span = max(0.0, pct_to - pct_from)
    try:
        n = 0
        for fut in as_completed(futures, timeout=max_seconds):
            n += 1
            r = fut.result()
            if r is not None:
                (ch, wb, we, bk, fresh), res = r
                recs = _dedup_records(data_loader._extract_records(res))
                raw_store.upsert_daily(recs, raw_path)             # поштучный upsert
                if not fresh:
                    raw_store.mark_unit_done(wb, we, bk, raw_path)  # чекпоинт единицы
                ingested += len(recs)
            if n % 20 == 0 or n == len(units):
                progress(pct_from + span * n / len(units),
                         f"Агрегаты {n}/{len(units)} ед. · +{ingested} строк")
    except FTimeout:
        stopped = True
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return {"ingested": ingested, "units_total": total_all, "units_run": len(units),
            "already_done": total_all - len(units), "stopped": stopped}


def _new_live_client():
    """Залогиненный клиент Omnicomm (по потоку — для параллельного забора)."""
    from omnicomm_report.api_client import OmnicommClient
    from omnicomm_report.config import Settings
    client = OmnicommClient(Settings.from_env())
    client.login()
    return client


def _demo_violations(vehicles) -> dict:
    """Синтетические превышения для демо (показать движок СТ КАП без сети)."""
    out: dict = {}
    for v in vehicles:
        ms = v.max_speed_kmh or 0
        if ms <= 60:
            continue
        excess = round(ms - 60, 1)
        public = (abs(hash(str(v.vehicle_id))) % 2 == 0)
        art, fine = (speeding.koap_for(excess) if public else (None, None))
        out[str(v.vehicle_id)] = [speeding.Violation(
            terminal_id=str(v.vehicle_id), geozone="Демо-участок 60 км/ч",
            limit=60, max_speed=float(ms), excess=excess, duration_s=300,
            start_ts=0, points=1, public_road=public,
            st_kap_severity=speeding.st_kap_severity(excess),
            koap_article=art, fine_kzt=fine)]
    return out


def _assemble_snapshot(*, vehicles, tree, vehicle_org, period, violations,
                       raw_geozones, sensor_section, maint_section,
                       fuel_price_kzt, progress, visits=None,
                       seed_accounts: bool = False, tyre_section=None,
                       geozones_override=None) -> dict:
    """Собрать снапшот дашборда из готовых ТС/визитов (общий хвост для полного и
    инкрементального синка): роллапы KPI → экономика (вентиль доверия) →
    рекомендации СТ КАП → геозоны + секции качества данных и ТО."""
    org_mod.assign_org_ids(vehicles, vehicle_org)
    progress(80, "Расчёт KPI по иерархии")
    kpi_tree = rollup.build_org_kpi_tree(
        vehicles, tree, fuel_price_kzt=fuel_price_kzt, vehicle_org=vehicle_org)

    if seed_accounts:
        # Авто-сидинг учёток на НОВЫЕ каноничные узлы (второй слой синхронизации
        # структуры). Идемпотентно/аддитивно; не должен ронять синк.
        try:
            from api import account_seed
            new_accounts = account_seed.seed_new_accounts(kpi_tree)
            if new_accounts:
                progress(89, f"Заведено учёток на новые ДЗО: {len(new_accounts)} "
                             f"({', '.join(a['login'] for a in new_accounts[:5])}"
                             f"{'…' if len(new_accounts) > 5 else ''})")
        except Exception:  # noqa: BLE001 — сидинг не критичен для снапшота
            pass

    progress(88, "Экономика и рекомендации")
    from omnicomm_report import dashboard
    holding_id = kpi_tree[0].org.org_id if kpi_tree else None
    eco = None
    eco_by_org: dict = {}
    if holding_id:
        # Вентиль доверия: экономику считаем ТОЛЬКО по транспорту (без АЗС/ёмкостей/ФЭС).
        transport = [v for v in vehicles if classify.is_transport(v.name)]

        def _eco_for(org_id):
            rep_o = dashboard.build_org_report(
                org_id, transport, period, tree,
                vehicle_org=vehicle_org, fuel_price_kzt=fuel_price_kzt)
            e = economics.build_economics(rep_o)
            if e is not None:
                e.worst_vehicles = [(n, v) for (n, v) in e.worst_vehicles if classify.is_transport(n)]
            return e

        eco = _eco_for(holding_id)
        # Экономика ПО КАЖДОМУ узлу — для серверного скоупа ДЗО (BUG-7), из тех же
        # transport-ТС по поддереву (без обращения к копе).
        def _walk(nodes):
            for n in nodes:
                try:
                    e = _eco_for(n.org.org_id)
                    if e is not None:
                        eco_by_org[str(n.org.org_id)] = serialize.economics_dict(e)
                except Exception:  # noqa: BLE001 — узел без данных не должен ронять синк
                    pass
                _walk(n.children)
        _walk(kpi_tree)
    recs = recommendations.recommend_fleet(
        violations, names={str(v.vehicle_id): v.name for v in vehicles})
    recs = [r for r in recs if classify.is_transport(getattr(r, "name", None))]

    progress(94, "Геозоны для карты")
    return {
        "period": {"start_ts": period.start_ts, "end_ts": period.end_ts, "label": period.human()},
        "fleet": {"vehicles": len(vehicles),
                  "with_data": sum(1 for v in vehicles if getattr(v, "has_data", False))},
        "orgs": serialize.kpi_tree(kpi_tree),
        "economics": serialize.economics_dict(eco) if eco else None,
        "economics_by_org": eco_by_org,
        "recommendations": [serialize.recommendation_dict(r) for r in recs],
        "vehicle_org": dict(vehicle_org),
        # Геометрия геозон от периода не зависит — в range-сборке переиспользуем
        # готовые фичи из базового снимка (geozones_override), не сериализуя заново.
        "geozones": (geozones_override if geozones_override is not None
                     else serialize.geozone_features_json(raw_geozones)),
        "sensor_health": sensor_section,
        "maintenance": maint_section,
        "tyres": tyre_section,
        # Отчётные формы паритета (kb-14): данные уже на руках.
        "geozone_visits": reports.build_geozone_visits(
            visits or [], {str(v.vehicle_id): v.name for v in vehicles}),
        "fleet_table": reports.build_fleet_table(vehicles, vehicle_org),
        "violations": reports.build_violations(
            violations, vehicles, {str(v.vehicle_id): v.name for v in vehicles}),
        "fuel": reports.build_fuel(vehicles),
    }


# --- Произвольный диапазон из АРХИВА (без Omnicomm) -------------------------------

RANGE_MAX_DAYS = 400   # защитный потолок (архив ≈ год)


def _reconstruct_base(base: dict):
    """Восстановить OrgTree + vehicle_org + name_map из готового снимка — для сборки
    произвольного диапазона из архива БЕЗ обращения в Omnicomm (структура/имена ТС
    от периода не зависят, берём из последнего снимка)."""
    orgs = []

    def walk(node, parent_id):
        oid = str(node.get("org_id"))
        try:
            lvl = org_mod.OrgLevel(node.get("level") or "unknown")
        except ValueError:
            lvl = org_mod.OrgLevel.UNKNOWN
        orgs.append(org_mod.Org(org_id=oid, name=node.get("name") or "",
                                parent_id=(str(parent_id) if parent_id else None),
                                level=lvl, type=org_mod.OrgType.OWN))
        for ch in node.get("children") or []:
            walk(ch, oid)

    for root in base.get("orgs") or []:
        walk(root, None)
    tree = org_mod.OrgTree(orgs)
    vehicle_org = {str(k): str(v) for k, v in (base.get("vehicle_org") or {}).items()}
    name_map = {str(r.get("vehicle_id")): r.get("vehicle")
                for r in ((base.get("fleet_table") or {}).get("rows") or [])
                if r.get("vehicle_id")}
    return tree, vehicle_org, name_map


def build_range_snapshot(start_ts: int, end_ts: int, *,
                         cache_path: str = cache.DEFAULT_PATH,
                         raw_path: str = None,
                         fuel_price_kzt: float = 0.0,
                         progress: ProgressCb = None) -> Optional[dict]:
    """Собрать снимок за ПРОИЗВОЛЬНЫЙ диапазон из ЛОКАЛЬНОГО архива — без единого
    обращения в Omnicomm. Период-зависимые секции (KPI/экономика/нарушения/топливо/
    таблицы) считаются из `raw_store`; секции текущего состояния (геометрия геозон,
    Sensor Health, Контроль ТО) переиспользуются из последнего снимка. Кэшируется по
    period_key. Возвращает `{period_key, synced_at, label}` или None (нет базы/данных)."""
    from . import raw_store
    progress = progress or (lambda *_: None)
    raw_path = raw_path or raw_store.DEFAULT_PATH
    base = cache.latest_snapshot(path=cache_path)
    if not base:
        return None
    period = ReportPeriod(start=datetime.fromtimestamp(start_ts, timezone.utc),
                          end=datetime.fromtimestamp(end_ts, timezone.utc))
    pkey = _period_key(period)
    progress(20, "Сборка диапазона из архива")
    tree, vehicle_org, name_map = _reconstruct_base(base)
    records = raw_store.load_daily(start_ts, end_ts, raw_path)
    vehicles = validator.validate(data_loader._aggregate_consolidated(records, name_map))
    if not vehicles:
        return None
    visits = raw_store.load_visits(start_ts, end_ts, raw_path)
    violations = speeding.detect_from_visits(visits, seed=None)
    snap = _assemble_snapshot(
        vehicles=vehicles, tree=tree, vehicle_org=vehicle_org, period=period,
        violations=violations, raw_geozones=None,
        geozones_override=base.get("geozones"),
        sensor_section=base.get("sensor_health"), maint_section=base.get("maintenance"),
        tyre_section=base.get("tyres"),
        fuel_price_kzt=fuel_price_kzt or config.DEFAULT_FUEL_PRICE_KZT,
        progress=lambda *_: None, visits=visits, seed_accounts=False)
    synced_at = cache.save_snapshot(snap, period_key=pkey, label=period.human(),
                                    path=cache_path)
    progress(100, "Диапазон готов")
    return {"period_key": pkey, "synced_at": synced_at, "label": period.human()}


def prewarm_ranges(day_list, *, cache_path: str = cache.DEFAULT_PATH,
                   raw_path: str = None, now: int = None) -> list[str]:
    """Пред-прогреть трейлинг-окна (в сутках) из архива, чтобы частые периоды
    отдавались мгновенно. Уже закэшированные ключи пропускаются. Возвращает список
    собранных period_key."""
    now = now or int(time.time())
    existing = {s["period_key"] for s in cache.list_snapshots(path=cache_path)}
    done = []
    for d in day_list:
        period = ReportPeriod(start=datetime.fromtimestamp(now - d * 86400, timezone.utc),
                              end=datetime.fromtimestamp(now, timezone.utc))
        if _period_key(period) in existing:
            continue
        try:
            r = build_range_snapshot(now - d * 86400, now,
                                     cache_path=cache_path, raw_path=raw_path)
            if r:
                done.append(r["period_key"])
        except Exception:  # noqa: BLE001 — прогрев не критичен
            pass
    return done


def run_incremental_sync(progress: ProgressCb, *, ingest_days: int = None,
                         view_days: int = None, fuel_price_kzt: float = 0.0,
                         workers: int = 6, cache_path: str = cache.DEFAULT_PATH,
                         raw_path: str = None, ingest_start_days: int = None,
                         ingest_end_days: int = None, store_only: bool = False,
                         max_seconds: float = None) -> dict:
    """Инкрементальный синк: довезти ТОЛЬКО свежие сутки в сырое хранилище и
    пересобрать снимок из НАКОПЛЕННОГО за view-окно (историю не перезабираем).

    Подходит для частого (каждые 3ч) обновления: тянем `ingest_days` последних
    суток (дёшево, чанками), кладём в `raw_store` (upsert по ТС×сутки/визиту —
    текущий день перезаписывается), затем строим снапшот из store за `view_days`.

    Backfill истории БЕЗ ПЕРЕКРЫТИЯ (помесячно): задать окно явным диапазоном
    `ingest_start_days`..`ingest_end_days` (суток назад от now, start>end) +
    `store_only=True` — тогда тянем ровно этот месяц ОДИН раз в `raw_store` и НЕ
    пересобираем снимок. Так каждый месяц года забирается ровно однажды (не нагружаем
    Omnicomm), а не трейлинг-окном `ingest_days`, которое перетягивало бы ранние месяцы.
    """
    from . import raw_store
    ingest_days = ingest_days or config.INGEST_WINDOW_DAYS
    view_days = view_days or config.VIEW_WINDOW_DAYS
    raw_path = raw_path or raw_store.DEFAULT_PATH
    now = int(time.time())
    if ingest_start_days is not None:        # явный диапазон месяца (backfill без перекрытия)
        ing_start = now - ingest_start_days * 86400
        ing_end = now - (ingest_end_days or 0) * 86400
    else:                                    # трейлинг-окно свежих суток (штатный синк)
        ing_start, ing_end = now - ingest_days * 86400, now
    ingest = ReportPeriod(start=datetime.fromtimestamp(ing_start, timezone.utc),
                          end=datetime.fromtimestamp(ing_end, timezone.utc))
    win_days = max(1.0, (ing_end - ing_start) / 86400.0)
    view = ReportPeriod(start=datetime.fromtimestamp(now - view_days * 86400, timezone.utc),
                        end=datetime.fromtimestamp(now, timezone.utc))
    pkey = _period_key(view)
    progress(2, (f"Backfill агрегатов: окно {win_days:.0f} сут "
                 f"({ingest_start_days}…{ingest_end_days or 0} сут назад), store-only"
                 if store_only else
                 f"Инкрементальный синк: довоз {ingest_days} сут, окно {view_days} сут"))

    client = _new_live_client()
    tree, vehicle_org = org_mod.build_from_omnicomm_tree(fleet_cache.vehicle_tree(client))
    ids = list(vehicle_org.keys())
    tree_vehicles = fleet_cache.list_vehicles(client)
    name_map = {str(v.get("terminal_id") or v.get("id") or v.get("uuid")): v.get("name")
                for v in tree_vehicles
                if (v.get("terminal_id") or v.get("id") or v.get("uuid")) and v.get("name")}

    # ДОВОЗ суток ingest-окна → сырое хранилище (бюджет масштабируем под длину окна,
    # либо явный max_seconds — для микро-слайсов трикла; резюм-логика добёрет за слайсы).
    ing_budget = max_seconds if max_seconds else min(480 + win_days * 80, 3000)
    if store_only:
        # Помесячный backfill — ПОШТУЧНО-РЕЗЮМИРУЕМЫЙ: тянем только дыры, чекпоинт на
        # каждую единицу. Кап = «достроим в след. слайс», не обрезка (см. _resumable_ingest).
        refresh_floor = now - config.INGEST_WINDOW_DAYS * 86400
        ing = _resumable_ingest(
            progress, ids, ing_start, ing_end, raw_path=raw_path, workers=workers,
            max_seconds=ing_budget, refresh_floor=refresh_floor, pct_from=4, pct_to=88)
    else:
        payload = fetch.fetch_report_parallel(
            _new_live_client, ids, ingest,
            call=lambda c, ch, p: c.get_consolidated_report(ch, p),
            label="Довоз телеметрии", workers=workers, progress=progress,
            pct_from=4, pct_to=50, best_effort=True,
            max_seconds=ing_budget, window_days=config.REPORT_WINDOW_DAYS)
        new_daily = _dedup_records(data_loader._extract_records(payload))
        raw_store.upsert_daily(new_daily, raw_path)

    # Визиты геозон (best-effort) — для обоих путей.
    try:
        visits_new = fetch.fetch_report_parallel(
            _new_live_client, ids, ingest,
            call=lambda c, ch, p: c.get_geozones_report(ch, p),
            label="Довоз геозон", workers=workers, progress=progress,
            pct_from=(88 if store_only else 50), pct_to=(96 if store_only else 60),
            best_effort=True, max_seconds=min(120 + win_days * 20, 600),
            window_days=config.REPORT_WINDOW_DAYS)
        raw_store.upsert_visits(visits_new, raw_path)
    except Exception:  # noqa: BLE001
        pass

    # store_only (помесячный backfill): снимок НЕ пересобираем — только наполнили архив.
    if store_only:
        cov = raw_store.coverage(raw_path)
        tail = "; кап — достроится в след. слайс" if ing["stopped"] else ""
        progress(100, f"Месяц: +{ing['ingested']} строк, забрано {ing['units_run']} ед. "
                      f"(+{ing['already_done']} уже было){tail}")
        return {"ingested": ing["ingested"], "units_run": ing["units_run"],
                "already_done": ing["already_done"], "stopped_by_cap": ing["stopped"],
                "store": cov, "store_only": True, "window_days": int(win_days)}

    # ПЕРЕСБОРКА снимка из НАКОПЛЕННОГО store за view-окно (без обращений в Omnicomm).
    progress(64, "Сборка снимка из накопленных данных")
    records = raw_store.load_daily(view.start_ts, view.end_ts, raw_path)
    vehicles = validator.validate(data_loader._aggregate_consolidated(records, name_map))
    if not vehicles:
        raise RuntimeError("Инкрементальный синк: в хранилище нет данных за окно — "
                           "снапшот не сохранён (запустите backfill)")
    visits = raw_store.load_visits(view.start_ts, view.end_ts, raw_path)
    raw_geozones = client.list_geozones()
    seed = geozones.build_seed(raw_geozones)
    violations = speeding.detect_from_visits(visits, seed=seed)

    try:
        activity = client.get_activity()
    except Exception:  # noqa: BLE001
        activity = []
    sensor_section = health.build_sensor_health(
        activity, records, tree_vehicles, now=now, fetch_state=client.get_vehicle_state)
    maint_section = health.build_maintenance(records, vehicles)
    # Шины: пробег комплекта копится с установки из ВСЕГО архива (не за окно).
    tyre_section = tyres.build_tyres(vehicles, now_ts=now, raw_path=raw_path)

    snapshot = _assemble_snapshot(
        vehicles=vehicles, tree=tree, vehicle_org=vehicle_org, period=view,
        violations=violations, raw_geozones=raw_geozones,
        sensor_section=sensor_section, maint_section=maint_section,
        tyre_section=tyre_section,
        fuel_price_kzt=fuel_price_kzt, progress=progress, visits=visits,
        seed_accounts=True)
    synced_at = cache.save_snapshot(snapshot, period_key=pkey, label=view.human(),
                                    path=cache_path)
    # Пред-прогрев частых окон из архива (неделя/квартал/полгода) — чтобы пилюли
    # периода отдавались мгновенно. Дёшево (сборка из store, без Omnicomm).
    try:
        warmed = prewarm_ranges([7, 90, 180], cache_path=cache_path,
                                raw_path=raw_path, now=now)
        if warmed:
            progress(99, f"Прогрев окон: {', '.join(warmed)}")
    except Exception:  # noqa: BLE001
        pass
    progress(100, "Снимок обновлён (инкрементально)")
    cov = raw_store.coverage(raw_path)
    return {"period_key": pkey, "synced_at": synced_at, "ingested": len(new_daily),
            "vehicles": len(vehicles), "recommendations": len(snapshot["recommendations"]),
            "store": cov}


def run_sync(progress: ProgressCb, *, demo: bool, start_ts: int, end_ts: int,
             fuel_price_kzt: float = 0.0, workers: int = 6,
             cache_path: str = cache.DEFAULT_PATH,
             registry_path: str = DEFAULT_REGISTRY) -> dict:
    """Полный синк периода → снапшот. Возвращает `{period_key, synced_at, ...}`."""
    period = ReportPeriod(start=datetime.fromtimestamp(start_ts, timezone.utc),
                          end=datetime.fromtimestamp(end_ts, timezone.utc))
    pkey = _period_key(period)
    progress(2, "Инициализация")

    raw_geozones: list = []
    visits: list = []         # визиты геозон (для формы «Посещение геозон»)
    sensor_section = None     # «Качество данных» (R7) — заполняется ниже
    maint_section = None      # «Контроль ТО» (R6)
    tyre_section = None       # «Учёт шин по пробегу»
    if demo:
        registry = demo_data.build_demo_registry()
        tree, vehicle_org = registry.tree, registry.vehicle_org
        vehicles = demo_data.demo_fleet(period)
        progress(65, "Демо-парк собран")
        violations = _demo_violations(vehicles)
        sensor_section = health.build_sensor_health_demo(vehicles, now=end_ts)
        maint_section = health.build_maintenance_demo(vehicles)
        tyre_section = tyres.build_tyres_demo(vehicles)
    else:
        # Дерево организаций строим из ЖИВОГО дерева ТС КАП (самообновляемо),
        # а не из устаревшего реестра на диске.
        client = _new_live_client()
        progress(4, "Построение иерархии организаций из дерева КАП")
        tree, vehicle_org = org_mod.build_from_omnicomm_tree(fleet_cache.vehicle_tree(client))
        ids = list(vehicle_org.keys())
        # Бюджет таймаута масштабируем под длину периода — чтобы месяц успел
        # собраться (чанкинг по REPORT_WINDOW_DAYS делает каждый запрос быстрым,
        # прогресс двигается по каждому окну).
        period_days = max(1.0, (end_ts - start_ts) / 86400.0)
        cons_budget = min(480 + period_days * 80, 2700)   # 2д≈640с … 30д≈2700с (потолок 45 мин)
        progress(5, f"Старт забора телеметрии: {len(ids)} ТС, период {period_days:.0f} сут")
        # best_effort: флапающий/таймаутящий запрос Omnicomm → пропуск, а не падение
        # всего синка (копия КАП нестабильна); пробелы добёрет следующий cron-синк.
        payload = fetch.fetch_report_parallel(
            _new_live_client, ids, period,
            call=lambda c, ch, p: c.get_consolidated_report(ch, p),
            label="Загрузка телеметрии", workers=workers, progress=progress,
            pct_from=5, pct_to=68, best_effort=True, max_seconds=cons_budget,
            window_days=config.REPORT_WINDOW_DAYS)
        tree_vehicles = fleet_cache.list_vehicles(client)
        name_map = {str(v.get("terminal_id") or v.get("id") or v.get("uuid")): v.get("name")
                    for v in tree_vehicles
                    if (v.get("terminal_id") or v.get("id") or v.get("uuid")) and v.get("name")}
        # Дедуп по (ТС, сутки): окна чанкинга могли захватить граничный день дважды,
        # а агрегация СУММИРУЕТ суточные строки → иначе двойной счёт топлива/пробега.
        records = _dedup_records(data_loader._extract_records(payload))
        vehicles = validator.validate(
            data_loader._aggregate_consolidated(records, name_map))
        progress(70, "Агрегация телеметрии")
        # Качество данных (R7) и контроль ТО (R6) — из тех же сырых строк/дерева.
        try:
            activity = client.get_activity()
        except Exception:  # noqa: BLE001 — светофор не валит синк
            activity = []
        sensor_section = health.build_sensor_health(
            activity, records, tree_vehicles, now=end_ts,
            fetch_state=client.get_vehicle_state)   # ур.1.5 — напряжение подозрительных
        maint_section = health.build_maintenance(records, vehicles)
        # Шины: пробег комплекта с установки из архива (не за окно синка).
        tyre_section = tyres.build_tyres(vehicles, now_ts=end_ts)
        # Карта геозон — лёгкий вызов (геометрия из list_geozones).
        raw_geozones = client.list_geozones()
        seed = geozones.build_seed(raw_geozones)
        # Скоростной режим (второй план): отчёт по геозонам ПАРАЛЛЕЛЬНО, best-effort,
        # с wall-clock-капом — если Omnicomm тормозит, синк не виснет; рекомендации
        # будут по тому, что успели собрать (полнее добёрет следующий cron-синк).
        try:
            geo_budget = min(120 + period_days * 20, 600)   # второй план: легче бюджет, потолок 10 мин
            visits = fetch.fetch_report_parallel(
                _new_live_client, ids, period,
                call=lambda c, ch, p: c.get_geozones_report(ch, p),
                label="Анализ геозон", workers=workers, progress=progress,
                pct_from=72, pct_to=79, best_effort=True, max_seconds=geo_budget,
                window_days=config.REPORT_WINDOW_DAYS)
            violations = speeding.detect_from_visits(visits, seed=seed)
        except Exception:  # noqa: BLE001 — детекция не валит снапшот
            violations = {}

    # Не затирать снапшот пустотой: если live-синк не получил ни одного ТС
    # (upstream недоступен/затроттлен) — падаем, оставляя прошлый снапшот в кэше.
    if not demo and not vehicles:
        raise RuntimeError("Live-синк не получил данных (Omnicomm недоступен) — "
                           "снапшот не сохранён, оставлен предыдущий")

    snapshot = _assemble_snapshot(
        vehicles=vehicles, tree=tree, vehicle_org=vehicle_org, period=period,
        violations=violations, raw_geozones=raw_geozones,
        sensor_section=sensor_section, maint_section=maint_section,
        tyre_section=tyre_section,
        fuel_price_kzt=fuel_price_kzt, progress=progress, visits=visits,
        seed_accounts=not demo)   # авто-сидинг учёток только на боевом дереве
    synced_at = cache.save_snapshot(snapshot, period_key=pkey,
                                    label=period.human(), path=cache_path)
    progress(100, "Снапшот сохранён")
    return {"period_key": pkey, "synced_at": synced_at,
            "vehicles": len(vehicles), "recommendations": len(snapshot["recommendations"])}
