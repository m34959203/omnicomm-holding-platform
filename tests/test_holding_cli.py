"""Тесты CLI-подкоманды `holding` (без сети)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import __main__ as cli  # noqa: E402
from omnicomm_report.org import OrgLevel  # noqa: E402


def test_parse_levels():
    assert cli._parse_levels(None) is None
    assert cli._parse_levels("") is None
    assert cli._parse_levels("dzo") == (OrgLevel.DZO,)
    assert cli._parse_levels("holding,dzo") == (OrgLevel.HOLDING, OrgLevel.DZO)
    assert cli._parse_levels(" DZO , Contractor ") == (OrgLevel.DZO, OrgLevel.CONTRACTOR)
    assert cli._parse_levels("garbage") is None        # неизвестное → None


def test_holding_parser_defaults():
    args = cli.build_holding_parser().parse_args(["--demo", "--from", "2026-05-01",
                                                  "--to", "2026-05-31"])
    assert args.demo is True
    assert args.outdir == "output/holding"
    assert args.date_from == "2026-05-01" and args.date_to == "2026-05-31"
    assert args.pptx is False and args.no_html is False and args.data_only is False


def test_holding_period_from_dates():
    args = cli.build_holding_parser().parse_args(["--from", "2026-05-01", "--to", "2026-05-31"])
    period = cli._holding_period(args)
    assert period.start.strftime("%Y-%m-%d") == "2026-05-01"
    assert period.end.strftime("%Y-%m-%d") == "2026-05-31"
    assert period.end.hour == 23                        # конец суток


def test_holding_period_requires_range():
    args = cli.build_holding_parser().parse_args(["--demo"])
    try:
        cli._holding_period(args)
        assert False, "ожидалась ошибка про --from/--to"
    except SystemExit:
        pass


def test_main_routes_to_holding(monkeypatch):
    seen = {}

    def fake_holding(a):
        seen["holding"] = a
        return 0

    def fake_default(a):
        seen["default"] = a
        return 0

    monkeypatch.setattr(cli, "run_holding", fake_holding)
    monkeypatch.setattr(cli, "run", fake_default)

    assert cli.main(["holding", "--demo", "--preset", "last-day"]) == 0
    assert "holding" in seen and "default" not in seen

    seen.clear()
    assert cli.main(["--source", "excel", "--input", "x.xlsx"]) == 0
    assert "default" in seen and "holding" not in seen
