"""Параметры, секреты и константы лимитов (ТЗ §4, §12).

Секреты берутся ТОЛЬКО из переменных окружения (ТЗ §4.6) — в коде
ни логина, ни пароля, ни токенов. Токены никогда не логируются.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


def load_env_file(path: str = ".env") -> None:
    """Подтянуть .env в окружение БЕЗ зависимостей (cron-команда его не сорсит).

    Существующие переменные окружения НЕ перетираются. Вызывать в точках входа
    (app.py, scheduler, __main__), чтобы APP_CRYPTO_KEY/SMTP/прочее были доступны
    процессам, запущенным голым `env … python`.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


# --- Деньги и нормы (валюта — тенге, ₸) ---------------------------------------

CURRENCY = "₸"                       # вся денежная оценка в отчёте — в тенге
# Дефолт цены топлива (₸/л ДТ, РК-ориентир). Переопределяется: ENV FUEL_PRICE_KZT,
# флагом CLI --fuel-price, полем клиента в платформе. Не хардкод — это лишь default.
DEFAULT_FUEL_PRICE_KZT = float(os.getenv("FUEL_PRICE_KZT", "320") or 320)
# Консервативная достижимая доля сокращения простоя (бенчмарк: 40-60% за 30 дней;
# берём осторожные 30% для оценки потенциальной экономии «снизу»).
IDLE_REDUCIBLE_SHARE = 0.30

# Эвристика типа ТС: если на моточас приходится мало пробега — это стационарная
# спецтехника (экскаватор/харвестер/генератор), для неё корректна метрика
# л/моточас, а не л/100км. Порог — средняя скорость по моточасам, км/ч.
STATIONARY_KM_PER_HOUR = 5.0

# Нормы расхода по ключу (подстрока имени/группы ТС, нижний регистр). Пусто —
# нормы не заданы, вывод о перерасходе не делается (бизнес-инвариант).
FUEL_NORMS_PER_100KM: dict[str, float] = {}
FUEL_NORMS_PER_MOTORHOUR: dict[str, float] = {}

# Цель по доле холостого хода (Geotab benchmark) — для подсветки и экономии.
IDLE_TARGET_SHARE = 0.05
# Минимальная наработка ТС для участия в рейтингах холостого хода, мч:
# доля «93%» при 0.4 мч — шум данных, а не лидер простоя.
MIN_HOURS_FOR_IDLE_RANK = 5.0

# --- Коэффициенты к нормам расхода (методики Минтранса) -----------------------
# Множители к ожидаемому расходу. Применяются к норме при расчёте перерасхода.
NORM_COEFFICIENTS = {
    "winter": 1.10,      # зимняя надбавка (РК ~6-12%, берём 10%)
    "dump": 1.15,        # работа на свалке/в карьере (+10-20%)
    "city": 1.10,        # частые остановки в городе (+10%)
    "wear": 1.05,        # износ ТС > 5 лет (+5%)
}

# --- Авто-алерты руководителю ------------------------------------------------
ALERT_OVERRUN_COST_KZT = 100_000     # перерасход по ТС выше → алерт, ₸
ALERT_IDLE_SHARE = 0.50              # доля холостого хода выше → алерт
ALERT_NODATA_SHARE = 0.10           # доля «тёмных» ТС выше → алерт по парку
ALERT_SPEEDING_SHARE = 0.10         # доля пробега с превышением выше → алерт по ТС

# Бенчмарк «среднее по паркам» показываем только при достаточном числе ДРУГИХ
# клиентов — иначе «среднее» по одному парку вводит в заблуждение.
MIN_BENCHMARK_PEERS = 2

# Сценарии «что если» — на сколько сократить простой (доли).
WHATIF_IDLE_CUTS = (0.10, 0.20, 0.30)

# --- Экономический эффект (economics.py, docs/STRATEGY.md §4.1) ----------------
# 1 ч холостого хода ≈ N км эквивалентного износа двигателя — конвенция
# severe-duty (Cummins ISX: 30/50/70 миль→км для severe/normal/light классов;
# для мусоровозов/спецтехники берём severe ≈ 30 км).
IDLE_WEAR_KM_PER_HOUR = 30.0
# Стоимость ТО на км для тяжёлой техники, ₸/км — отраслевая ОЦЕНКА (ATRI 2025:
# R&M ≈ $0.123/км; для КЗ консервативно ниже). 0 = корзина «Износ и ТО» не
# считается. Переопределяется per-client при появлении фактических данных ТО.
MAINT_COST_PER_KM_KZT = float(os.getenv("MAINT_COST_PER_KM_KZT", "40") or 40)
# Консервативный эффект программ эко-вождения на топливо в движении
# (исследования: устойчивые 5-10%; берём нижнюю границу). Только «потенциал».
ECO_DRIVING_SAVE_SHARE = 0.05

