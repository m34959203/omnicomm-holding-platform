"""CLI-точка входа: оркестрация конвейера (ТЗ §13).

Конвейер: data_loader → validator → analytics → charts → report_builder.

Примеры:
    python -m omnicomm_report --source excel --input samples/fleet_sample.xlsx --client "ООО Пример"
    python -m omnicomm_report --source api --demo --from 2026-05-01 --to 2026-05-31
    python -m omnicomm_report holding --demo --from 2026-05-01 --to 2026-05-31 --fuel-price 320
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from datetime import datetime, time, timezone

from . import analytics, charts, data_loader, history, holding, norms, report_builder, validator
from .config import DEFAULT_FUEL_PRICE_KZT, Settings, load_env_file
from .models import ReportPeriod
from .org import OrgLevel

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("omnicomm_report")


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _preset_period(preset: str) -> ReportPeriod:
    """Готовый период для планировщика/cron относительно текущей даты (UTC)."""
    from datetime import timedelta
    today = datetime.now(timezone.utc).date()
    if preset == "last-day":
        d = today - timedelta(days=1)
        start_d, end_d = d, d
    elif preset == "last-week":
        start_d, end_d = today - timedelta(days=7), today - timedelta(days=1)
    elif preset == "last-month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        start_d, end_d = last_prev.replace(day=1), last_prev
    else:
        start_d, end_d = today.replace(day=1), today
    return ReportPeriod(
        start=datetime.combine(start_d, time.min, tzinfo=timezone.utc),
        end=datetime.combine(end_d, time.max, tzinfo=timezone.utc),
    )


def _build_period(args: argparse.Namespace) -> ReportPeriod:
    if args.preset:
        return _preset_period(args.preset)
    if args.source == "api" and not (args.date_from and args.date_to):
        raise SystemExit("Для режима API укажите --from и --to (YYYY-MM-DD) или --preset")
    start = _parse_date(args.date_from) if args.date_from else datetime.now(timezone.utc)
    end = _parse_date(args.date_to) if args.date_to else datetime.now(timezone.utc)
    # конец периода — конец суток
    end = datetime.combine(end.date(), time.max, tzinfo=timezone.utc)
    return ReportPeriod(start=start, end=end)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omnicomm_report",
        description="Анализ автопарка Omnicomm → клиентский отчёт .pptx",
    )
    p.add_argument("--source", choices=["excel", "csv", "api"], default="excel")
    p.add_argument("--input", help="путь к .xlsx/.csv (режим Б)")
    p.add_argument("--client", default="Клиент", help="название клиента для титула")
    p.add_argument("--from", dest="date_from", help="начало периода YYYY-MM-DD (режим А)")
    p.add_argument("--to", dest="date_to", help="конец периода YYYY-MM-DD (режим А)")
    p.add_argument("--preset", choices=["last-day", "last-week", "last-month"],
                   help="готовый период для cron (перекрывает --from/--to)")
    p.add_argument("--email", help="отправить готовые файлы на e-mail (SMTP из ENV)")
    p.add_argument("--alert-email", dest="alert_email",
                   help="отправить авто-сигналы (перерасход/простой) на e-mail")
    p.add_argument("--demo", action="store_true", help="демо-контур Omnicomm (http)")
    p.add_argument("--vehicles", help="список ID/UUID ТС через запятую (режим А)")
    p.add_argument("--with-track", action="store_true", dest="with_track",
                   help="запросить GPS-трек → карта точек погрузки (режим А, дольше)")
    p.add_argument("--outdir", default="output", help="каталог результатов")
    p.add_argument("--fuel-price", type=float, default=DEFAULT_FUEL_PRICE_KZT,
                   dest="fuel_price",
                   help=f"цена топлива ₸/л для денежной оценки (0 = без денег; "
                        f"по умолчанию {DEFAULT_FUEL_PRICE_KZT:.0f})")
    p.add_argument("--time-fund", type=float, default=0.0, dest="time_fund",
                   help="нормативный фонд времени, ч/сутки на ТС — для "
                        "коэффициента использования (0 = только календарный)")
    p.add_argument("--volume-m3", type=float, default=0.0, dest="volume_m3",
                   help="вывезено за период, м³ (данные полигона) — "
                        "топливная себестоимость ₸/м³ (ТКО)")
    p.add_argument("--rental-act", action="store_true", dest="rental_act",
                   help="выгрузить акт наработки .xlsx по ТС со ставкой "
                        "аренды (поле «Аренда ₸/мч» в паспорте)")
    p.add_argument("--no-history", action="store_true",
                   help="не сохранять/не использовать снапшоты для трендов")
    p.add_argument("--html", action="store_true", help="дополнительно собрать HTML-отчёт")
    p.add_argument("--pdf", action="store_true", help="дополнительно экспортировать PDF")
    p.add_argument("--xlsx", action="store_true", help="дополнительно выгрузить очищенный Excel")
    return p


def run(args: argparse.Namespace) -> int:
    load_env_file()   # .env в окружение (APP_CRYPTO_KEY для расшифровки кредов)
    period = _build_period(args)

    # 1. Загрузка → единая модель
    if args.source in ("excel", "csv"):
        if not args.input or not os.path.exists(args.input):
            raise SystemExit(f"Укажите существующий --input для режима {args.source}")
        log.info("Загрузка %s: %s", args.source.upper(), args.input)
        vehicles = data_loader.load(args.source, path=args.input)
    else:
        settings = Settings.from_env(demo=args.demo)
        from .api_client import OmnicommClient

        client = OmnicommClient(settings)
        client.login()
        ids = [v.strip() for v in args.vehicles.split(",")] if args.vehicles else None
        log.info("Загрузка из Omnicomm API за %s", period.human())
        vehicles = data_loader.load_from_api(client, period, ids,
                                             with_track=args.with_track)

    if not vehicles:
        raise SystemExit("Нет данных по ТС — отчёт не сформирован")

    # 2. Валидация / аномалии
    vehicles = validator.validate(vehicles)

    # 3. Аналитика (+ цена топлива в ₸, + тренды из истории прошлых прогонов)
    previous = None
    if not args.no_history:
        previous = history.load_previous(args.client, period)
    # Нормы расхода клиента (enter-once): подтягиваем сохранённые → перерасход/экономия.
    client_norms = norms.load_norms(args.client)
    if client_norms:
        log.info("Нормы расхода: загружено %d ТС", len(client_norms))
    # Календарь цены ГСМ: если задан — берём средневзвешенную по дням цену периода.
    from . import price_history
    price_eff, blended = price_history.price_for_period(
        args.fuel_price, period.start, period.end)
    if blended:
        log.info("Календарь цен ГСМ: средняя %.0f ₸/л за период", price_eff)
    report = analytics.analyze(
        vehicles, period, args.client, source=args.source,
        fuel_price_kzt=price_eff, previous_kpi=previous,
        norms=client_norms or None,
        time_fund_hours_per_day=args.time_fund,
        haul_volume_m3=args.volume_m3,
    )
    report.generated_at = datetime.now(timezone.utc)
    if not args.no_history:
        history.save_snapshot(report)
        # Счётчик подтверждённой экономии: no-op без замороженного baseline
        # (заморозка: python -m omnicomm_report.savings freeze ...).
        from . import savings
        if savings.apply_to_report(report):
            log.info("Счётчик экономии: %+.0f ₸ за период, накоплено %+.0f ₸",
                     report.savings["period"]["saved_kzt"],
                     report.savings["cumulative_kzt"])
    if report.alerts:
        log.info("Авто-сигналов: %d", len(report.alerts))
    if args.alert_email and report.alerts:
        from . import alerts as alerts_mod
        alerts_mod.send_alerts(report, args.alert_email)

    # 4. Графики
    os.makedirs(args.outdir, exist_ok=True)
    produced: list[str] = []
    with tempfile.TemporaryDirectory() as chart_dir:
        chart_paths = charts.build_charts(report, chart_dir)

        # 5. Отчёт .pptx
        stamp = report.generated_at.strftime("%Y_%m_%d")
        pptx_path = os.path.join(args.outdir, f"client_fleet_report_{stamp}.pptx")
        report_builder.build_pptx(report, chart_paths, pptx_path)
        produced.append(pptx_path)
        log.info("Готов отчёт: %s", pptx_path)

        if args.html:
            html_path = os.path.join(args.outdir, f"client_fleet_report_{stamp}.html")
            report_builder.build_html(report, chart_paths, html_path)
            produced.append(html_path)
            log.info("Готов HTML: %s", html_path)

        if args.xlsx:
            xlsx_path = os.path.join(args.outdir, f"client_fleet_report_{stamp}.xlsx")
            report_builder.export_xlsx(report, xlsx_path)
            produced.append(xlsx_path)
            log.info("Выгружен Excel: %s", xlsx_path)

        if args.rental_act:
            from . import rental
            act = rental.build_act(report, client_norms or {})
            if act:
                act_path = os.path.join(args.outdir, f"rental_act_{stamp}.xlsx")
                rental.export_act_xlsx(act, act_path)
                produced.append(act_path)
            else:
                log.warning("Акт аренды не сформирован: ни у одного ТС нет "
                            "ставки «Аренда ₸/мч» в паспорте")

        if args.pdf:
            pdf_path = os.path.join(args.outdir, f"client_fleet_report_{stamp}.pdf")
            res = report_builder.export_pdf(pptx_path, pdf_path)
            if res:
                produced.append(res)
                log.info("Экспортирован PDF: %s", res)
            else:
                log.warning("PDF не сформирован (нет конвертера) — см. docs/api.md")

    # 6. Опциональная отправка по e-mail (для scheduled-рассылки).
    if args.email:
        from . import mailer
        subject = f"Отчёт по автопарку «{args.client}» — {period.human()}"
        body = (f"Автоматический отчёт по автопарку за период {period.human()}.\n"
                f"Файлы во вложении. Сформировано Omnicomm Fleet Report.")
        mailer.send_report(args.email, subject, body, produced)

    return 0


# --- Подкоманда `holding`: прогон по холдингу (дашборды на каждое ДЗО) --------

_LEVEL_MAP = {
    "holding": OrgLevel.HOLDING, "dzo": OrgLevel.DZO,
    "sub_dzo": OrgLevel.SUB_DZO, "contractor": OrgLevel.CONTRACTOR,
}


def _parse_levels(s: str | None):
    """`"dzo,holding"` → кортеж OrgLevel; пусто/None → None (все уровни с ТС)."""
    if not s:
        return None
    out = [_LEVEL_MAP[t.strip().lower()] for t in s.split(",")
           if t.strip().lower() in _LEVEL_MAP]
    return tuple(out) or None


def _holding_period(args: argparse.Namespace) -> ReportPeriod:
    if args.preset:
        return _preset_period(args.preset)
    if not (args.date_from and args.date_to):
        raise SystemExit("Holding: укажите --from и --to (YYYY-MM-DD) или --preset")
    return ReportPeriod(
        start=_parse_date(args.date_from),
        end=datetime.combine(_parse_date(args.date_to).date(), time.max, tzinfo=timezone.utc),
    )


def build_holding_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omnicomm_report holding",
        description="Holding-прогон: один аккаунт Omnicomm → дашборды на каждое ДЗО",
    )
    p.add_argument("--demo", action="store_true", help="демо-контур Omnicomm (http)")
    p.add_argument("--from", dest="date_from", help="начало периода YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", help="конец периода YYYY-MM-DD")
    p.add_argument("--preset", choices=["last-day", "last-week", "last-month"],
                   help="готовый период для cron (перекрывает --from/--to)")
    p.add_argument("--outdir", default="output/holding", help="каталог дашбордов по ДЗО")
    p.add_argument("--fuel-price", type=float, default=DEFAULT_FUEL_PRICE_KZT,
                   dest="fuel_price", help="цена топлива ₸/л (0 = без денег)")
    p.add_argument("--registry", help="путь сохранить реестр организаций (org_registry.json)")
    p.add_argument("--contractors", help="org_id подрядчиков через запятую (пометить тегом)")
    p.add_argument("--levels", help="уровни рендера: holding,dzo,sub_dzo,contractor "
                                    "(через запятую; пусто = все узлы с ТС)")
    p.add_argument("--pptx", action="store_true", help="рендерить .pptx (по умолч. только HTML)")
    p.add_argument("--no-html", action="store_true", dest="no_html",
                   help="не рендерить HTML")
    p.add_argument("--data-only", action="store_true", dest="data_only",
                   help="только реестр+ингест+роллапы, без отрисовки дашбордов")
    return p


def run_holding(args: argparse.Namespace) -> int:
    load_env_file()
    period = _holding_period(args)
    settings = Settings.from_env(demo=args.demo)
    from .api_client import OmnicommClient

    client = OmnicommClient(settings)
    client.login()
    contractors = ([c.strip() for c in args.contractors.split(",") if c.strip()]
                   if args.contractors else None)
    log.info("Holding-прогон за %s", period.human())
    result = holding.run_from_client(
        client, period,
        fuel_price_kzt=args.fuel_price, out_dir=args.outdir,
        contractor_org_ids=contractors, registry_path=args.registry,
        levels=_parse_levels(args.levels), render=not args.data_only,
        html=not args.no_html, pptx=args.pptx,
    )
    log.info("Организаций в реестре: %d; ТС привязано: %d; без узла в дереве: %d",
             len(result.registry.tree), result.assigned, len(result.unassigned))
    if result.unassigned:
        log.warning("ТС вне дерева аккаунта (%d): %s%s", len(result.unassigned),
                    ", ".join(result.unassigned[:10]),
                    " …" if len(result.unassigned) > 10 else "")
    for oid, paths in result.rendered.items():
        node = result.registry.tree.get(oid)
        log.info("Дашборд «%s»: %s", node.name if node else oid,
                 ", ".join(paths.values()))
    if not args.data_only and not result.rendered:
        log.warning("Дашборды не сформированы — нет ТС в выбранных уровнях/scope")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "holding":
        return run_holding(build_holding_parser().parse_args(argv[1:]))
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
