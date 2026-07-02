"""Реестр справочных данных по моделям техники — «как выглядит + что это».

Зеркалит паттерн `vehicle_types.py`: committed seed `DEFAULT_MODELS` + матчер
`lookup(name)` по подстрокам имени ТС + runtime-оверрайды из
`data/vehicle_models.json` (gitignored). Питает блок «референс модели» в карточке.

Картинки: `image_slug` → локальный файл `web/public/models/<slug>.jpg` (same-origin,
надёжно под CSP/гео-блоком Hoster); `image_url` — внешний прямой URL (Wikimedia),
браузер грузит сам. Нет ни того, ни другого → фронт рисует иконку по типу.

Характеристики (`specs`) приблизительны — зависят от модификации/года (данные
собраны веб-поиском: LECTURA Specs, сайты производителей, отраслевые каталоги).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

MODELS_PATH = os.path.join("data", "vehicle_models.json")


@dataclass(frozen=True)
class ModelRef:
    canonical: str
    type_key: str
    summary: str
    specs: str
    match_keywords: tuple[str, ...] = field(default_factory=tuple)
    brand: Optional[str] = None
    image_slug: Optional[str] = None   # локальный файл web/public/models/<slug>.jpg
    image_url: Optional[str] = None    # внешний прямой URL (Wikimedia)
    wiki_url: Optional[str] = None


# Seed-реестр. ПОРЯДОК ВАЖЕН: специфичные (каротаж/УРБ) — до общих марок (урал/маз).
DEFAULT_MODELS: list[ModelRef] = [
    ModelRef("Atlas Copco V900", "compressor",
             "Передвижной дизельный винтовой компрессор высокого давления для бурения.",
             "≈25 м³/мин, 25 бар; двигатель Cummins ~264 кВт; буксируемый.",
             ("atlas copco v900", "v900", "v 900"), brand="Atlas Copco",
             wiki_url="https://www.atlascopco.com/en-us/construction-equipment/products/mobile-air-compressors"),
    ModelRef("Atlas Copco XRVS 336", "compressor",
             "Буксируемый дизельный винтовой компрессор высокого давления для бурения.",
             "≈20 м³/мин, 25 бар; двигатель Caterpillar C9 ~224 кВт; бак ~538 л; ~6.6 т.",
             ("atlas copco xrvs", "xrvs 336", "xrvs336", "xrvs"), brand="Atlas Copco",
             wiki_url="https://www.lectura-specs.com/en/model/structural-and-civil-engineering-equipment/air-compressors-portable-air-compressors-diesel-electric-gasoline-atlas-copco/xrvs-336-cd-234"),
    ModelRef("Atlas Copco XAXS 600", "compressor",
             "Передвижной дизельный винтовой компрессор высокого давления для скважинного бурения.",
             "≈17 м³/мин, 17 бар; двигатель Cummins QSB6.7 ~194 кВт; ~2.8 т.",
             ("atlas copco xaxs", "xaxs 600", "xaxs600", "xaxs"), brand="Atlas Copco"),
    ModelRef("Буровая установка ЗИФ (ЗИФ-650М/1200)", "drill_rig",
             "Стационарная колонковая буровая для геологоразведки на твёрдые полезные ископаемые.",
             "ЗИФ-650М: глубина ~500–800 м, привод ~30 кВт. ЗИФ-1200: до ~1200–2000 м, ~55 кВт.",
             ("зиф", "буровая установка зиф", "зиф-650", "зиф 650", "зиф-1200"), brand="ЗИФ",
             wiki_url="http://ageomash.com/product/burovoj-stanok-zif-650m/"),
    ModelRef("УРБ-2А2 (буровая на шасси МАЗ)", "drill_rig_mobile",
             "Самоходная установка разведочного бурения на шасси грузовика — скважины на воду/геофизику.",
             "Глубина до ~350 м; диаметр 300→118 мм; мачта ~6000 кгс; вращательное бурение.",
             ("урб", "урб-2а2", "урб 2а2", "установка разведочного бурения"), brand="МАЗ",
             wiki_url="https://www.mozbt.com/burovye-ustanovki/modelnyj-ryad-urb/burovaya-ustanovka-urb-2a-2"),
    ModelRef("Урал — каротажная станция", "logging_station",
             "Геофизическая каротажная станция (ЛКС/ПКС) на шасси Урал для операций в скважинах.",
             "Спецкузов на Урал 6×6: лаборатория + каротажная лебёдка + регистрирующая аппаратура.",
             ("каротаж", "каротажная станция", "геофиз", "пкс"), brand="Урал",
             wiki_url="https://tehnogeo.ru/products/karotazhnaya-stanciya-na-baze-ural"),
    ModelRef("Volvo FMX 420", "dump_truck",
             "Тяжёлый строительный самосвал Volvo для карьеров и бездорожья.",
             "Двигатель D13K 13 л, 420 л.с. (~309 кВт); 6×4/8×4; полезная ~17–19 т.",
             ("volvo fmx", "fmx420", "fmx 420", "вольво fmx"), brand="Volvo",
             image_slug="volvo-fmx",
             image_url="https://upload.wikimedia.org/wikipedia/commons/3/32/Volvo_FMX_10x4_dump_truck_2014._Spielvogel_1.JPG",
             wiki_url="https://en.wikipedia.org/wiki/Volvo_FMX"),
    ModelRef("IVECO Astra HD9", "dump_truck",
             "Итальянский тяжёлый внедорожный самосвал для карьеров и горных работ.",
             "FPT Cursor 13 л, ~380–570 л.с.; 2/3/4 оси, до ~65 т; ZF Ecosplit 16.",
             ("iveco astra", "astra hd", "astra"), brand="IVECO",
             wiki_url="https://www.astra-trucks.com/en/products/hd9-rigid/"),
    ModelRef("SHACMAN X3000 / F3000", "dump_truck",
             "Китайский тяжёлый самосвал (Shaanxi) для карьерных и строительных перевозок.",
             "Weichai/Cummins ~336–460 л.с.; 6×4/8×4; загрузка до ~40–50 т; МКПП.",
             ("shacman", "шакман", "x3000", "f3000"), brand="SHACMAN",
             wiki_url="https://www.shacman-truck.com/products/x3000-8x4-dump-truck.html"),
    ModelRef("МАЗ (самосвал МАЗ-5516)", "dump_truck",
             "Белорусский самосвал Минского автозавода для строительных и карьерных перевозок.",
             "МАЗ-5516: 6×4, ~19–20 т, кузов ~11–16 м³, двигатель ЯМЗ ~330–400 л.с.",
             ("маз-5516", "5516", "маз самосвал"), brand="МАЗ",
             image_slug="maz-5516",
             image_url="https://upload.wikimedia.org/wikipedia/commons/9/97/MAZ-5516_dump_truck_in_Belarus_11.jpg",
             wiki_url="https://commons.wikimedia.org/wiki/Category:MAZ_trucks_by_number"),
    ModelRef("КрАЗ (самосвал)", "offroad_special",
             "Украинский тяжёлый полноприводный самосвал для карьеров и бездорожья.",
             "Напр. КрАЗ-65055: 6×4, ~16–18 т, кузов ~10–12 м³, ЯМЗ ~330 л.с.; версии 6×6.",
             ("краз", "kraz", "краз-6510", "65055"), brand="КрАЗ",
             image_slug="kraz",
             image_url="https://upload.wikimedia.org/wikipedia/commons/3/38/KrAZ-256_dump_truck_in_Kazakhstan.JPG",
             wiki_url="https://en.wikipedia.org/wiki/KrAZ"),
    ModelRef("DEVELON SD300N", "loader",
             "Фронтальный колёсный погрузчик Develon/Doosan для погрузки сыпучих.",
             "Масса ~17 т, ковш ~3.0 м³, двигатель ~162 кВт (220 л.с.), разгрузка ~4.15 м.",
             ("develon sd300", "sd300n", "sd300", "sd 300", "doosan sd300", "девелон"), brand="DEVELON",
             wiki_url="https://www.lectura-specs.com/en/model/construction-machinery/wheel-loaders-doosan/sd300n-11752896"),
    ModelRef("ГАЗ-3309 АГП (автогидроподъёмник)", "agp",
             "Автовышка/автогидроподъёмник на шасси ГАЗ-3309 для высотных работ.",
             "Шасси ГАЗ-3309, ЯМЗ-534; высота подъёма ~18–22 м, вылет ~10–15 м, люлька ~300 кг.",
             ("газ 3309", "газ-3309", "3309", "агп", "автогидроподъемник", "автовышка"), brand="ГАЗ",
             wiki_url="https://commons.wikimedia.org/wiki/Category:GAZ-3307"),
    ModelRef("УРАЛ-4320", "offroad_special",
             "Полноприводный вездеходный грузовик 6×6 (Миасс) для бездорожья.",
             "6×6, грузоподъёмность ~4.5–7 т, дизель ЯМЗ ~230–312 л.с.",
             ("урал-4320", "урал 4320", "4320", "урал"), brand="Урал",
             image_slug="ural-4320",
             image_url="https://upload.wikimedia.org/wikipedia/commons/f/fa/URAL-4320_%284713570237%29.jpg",
             wiki_url="https://en.wikipedia.org/wiki/Ural-4320"),
    ModelRef("Toyota Land Cruiser Prado", "car",
             "Полноразмерный рамный внедорожник Toyota для служебных/разъездных поездок.",
             "Рамный SUV 4WD; бензин ~2.7–4.0 л и дизель ~2.8–3.0 л, ~150–280 л.с.",
             ("land cruiser prado", "prado", "прадо", "тойота прадо", "toyota prado"), brand="Toyota",
             image_slug="prado",
             image_url="https://upload.wikimedia.org/wikipedia/commons/a/a6/2013_Toyota_Land_Cruiser-Prado_01.jpg",
             wiki_url="https://en.wikipedia.org/wiki/Toyota_Land_Cruiser_Prado"),
]


def _as_dict(m: ModelRef) -> dict:
    return {
        "canonical": m.canonical, "model": m.canonical, "brand": m.brand,
        "type_hint": m.type_key, "summary": m.summary, "specs": m.specs,
        "image_slug": m.image_slug, "image_url": m.image_url, "wiki_url": m.wiki_url,
    }


def _load_overrides() -> list[ModelRef]:
    if not os.path.exists(MODELS_PATH):
        return []
    try:
        with open(MODELS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for d in data or []:
        out.append(ModelRef(
            d.get("canonical", "?"), d.get("type_key", "other"),
            d.get("summary", ""), d.get("specs", ""),
            tuple(d.get("match_keywords", [])), d.get("brand"),
            d.get("image_slug"), d.get("image_url"), d.get("wiki_url")))
    return out


def all_models() -> list[ModelRef]:
    """Оверрайды из JSON ПЕРЕД дефолтами (пользователь уточняет раньше seed)."""
    return _load_overrides() + DEFAULT_MODELS


def lookup(name: Optional[str]) -> Optional[dict]:
    """Референс модели по имени ТС (первое совпадение подстроки). Нет → None."""
    n = (name or "").lower()
    if not n:
        return None
    for m in all_models():
        for kw in m.match_keywords:
            if kw and kw in n:
                return _as_dict(m)
    return None