# Себестоимость вывоза: контейнеров на точку погрузки (для оценки ₸/контейнер).
CONTAINERS_PER_POINT = 1.0          # уточняется заказчиком

# Порог правдоподобия макс. скорости, км/ч: выше — сбой GPS (напр. 655 км/ч),
# не учитываем в KPI и помечаем «требует проверки». Глобальный предел.
MAX_PLAUSIBLE_SPEED_KMH = 200.0

# Класс-зависимый предел макс. скорости (Cowork-ревью: мусоровоз ≠ 168 км/ч).
# Применяется после классификации типа; выше — сбой GPS → отсев из KPI.
MAX_PLAUSIBLE_SPEED_BY_TYPE = {
    "refuse_truck": 110.0, "vacuum_sweeper": 110.0, "dump_truck": 110.0,
    "truck": 130.0, "bus": 110.0, "car": 180.0,
    "excavator": 40.0, "crane": 50.0, "loader": 50.0, "tractor": 60.0,
}


# --- Модуль «Работа на погрузке» (спецтехника/мусоровозы) ---------------------

# Единицы Omnicomm consolidatedReport (сверено с developers.omnicomm.ru/api.yaml):
# топливо (fuelConsumption, fuelConsumptionWOMovement, univInputOnConsumption,
# refuelling, draining) — в ДЕЦИЛИТРАХ → литры = значение / 10.
DECILITRES_TO_LITRES = 10.0

# GPS-кластеризация точек погрузки (track): стоянка = speed 0, достаточно спутников,
# в радиусе и не короче порога.
TRACK_STOP_RADIUS_M = 50          # радиус кластера стоянок, м
TRACK_MIN_STOP_SEC = 180          # минимальная длительность стоянки-погрузки, с
TRACK_MIN_SATELLITES = 4          # ниже — координата недостоверна, точку отбрасываем

# Бессенсорная оценка погрузки по GPS-остановкам маршрута (нет датчика надстройки
# и оборотов). Откалибровано на боевом прогоне Горкомтранс (2026-06-07, 458 стоянок
# с 20 мусоровозов, треки 02–06.06, детектором cluster_track_points): распределение
# бимодальное — короткие 0–1 мин (~27%) и рабочий бугор 8–12 мин (~13%), провал на
# 12–15 мин, затем «парковочный» хвост >60 мин (~22%, база/ночь). Окно обслуживания
# [MIN..MAX] отсекает светофоры снизу и стоянки/простой сверху.
LOADING_STOP_MIN_SEC = 60         # мин. остановка-обслуживание, с (короче — светофор/манёвр)
LOADING_STOP_MAX_SEC = 900        # макс. остановка-обслуживание, с (15 мин; дольше — стоянка/простой)
# Гоча калибровки: на стоянке GPS даёт джиттер скорости 0.4–1 км/ч; строгое speed>0
# рвало стоянку на куски (детектор находил ~3 стоянки/день вместо ~20). Порог «стоит»
# вынесен в cluster_track_points(speed_eps=1.5). Спутники на стоянке часто 0 →
# для оценки погрузки кластеризуем с min_satellites=0 (см. data_loader).

# Удельный расход гидравлики выше — пометить «требует проверки» (выброс).
LOADING_FUEL_PER_MH_REVIEW = 120.0

# Правило заказчика по режимам работы по оборотам: <1000 об/мин — холостой ход,
# >1000 — техника в работе. Omnicomm отдаёт ВРЕМЯ в трёх полосах (idlingRPM/
# normalRPM/workedUnderLoadRPM), а не сырые обороты, поэтому «1000» — это порог
# полосы «под нагрузкой» (настраивается на терминале), а не извлекаемое значение.
# Дедукция: обороты под нагрузкой + GPS неподвижна = работает гидравлика (погрузка).
RPM_WORK_THRESHOLD = 1000  # ориентир, об/мин (документирует бизнес-правило)


