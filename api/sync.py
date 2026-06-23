"""Оркестрация синка: Omnicomm → расчёт → снапшот в кэш.

Один проход считает ГОТОВЫЙ снапшот дашборда (KPI-дерево + экономика холдинга +
рекомендации СТ КАП + геозоны) и кладёт в `cache`. Все чтения фронта берут его
оттуда мгновенно. Запускается фоновой задачей (`jobs`), репортит прогресс.

`demo=True` — без сети (демо-парк), поэтому пайплайн целиком прогоняется и
тестируется в любой среде. Live-путь забирает телеметрию КОНКУРЕНТНО (`fetch`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from omnicomm_report import (
    classify, config, data_loader, demo_data, economics, geozones, org as org_mod,
    recommendations, rollup, speeding, validator)
from omnicomm_report.models import ReportPeriod

from . import cache, fetch, health, serialize

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
    sensor_section = None     # «Качество данных» (R7) — заполняется ниже
    maint_section = None      # «Контроль ТО» (R6)
    if demo:
        registry = demo_data.build_demo_registry()
        tree, vehicle_org = registry.tree, registry.vehicle_org
        vehicles = demo_data.demo_fleet(period)
        progress(65, "Демо-парк собран")
        violations = _demo_violations(vehicles)
        sensor_section = health.build_sensor_health_demo(vehicles, now=end_ts)
        maint_section = health.build_maintenance_demo(vehicles)
    else:
        # Дерево организаций строим из ЖИВОГО дерева ТС КАП (самообновляемо),
        # а не из устаревшего реестра на диске.
        client = _new_live_client()
        progress(4, "Построение иерархии организаций из дерева КАП")
        tree, vehicle_org = org_mod.build_from_omnicomm_tree(client.get_vehicle_tree())
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
        tree_vehicles = client.list_vehicles() or []
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

    org_mod.assign_org_ids(vehicles, vehicle_org)

    progress(80, "Расчёт KPI по иерархии")
    kpi_tree = rollup.build_org_kpi_tree(
        vehicles, tree, fuel_price_kzt=fuel_price_kzt,
        vehicle_org=vehicle_org)

    progress(88, "Экономика и рекомендации")
    from omnicomm_report import dashboard
    holding_id = kpi_tree[0].org.org_id if kpi_tree else None
    eco = None
    if holding_id:
        # Вентиль доверия: экономику (потери/COI/рейтинг «Первоочередные ТС»)
        # считаем ТОЛЬКО по транспорту — стационарные объекты (АЗС/ёмкости/ФЭС/
        # генераторы) не машины и не должны «жечь топливо» в денежном рейтинге.
        transport = [v for v in vehicles if classify.is_transport(v.name)]
        rep = dashboard.build_org_report(
            holding_id, transport, period, tree,
            vehicle_org=vehicle_org, fuel_price_kzt=fuel_price_kzt)
        eco = economics.build_economics(rep)
        if eco is not None:  # подстраховка, если имя просочилось из другого источника
            eco.worst_vehicles = [
                (n, v) for (n, v) in eco.worst_vehicles if classify.is_transport(n)]
    recs = recommendations.recommend_fleet(
        violations, names={str(v.vehicle_id): v.name for v in vehicles})
    # И из рекомендаций по скоростному режиму (стационарный объект не «нарушитель»).
    recs = [r for r in recs if classify.is_transport(getattr(r, "name", None))]

    progress(94, "Геозоны для карты")
    snapshot = {
        "period": {"start_ts": start_ts, "end_ts": end_ts, "label": period.human()},
        "fleet": {"vehicles": len(vehicles),
                  "with_data": sum(1 for v in vehicles if getattr(v, "has_data", False))},
        "orgs": serialize.kpi_tree(kpi_tree),
        "economics": serialize.economics_dict(eco) if eco else None,
        "recommendations": [serialize.recommendation_dict(r) for r in recs],
        "vehicle_org": dict(vehicle_org),
        "geozones": serialize.geozone_features_json(raw_geozones),
        "sensor_health": sensor_section,
        "maintenance": maint_section,
    }
    synced_at = cache.save_snapshot(snapshot, period_key=pkey,
                                    label=period.human(), path=cache_path)
    progress(100, "Снапшот сохранён")
    return {"period_key": pkey, "synced_at": synced_at,
            "vehicles": len(vehicles), "recommendations": len(recs)}