# --- Эталонная конфигурация клиента (ТЗ §4.5) ---------------------------------

MAX_IDS_PER_REQUEST = 15        # пачка ID в одном запросе
# Нарезка периода ПО ВРЕМЕНИ на маленькие окна при заборе (чанкинг): длинный
# период (неделя/месяц) разбивается на окна по REPORT_WINDOW_DAYS суток, каждое —
# отдельный быстрый запрос. Без этого 30-дневный запрос на медленном контуре
# КАП виснет, а прогресс застывает (двигался только по завершении целого батча).
REPORT_WINDOW_DAYS = 3
# Инкрементальный синк (раздельный довоз свежих суток + пересборка из накопленного):
INGEST_WINDOW_DAYS = 2          # сколько последних суток довозим за раз (свежие данные)
VIEW_WINDOW_DAYS = 30           # за какое окно пересобираем снимок из хранилища

# --- Локальный архив GPS-треков за год (бэкфилл + хранение) -------------------
# Требование: система держит у себя ВЕСЬ год телеметрии (включая треки), чтения —
# мгновенные из локального хранилища, в Omnicomm при открытии карточки НЕ ходим.
# Бэкфилл устроен БЕРЕЖНО к серверу Omnicomm (см. api/track_backfill.py):
TRACK_BACKFILL_DAYS = int(os.getenv("TRACK_BACKFILL_DAYS", "365") or 365)
# Потолок забора треков — ЩАДЯЩИЙ к копии Omnicomm. Урок 24.06: устойчивые 120/мин
# + повторный тяжёлый забор дерева ТС из каждой задачи деградировали копию (дерево
# ушло в таймаут). Безопасно для ЭТОЙ копии = ~60/мин (не «по докам 180», а по факту).
TRACK_BACKFILL_RATE_PER_MIN = int(os.getenv("TRACK_BACKFILL_RATE_PER_MIN", "60") or 60)
# Пул воркеров: перекрывают латентность, чтобы достигать потолка частоты. Меньше потоков
# = меньше одновременных соединений к копии. Лимитер всё равно режет суммарную частоту.
TRACK_BACKFILL_WORKERS = int(os.getenv("TRACK_BACKFILL_WORKERS", "4") or 4)
# Дерево ТS (~2000 ТС) — тяжёлый эндпоинт: длинный таймаут + больше попыток с backoff.
TREE_TIMEOUT = int(os.getenv("TREE_TIMEOUT", "120") or 120)
TREE_MAX_RETRIES = int(os.getenv("TREE_MAX_RETRIES", "4") or 4)
# Кэш дерева/списка ТС на процесс (один забор на TTL, single-flight) — чтобы 24 задачи
# бэкфилла и пул воркеров НЕ дёргали тяжёлое дерево по многу раз (причина деградации 24.06).
FLEET_CACHE_TTL = int(os.getenv("FLEET_CACHE_TTL", "3600") or 3600)

# Адаптивный темп бэкфилла треков (AIMD по здоровью копии): ускоряемся когда сервер
# отвечает быстро и чисто, тормозим при росте латентности/ошибках. Всё в [min, max];
# max ≤ аккаунт-лимита с запасом живому синку. Старт консервативный.
TRACK_ADAPTIVE = os.getenv("TRACK_ADAPTIVE", "1") not in ("0", "false", "False", "")
TRACK_RATE_MIN = float(os.getenv("TRACK_RATE_MIN", "20") or 20)
TRACK_RATE_MAX = float(os.getenv("TRACK_RATE_MAX", "120") or 120)
TRACK_RATE_START = float(os.getenv("TRACK_RATE_START", "40") or 40)
TRACK_LATENCY_LOW = float(os.getenv("TRACK_LATENCY_LOW", "2.0") or 2.0)   # < — ускоряемся
TRACK_LATENCY_HIGH = float(os.getenv("TRACK_LATENCY_HIGH", "5.0") or 5.0)  # > — тормозим
TRACK_ADJUST_EVERY = int(os.getenv("TRACK_ADJUST_EVERY", "30") or 30)
TRACK_AI_STEP = float(os.getenv("TRACK_AI_STEP", "10") or 10)
# Кап на ОДИН запуск (cron гоняет короткими ночными слайсами; остаток добирается
# в следующий слайс — забор резюмируемый, уже сохранённые сутки пропускаются).
TRACK_BACKFILL_MAX_SECONDS = int(os.getenv("TRACK_BACKFILL_MAX_SECONDS", "1800") or 1800)
# Трек тянем ТОЛЬКО за сутки, где ТС реально ехал (по агрегату) — стоянки/простой
# не дёргаем: на порядок меньше запросов, чем 2000 ТС × 365 сут «в лоб».
TRACK_MIN_MILEAGE_KM = float(os.getenv("TRACK_MIN_MILEAGE_KM", "0.5") or 0.5)
# Упрощение полилинии (Дуглас-Пекер): ~0.00008° ≈ 9 м — маршрут читается, объём ↓ в разы.
TRACK_SIMPLIFY_EPSILON_DEG = float(os.getenv("TRACK_SIMPLIFY_EPSILON_DEG", "0.00008") or 0.00008)
# Ретеншн локального архива (скользящее окно года). 0 — не чистить.
TRACK_RETENTION_DAYS = int(os.getenv("TRACK_RETENTION_DAYS", "365") or 365)
SLEEP_TIME = 0.4                # сек, пауза между запросами (пер-клиентный пол)
# Документированный лимит Omnicomm — 180 запросов/мин на пользователя; держим
# консервативно ниже. Глобальный token-bucket на аккаунт (rate_limit.py) гарантирует
# суммарную частоту по ВСЕМ потокам синка ≤ этого значения (защита сервера Omnicomm).
MAX_REQUESTS_PER_MINUTE = 170
DEFAULT_TIMEOUT = 30            # сек, таймаут обычного HTTP-запроса
REPORT_TIMEOUT = 180            # сек, таймаут тяжёлых report-POST (много ТС × дни)
SKEW_SECONDS = 120              # запас по сроку токена — обновлять заранее

LOGIN_MAX_RETRIES = 5           # login — до 5 попыток
REFRESH_MAX_RETRIES = 3         # refresh — до 3 попыток
RETRY_STATUSES = {429, 500, 502, 503, 504}

# Лимиты Omnicomm (раздел «Ограничения») — для самоконтроля клиента
RATE_AUTHORIZED_PER_MIN = 180   # авторизованные вызовы / мин / пользователь
RATE_FAILED_AUTH_PER_MIN = 10   # неуспешные авторизации / мин / IP
RATE_UNAUTH_PER_MIN = 60        # неавторизованные вызовы / мин / IP


# --- Контуры (ТЗ §4.1) --------------------------------------------------------

# Демо-контур для отладки — адрес именно по HTTP (подтверждено документацией).
DEMO_BASE_URL = "http://online.omnicomm.ru"
DEMO_LOGIN = "rudemoru"
DEMO_PASSWORD = "rudemo123456"

# Боевой kz-контур — точный адрес подтверждается отделом техобслуживания Omnicomm.
DEFAULT_PROD_BASE_URL = "https://kz.omnicomm.online"


# --- Эндпоинты (ТЗ §4.3) ------------------------------------------------------

ENDPOINTS = {
    "login": "/auth/login?jwt=1",
    "refresh": "/auth/refresh",
    "vehicle_tree": "/ls/api/v2/tree/vehicle",
    "reports_catalog": "/ls/api/v1/reports/",
    "consolidated_report": "/ls/api/v1/reports/consolidatedReport",
    "events_v1": "/ls/api/v1/reports/events/",
    "events_v2": "/ls/api/v2/reports/events/",
    "activity_vehicles": "/ls/api/v1/activity/vehicles",
    "drivers": "/ls/api/v1/drivers",
    "track": "/ls/api/v1/reports/track/{id}",
    "geozones_report": "/ls/api/v1/reports/geozones",
    "geozones_list": "/api/service/geozones/geozones",
    "links": "/ls/api/v1/reports/links",
    "journal": "/ls/api/v1/click/log",            # отчёт «Журнал» — сырьё по узлам
    "journal_additional": "/ls/api/v1/click/log/additional",  # CAN/Modbus/польз.
}

# Геозоны-площадки: мин. длительность визита для журнала (минуты).
GEOZONE_MIN_VISIT_MIN = 3

# Ключевые отчёты (ТЗ §4.4) — id подтверждаются вызовом каталога на контуре.
REPORT_CONSOLIDATED_ID = 32     # consolidatedreport (FAS, FTC)
REPORT_FUEL_EVENTS_ID = 8       # fueleventsreport


# --- Право РК: КоАП превышение скорости (docs/knowledge-base/03) --------------
# ✅ СВЕРЕНО 2026-06-23 со ст. 592 КоАП РК (действующая редакция — Закон РК
# от 03.10.2024 № 131-VIII / adilet Z2400000131). Дословный текст подтверждён;
# части/ставки ниже совпадают. R-INV-8 снят: суммы можно показывать.
MRP_KZT = 4325                       # МРП на 2026
KOAP_VERIFIED = True                 # сверено на adilet (см. дату ниже)
KOAP_REVISION_DATE = "2024-10-03"    # ред. ст.592: Закон РК № 131-VIII
# ст. 592 КоАП РК (превышение скорости): (нижняя граница превышения км/ч, МРП, статья)
# Только штраф (предупреждения нет); превышение < 10 км/ч ненаказуемо.
KOAP_SPEEDING = [
    (60, 40, "ст.592 ч.3-1"),        # 60+ км/ч → 40 МРП
    (40, 20, "ст.592 ч.3"),          # 40–60   → 20 МРП
    (20, 10, "ст.592 ч.2"),          # 20–40   → 10 МРП
    (10, 5,  "ст.592 ч.1"),          # 10–20   → 5 МРП
]
# Пороги дисциплинарного отклонения СТ КАП (kb-09 §1): (нижняя граница км/ч, метка)
ST_KAP_THRESHOLDS = [(6, "грубое"), (3, "существенное"), (1, "незначительное")]

# Детекция превышений (R-INV-3): устойчивый сегмент + физфильтр выбросов.
SPEEDING_MIN_SEGMENT_POINTS = 3      # ≥N подряд правдоподобных точек = нарушение
SPEEDING_MIN_SATELLITES = 4          # валидная GPS-точка
SPEEDING_MAX_ACCEL_MS2 = 4.0         # |Δv/Δt| выше → GPS-выброс, точка отбрасывается


# --- AI-полировка рекомендаций через Claude (Anthropic) — ai_engine.py --------
# Claude ТОЛЬКО переформулирует посчитанные движком факты (статья/ставка/тип
# дороги/действие), НЕ источник права. Нет ключа/сети → fallback на
# детерминированный Recommendation.as_text(). Ключ — ANTHROPIC_API_KEY из ENV.
AI_RECOMMENDATIONS_ENABLED = True
AI_MODEL = "claude-opus-4-8"
AI_MAX_TOKENS = 700


# --- Sensor Health (docs/knowledge-base/10) -----------------------------------
# Терминальный «светофор» по давности данных (activity/vehicles → dateID).
TERMINAL_STALE_AFTER_MIN = 60        # данных нет > часа → STALE (🟡)
TERMINAL_OFFLINE_AFTER_HOURS = 24    # данных нет > суток → OFFLINE (🔴)

# Уровень 1.5 — ПИТАНИЕ (kb-10): напряжение бортсети (`/vehicles/{id}/state`) как
# gate «сбой ДУТ vs обесточенный терминал». Питание есть + блок данных пропал =
# сбой именно датчика; питание низкое/нет = причина в питании, не в сенсоре.
# Пороги покрывают 12В и 24В системы (по самому значению определяем тип сети).
VOLTAGE_DEAD = 6.0                   # < — практически обесточен
VOLTAGE_24V_SPLIT = 18.0             # > — это 24В-система
VOLTAGE_12V_LOW = 11.8               # 12В: ниже — просадка питания
VOLTAGE_24V_LOW = 23.5               # 24В: ниже — просадка питания
# Бюджет на пробу напряжения за синк (по одному /state на ТС, под rate-limit):
# проверяем только подозрительных (ТС с пропавшими блоками), не весь парк.
SENSOR_VOLTAGE_PROBE_MAX = 120


# --- Контроль ТО (R6) ---------------------------------------------------------
# Дефолт-интервалы ТО по КЛАССУ ТС (до согласования по модели с заказчиком):
# подвижная техника считается по пробегу, стационарная/спецтехника — по моточасам.
# Точные интервалы по модели заведутся справочником при онбординге (R6.2).
MAINT_INTERVAL_KM_MOBILE = float(os.getenv("MAINT_INTERVAL_KM_MOBILE", "15000") or 15000)
MAINT_INTERVAL_MH_STATIONARY = float(os.getenv("MAINT_INTERVAL_MH_STATIONARY", "250") or 250)
MAINT_REMIND_BEFORE_KM = float(os.getenv("MAINT_REMIND_BEFORE_KM", "1000") or 1000)
MAINT_REMIND_BEFORE_MH = float(os.getenv("MAINT_REMIND_BEFORE_MH", "25") or 25)


# --- Спец-лимит по типу груза (R4.4, ADR) -------------------------------------
# Для опасных грузов (ADR) внутренний стандарт снижает лимит на величину ниже.
# Привязка ТС→тип груза приходит отдельным справочником (согласует Данияр) —
# пока каркас: смещение применяется к ТС, помеченным как перевозящие опасный груз.
ADR_SPEED_REDUCTION_KMH = int(os.getenv("ADR_SPEED_REDUCTION_KMH", "30") or 30)


# --- Частота обновления данных (R2.4) -----------------------------------------
# Сколько раз в сутки cron тянет данные из Omnicomm. Админ-настройка (не польз.):
# меняется в ENV и в крон-расписании деплоя (см. docs/DEPLOY-holding.md).
REFRESH_TIMES_PER_DAY = int(os.getenv("REFRESH_TIMES_PER_DAY", "8") or 8)


@dataclass
class Settings:
    """Среда выполнения. Загружается из ENV: LOGIN, PASSWORD, SERVICE."""

    base_url: str = DEFAULT_PROD_BASE_URL
    login: str = ""
    password: str = ""
    service: str = ""           # имя сервиса/контура, если требуется

    @classmethod
    def from_env(cls, *, demo: bool = False) -> "Settings":
        if demo:
            return cls(
                base_url=DEMO_BASE_URL,
                login=os.getenv("LOGIN", DEMO_LOGIN),
                password=os.getenv("PASSWORD", DEMO_PASSWORD),
                service=os.getenv("SERVICE", ""),
            )
        return cls(
            base_url=os.getenv("OMNICOMM_BASE_URL", DEFAULT_PROD_BASE_URL),
            login=os.getenv("LOGIN", ""),
            password=os.getenv("PASSWORD", ""),
            service=os.getenv("SERVICE", ""),
        )


# --- Коды ошибок Omnicomm (полный официальный список, ТЗ §4.5) ----------------

class ErrorAction(str, Enum):
    """Что делает клиент при получении кода ошибки Omnicomm."""

    OK = "ok"                       # норма
    ABORT = "abort"                 # прервать запрос, не ретраить
    REAUTH = "reauth"               # выполнить login/refresh и повторить
    MARK_NO_DATA = "mark_no_data"   # пометить ТС «нет данных», НЕ прерывать отчёт
    RETRY = "retry"                 # ретрай, затем лог


# code -> (англ. имя, значение, действие клиента)
OMNICOMM_ERRORS: dict[int, tuple[str, str, ErrorAction]] = {
    0:  ("No errors",          "Ошибок нет",                                ErrorAction.OK),
    1:  ("Signing in failed",  "Неверный логин/пароль",                     ErrorAction.ABORT),
    2:  ("Authorization required", "Требуется авторизация",                 ErrorAction.REAUTH),
    3:  ("Dead session number", "Сессия закончена",                         ErrorAction.REAUTH),
    4:  ("Bad interval",       "Неверный временной интервал",               ErrorAction.ABORT),
    5:  ("Bad object",         "Объекта с таким ID нет",                    ErrorAction.MARK_NO_DATA),
    6:  ("Admin login",        "Авторизация под админ-правами",             ErrorAction.ABORT),
    7:  ("Unusable object",    "Значение не рассчитывается для объекта",    ErrorAction.MARK_NO_DATA),
    8:  ("Bad event type",     "Тип события не существует",                 ErrorAction.ABORT),
    9:  ("Access denied",      "Нет прав доступа на объект",                ErrorAction.MARK_NO_DATA),
    10: ("Data not found",     "Данные не найдены",                         ErrorAction.MARK_NO_DATA),
    11: ("Blocked interval",   "Период содержит блокировки данных",         ErrorAction.MARK_NO_DATA),
    12: ("Bad object type",    "Тип объекта не существует",                 ErrorAction.ABORT),
    13: ("Invalid format",     "Неверный формат",                           ErrorAction.ABORT),
    14: ("Undefined error",    "Неопределённая ошибка",                     ErrorAction.RETRY),
    15: ("404",                "Несуществующая страница",                   ErrorAction.ABORT),
}
