# Omnicomm Holding Platform — Developer Guide (для Claude Code)

## Project Overview

Holding-scale аналитическая платформа автопарка: сбор телеметрии из Omnicomm Online
по всем ДЗО холдинга, нормализация в иерархическую модель (Холдинг → ДЗО → под-ДЗО →
подрядчик), перевод в деньги (₸) и раздача отчётов/дашбордов на каждое ДЗО без
посемест­ных лицензий. Выросла из `omnicomm-fleet-report` (single-client отчёт) —
его движок (`src/omnicomm_report/`) переиспользуется, поверх строится holding-слой.

**Прод (2026-06): omnicomm.technokod.kz** — копия аккаунта КАП `projectkap`
(~1962 ТС, 73 узла оргструктуры, 274 теста). Стек:
**Python-движки (`src/omnicomm_report/`) → FastAPI-мост (`api/`) → Next.js фронт (`web/`)**
за реверс-прокси `deploy/holding_proxy.py`; чтения отдаются мгновенно из кэш-снапшота
SQLite (`api/cache.py`) и **не ходят в Omnicomm**. Унаследованный Streamlit-портал
(`holding_app.py`) выпилен из критпути (живёт как legacy-инструмент).

- **▶ НАЧНИ С `docs/DEV_MEMORY.md` — живой снимок состояния для продолжения между сессиями.**
- **Целевой дизайн платформы — `docs/holding-architecture.md` (north star).**
- **Развёртывание прод-стека — `docs/DEPLOY-holding.md`.**
- **Хронология разработки — `NOTES.md` (чек-поинты по ходу).**
- Унаследованный single-client движок (этот же `src/omnicomm_report/`) описан ниже —
  он остаётся фундаментом; holding-слой (dim_org, мульти-аккаунт, star schema) и
  прод-стек (FastAPI + Next.js + кэш-снапшот) надстраиваются.

## Tech Stack

- **Бэкенд:** Python 3.10+ · `fastapi` + `uvicorn` (мост `api/`) · `requests` · `pandas` · `openpyxl` · `matplotlib` · `python-pptx` · `python-dotenv`. Streamlit — legacy.
- **Фронт:** Next.js 16 (static export → `web/out`), TypeScript, инлайн-SVG-графики, Яндекс.Карты. Менеджер пакетов — `pnpm`.
- **Персистентность:** кэш-снапшоты дашборда — SQLite (`api/cache.py`). Лёгкие данные движка — JSON: `output/norms/` (паспорта/нормы), `output/history/` (тренды), `data/clients/` (клиенты). Всё в `.gitignore`.

## Running Locally

```bash
# движок (наследие, отчёт из Excel)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m omnicomm_report --source excel --input samples/fleet_sample.xlsx

# прод-стек локально
uvicorn api.main:app --port 8810        # FastAPI-мост
curl -X POST 127.0.0.1:8810/api/sync -d '{"demo":false}'  # тёплый кэш-снапшот
cd web && pnpm install && pnpm dev       # Next.js (или pnpm build → web/out)
```

## Architecture conventions

- Конвейер: `data_loader → validator → analytics → charts → report_builder`. См. `docs/architecture.md`.
- Единый контракт — `models.py` (`VehicleMetrics`, `FleetReport`). Всё после `data_loader` работает только с ним.
- Источник (API/Excel) абстрагирован в `data_loader`; остальной конвейер не зависит от источника.
- Константы лимитов/эндпоинтов/кодов ошибок — только в `config.py`, не хардкодить по месту.

## Omnicomm API (критично, сверено с api.yaml + проверено на демо/боевом)

- **ПРАВИЛО: перед НОВЫМ запросом/эндпоинтом — СНАЧАЛА читать доку** (`api.yaml`, `docs/api.md`, `docs/api-appendix.md`, `docs/knowledge-base/`, мануал `download/omnicomm_online-manual-ru.pdf`), НЕ перебирать URL вслепую (шум + бьёт по хрупкой копе). Эмпирическая проба — только когда дока молчит, и бережно.
- Заголовок строго `Authorization: JWT <token>` (пробел!). Для доступа к отчётам нужен `service` (напр. `omnicomm`) + права у учётки.
- **Отчёты вызываются POST, не GET.** Сводный: `POST /ls/api/v1/reports/consolidatedReport`,
  тело `{"vehicleIds":[<terminal_id int>],"timeBegin":<unix>,"timeEnd":<unix>}`. Лимиты **≤50 ТС / ≤31 дня** — батчинг и нарезка периода в `api_client._report_post`.
- Ответ — строка на **ТС × сутки** (`mv`/`fuel`/`uniDataList`); имени нет → берём из дерева (`list_vehicles`).
- **Дерево ТС**: `GET /ls/api/v2/tree/vehicle` — ТС вложены в `children[].objects[]` (рекурсивный флэттен в `_flatten_vehicle_tree`).
- **ЕДИНИЦЫ (частый баг ×10):** топливо (`fuelConsumption`, `*WOMovement`, `univInputOnConsumption`, `fuelCons*`) — в **децилитрах → /10 = литры**; время — секунды → /3600; `deviation` — сл /100; `univInputHourConsumption` по факту дл (не доверять, считать из тоталов). Приведение в `data_loader._aggregate_consolidated` (Excel уже в литрах).
- Коды ошибок 0–15 — `config.OMNICOMM_ERRORS`. **Коды 5/7/9/10/11 НЕ прерывают отчёт** — ТС `has_data=False`.
- GPS: `GET /ls/api/v1/reports/track/{terminal_id}?timeBegin&timeEnd` → точки `{lat,lon,speed,satellitesCount}`.
- **Геозоны ПАГИНИРОВАНЫ:** `GET /api/service/geozones/geozones` → `{total,page,pageSize,rows}`. `list_geozones` тянет ВСЕ страницы (`pageSize=1000` = один запрос; `5000` сервер режет 400) + дедуп по id — иначе бралась 1-я страница (200 из 401, терялись внутренние геозоны ДЗО). **Лимит скорости и ТИП ТС зашиты в ИМЯ** (геозона «…50 км/ч», ТС «…Самосвал»), структурных полей нет; per-type×geozone лимит Omnicomm держит в профилях→событиях (на `projectkap` события пусты). Аудит — `docs/audit-vehicle-type-speed-limit.md`.
- **Rate-limit: 180 запросов/мин НА АККАУНТ** (не на клиент/поток). Параллельный синк держит много `OmnicommClient` на одной учётке → нужен общий лимитер (`rate_limit.get_limiter`, ёмкость ≤170/мин с запасом), иначе 429.
- **Текущее состояние ТС: `api_client.get_vehicle_state` → `GET /ls/api/v1/vehicles/{id}/state`** даёт `voltage` (**НАПРЯЖЕНИЕ БОРТСЕТИ**), адрес, зажигание, текущие скорость/топливо. **ВАЖНО: voltage НЕ приходит в `consolidatedReport`** — только в `/state`.
- **На `projectkap` события `GET /ls/api/v1/reports/events/{id}` приходят пустыми** — не строить на них логику для этого аккаунта.
- Демо-контур: `http://online.omnicomm.ru`, `rudemoru/rudemo123456`, service `omnicomm` (есть датчики надстройки у части ТС). Полное описание — `docs/platform.md`.

## Прод-стек: FastAPI-мост (`api/`) + Next.js (`web/`)

Поверх движка и holding-слоя — тонкий веб-стек. **Принцип: синк наполняет кэш-снапшот,
чтения мгновенны.** Деплой — см. `docs/DEPLOY-holding.md`.

### Бэкенд `api/` (FastAPI, uvicorn :8810)
- `main.py` — приложение и эндпоинты:
  - `POST /api/sync` (опц. `start_ts`/`end_ts`/`demo`) — запустить синк → снапшот; возвращает `job_id`.
  - `GET /api/sync/{id}` — статус; `GET /api/sync/{id}/stream` — прогресс по SSE.
  - `GET /api/snapshots` — список снимков; `GET /api/dashboard` — дашборд (опц. `period_key`).
  - `GET /api/geozones`, `/api/recommendations`, `/api/sensor-health`, `/api/maintenance` — секции снапшота.
  - `GET /api/dashboard.xlsx` — Excel-выгрузка дашборда.
  - `GET /api/vehicle/{id}` — карточка ТС (трек); `GET /api/vehicle/{id}/telemetry` — телеметрия.
- **Произвольный диапазон мгновенно (Фаза A):** любой `period_key` формата `YYYY-MM-DD_YYYY-MM-DD`,
  которого нет в кэше, собирается **из локального архива без Omnicomm** — `_ensure_range_snapshot`
  в `_snapshot` (single-flight по ключу; первый заход ~3с, дальше ~25мс из кэша). Фронт: пилюли
  Сутки/Неделя/Месяц/Квартал/Полгода/Год (вычисляемые трейлинг-ключи) + произвольный календарь.
  Полный забор из Omnicomm — только отдельная кнопка «↻ обновить» (`POST /api/sync`). **Фазу B
  (дневной куб) НЕ делать** — отклонена как маргинальная (см. NOTES 01.07).
- `sync.py` — оркестрация синка → снапшот: geozones → speeding → recommendations, sensor health, maintenance.
  - `build_range_snapshot(start,end)` — снимок за ЛЮБОЙ диапазон из архива (0 обращений в Omnicomm):
    период-зависимое считается из `raw_store`, секции текущего состояния (геозоны/Sensor Health/ТО)
    переиспускаются из последнего снимка (`_reconstruct_base`, `_assemble_snapshot(geozones_override=)`).
  - `prewarm_ranges([дни])` — пред-прогрев частых окон (вызывается в конце инкрем-синка на `[7,90,180]`).
- `cache.py` — снапшот-кэш SQLite (чтения дашборда **не** ходят в Omnicomm). **`latest_snapshot` = дефолт дашборда: снимок со СВЕЖАЙШИМ концом периода (среди равных — длиной ближе к 30-дн окну), НЕ последний-по-`synced_at`** — иначе короткие backfill-окна (2-дн) перехватывали бы дефолт и занижали ТС/пустой fleet_table. Счётчик ТС в шапке = `dash.fleet.vehicles`. Число ТС растёт органически (КАП заводит терминалы).
- **Качество данных (светофор):** `TERMINAL_STALE_AFTER_MIN=30`, `TERMINAL_OFFLINE_AFTER_HOURS=24` → 🟢 ≤30 мин · 🟠 30 мин–24 ч · 🔴 >24 ч · ⚪ нет данных. Общий % = `online/total`.
- `jobs.py` — фоновые задачи + single-flight (без дублирующих синков).
- `fetch.py` — параллельный забор из Omnicomm; `serialize.py` — сериализация снапшота.
- `health.py` — секции Sensor Health и Контроль ТО; `excel.py` — Excel-выгрузка.
- `tyres.py` + `tyre_store.py` — **учёт автошин по пробегу** (родственно ТО, но ресурс
  комплекта копится с даты установки из ГОДОВОГО архива `raw_store`, а не за окно снапшота).
  Секция `tyres` в снапшоте, износ в ₸ (доля отхоженного × стоимость). Стор `data/cache/tyres.db`
  (план/цикл/журнал замен). Эндпоинты `/api/tyres`, `/api/tyres/{id}/replace|plan|history`
  (мутации — по скоупу ТС). Движок — `omnicomm_report/tyres.py`. Тесты `test_tyres.py`.
  MVP = комплект на ТС; позиции/оси/ротация — фаза 2. **В Omnicomm такого отчёта нет** (наш value-add).
- `vehicle.py` — карточка ТС: трек **сначала из локального архива** (`raw_store.fact_track`,
  мгновенно, в Omnicomm не ходим), live-фолбэк с TTL-кэшем только если архив за окно пуст.
- `raw_store.py` — сырое локальное хранилище SQLite: `fact_daily` (агрегат ТС×сутки),
  `fact_visit` (визиты геозон), **`fact_track` (упрощённый GPS-трек ТС×сутки)** — основа
  «весь год у себя». `upsert/load_track`, `tracks_present` (batch-skip), `track_coverage`,
  `prune_before` (ретеншн агрегатов+визитов+треков). Тесты — `test_raw_store.py`, `test_track_backfill.py`.
- `track_backfill.py` — **бережный бэкфилл треков за год** (`run_track_backfill`):
  выделенный медленный лимит ≪ аккаунта, только дни с движением (по `fact_daily`),
  резюмируемо+идемпотентно (чекпоинт=строка `fact_track`), кап-таймаут на слайс,
  хранение упрощённой полилинией (`track_clean.simplify_track`). Эндпоинты `POST /api/track/backfill`
  (single-flight), `GET /api/track/coverage`. Cron ночного до-вода — `docs/DEPLOY-holding.md`.
- Тесты — `test_api_bridge.py`, `test_api_mode.py`, `test_health_excel.py`.

### Фронт `web/` (Next.js 16, static export → `web/out`)
- **Компоненты:** `ScopeRail`, `HealthStrip`, `AttentionFeed`, `Overview`, `DomainTabs`,
  `TileKPI`, `EconomicsPanel`, `Recommendations` (структурные поля канона), `SensorHealthPanel`,
  `MaintenancePanel`; карты `GeozoneMap`/`YandexGeozoneMap` (Яндекс hybrid)/`MapLibreGeozoneMap`/`GoogleGeozoneMap`;
  `VehicleCard`, `SyncBar` (выбор снимка + шаблоны периода + произвольный период), `Toolbar`, `ThemeToggle`.
- `charts.tsx` — инлайн-SVG-графики: `ColumnChart`, `StackedBar`, `RankBars`, `LineChart` (без внешних либ).
- **lib:** `scope.ts` (скоупинг по `vehicle_org`), `i18n.ts` (RU/KK), `ymaps.ts` (загрузчик Яндекс.Карт), `api.ts`, `format.ts`.
- **Тема:** цвета Omnicomm Online + шрифт Roboto, светлая/тёмная через `[data-theme]`,
  токены в `globals.css`. `NEXT_PUBLIC_YANDEX_MAPS_API_KEY` — в `web/.env.production`.

### Снапшот-движки (`src/omnicomm_report/`, питают синк)
- `geozones.py`, `speeding.py`, `recommendations.py` (рекомендации по канону СТ КАП `kb-05`),
  `sensor_health.py`, `maintenance.py`, `geomap.py`, `ai_engine.py`.
- `classify.py` — `is_transport`: фильтр не-ТС (АЗС/ёмкости/ФЭС/генераторы/IMEI-объекты)
  из денежных рейтингов — **вентиль доверия** к экономике. Тесты — `test_classify.py`.
- `rate_limit.py` — **ГЛОБАЛЬНЫЙ token-bucket ≤170/мин на аккаунт** (лимит Omnicomm 180/мин),
  общий на все потоки; вызывается в `OmnicommClient._throttle`. **ГОЧА:** параллельный синк =
  много клиентов на ОДНОЙ учётке, а лимит — на аккаунт → лимитер обязан быть общим. Тесты — `test_rate_limit.py`.
- Тесты секций — `test_geozones.py`, `test_speeding.py`, `test_recommendations.py`,
  `test_sensor_health.py`, `test_maintenance.py`, `test_geomap.py`.

КОАП РК для рекомендаций по нарушениям сверен: `KOAP_VERIFIED=True` (adilet, ред. 03.10.2024 №131-VIII).

## Holding-слой (новое в этой платформе — см. docs/holding-architecture.md)

- `org.py` — `dim_org`: иерархия организаций (Холдинг→ДЗО→под-ДЗО→подрядчик),
  построение из дерева ТС Omnicomm (`build_from_omnicomm_tree`), **row-level доступ
  по поддереву** (`OrgTree.can_view`/`visible_org_ids`), маппинг ТС→org_id, JSON-реестр.
  Конфиденциальность между ДЗО — `filter_vehicles_for_viewer` (fail-closed). Тесты — `test_org.py`.
- `org.assign_org_ids` — ингест: проставить `org_id` ТС из маппинга реестра.
- `rollup.py` — роллапы KPI по иерархии: `rollup_kpi` (org_id→FleetKPI по ТС поддерева,
  переиспользует `analytics.compute_kpi`), `build_org_kpi_tree` (дерево `OrgKPI` для дашборда).
  ДЗО агрегирует все свои под-ДЗО (которых может быть несколько) и подрядчиков. Тесты — `test_rollup.py`.
- `dashboard.py` — дашборд/отчёт на ДЗО: `build_org_report` (FleetReport на срез поддерева,
  переиспользует `analytics.analyze`), `render_org_report` (графики+HTML/PPTX),
  `render_for_scope` (рендер по всем ДЗО в пределах scope пользователя; изоляция). Тесты — `test_dashboard.py`.
- `holding.py` — end-to-end оркестратор: `build_registry`, `run` (реестр→ингест→роллапы→
  дашборды), `run_from_client`/`fetch_fleet` (забор из живого Omnicomm). `HoldingRun`. Тесты — `test_holding.py`.
- `track_clean.py` — чистка GPS-трека по физике (`clean_track` — телепорт-и-возврат по
  расстоянию/Δt; `reconcile_vehicle_speed` — правдоподобная max_speed + пометка). Замена окна
  по длительности из Power BI. Хук интеграции — `data_loader` где тянется трек. Тесты — `test_track_clean.py`.
- `store.py` — SQLite star schema (`dim_org`+`vehicle_org`). `org.save/load_org_registry`
  диспетчат по расширению: `.db`/`.sqlite`→SQLite, иначе JSON. Postgres — в `store._connect()`. Тесты — `test_store.py`.
- `holding_app.py` (корень) — Streamlit holding-портал (**legacy**): вход по scope → дашборд ДЗО. Выпилен из критпути, прод-UI теперь `web/` + `api/`.
- `auth` (holding): у пользователя `org_id` (узел dim_org). `create_user(org_id=…)`,
  `authenticate()`, `user_org`, `get_user`. Доступ = `org.OrgTree.visible_scope` (admin=всё, иначе поддерево).
- `models.VehicleMetrics.org_id` — привязка ТС к узлу `dim_org`.

## Модули сверх MVP (см. docs/platform.md)

- `loading.py` — «Работа на погрузке» (мусоровозы): авто-источник sensor→rpm→none + GPS-кластеры.
- `vehicle_types.py` — типы техники + профили (шаблон управляет метрикой расчёта).
- `norms.py` — паспорта/нормы по клиенту (enter-once) + коэффициенты → перерасход/экономия (₸).
- `alerts.py` — авто-сигналы (перерасход/простой/тёмные ТС). `benchmark.py` — сравнение парков (обезличенно).
- `fuel_price.py` — парсер цены ГСМ (Royal Petrol, playwright) + сверка/чек-поинт ДТ лето/зима.
- `history.py` — тренды период-к-периоду. `mailer.py` — рассылка отчётов/сигналов (SMTP из ENV).
- `clients.py` + `app.py` — мульти-клиентская платформа (учётка/настройки/e-mail хранятся, `data/` gitignored).
- Доп-аналитика в `analytics`: `build_whatif`, `build_scorecard`.

## Прочие гочи
- **Макс. скорость**: значения > `MAX_PLAUSIBLE_SPEED_KMH` (200) — сбой GPS (напр. 655 км/ч);
  фильтруются по суткам в агрегации + `validator` убирает из KPI и флажит «требует проверки».
- Перед коммитом: реального пароля нет в диффе (паттерн `password=` в коде/тестах — ложный позитив).

## Правила отчёта (бизнес-инварианты)

- Столбец «возможные сливы топлива» НИКОГДА не выводится в `.pptx`.
- Аномалии — только `severity=REVIEW` («требует проверки»), без обвинительных формулировок.
- Перерасход не утверждать без согласованных норм.
- Светлый фон, официальный корпоративный стиль, читаемый текст.

## Security

- Логин/пароль/токены — только из ENV (`LOGIN`, `PASSWORD`, `SERVICE`). Не в коде, не в логах, не в отчёте.
- `.env`, `secrets/`, `*.token`, `data/`, `output/*` — в `.gitignore`. Коммитить только `.env.example`.
- Платформа (`clients.py`) хранит пароли клиентов в `data/` с base64-обфускацией — **песочница, не криптостойко**; для прода заменить на секрет-хранилище/шифрование.
- Перед коммитом сверять, что реального пароля нет в диффе (паттерн `password=` в коде/тестах — ложный позитив).

## Deploy (прод omnicomm.technokod.kz — см. docs/DEPLOY-holding.md)

- Keep-alive — **cron + flock (НЕ systemd)**. API uvicorn :8810, реверс-прокси :8535, фронт раздаётся из `web/out`.
- **Рестарт API — по PID, не `pkill`** (на сервере могут жить другие uvicorn-процессы).
- Бэкенд (`api/`, `src/`): `git pull` → рестарт uvicorn по PID. Фронт (`web/`): `rm -rf out .next && pnpm build` (прокси раздаёт `web/out` с диска, рестарт не нужен).
- Синк тёплого кэша — cron `POST /api/sync` под `flock` (частота `ENV REFRESH_TIMES_PER_DAY`, по умолч. 8×/сутки `0 */3 * * *`). Новые секции снапшота (Sensor Health / ТО) появляются только в свежих синках.

## Testing

- `python -m pytest -q` — проходит (274 теста на проде).
- `python -m compileall src api` — синтаксис ок.
- Smoke: режим Б на `samples/fleet_sample.xlsx` должен собрать `.pptx` без ошибок.
- Фронт: `cd web && pnpm build` (static export в `web/out`).

## Git

- Conventional Commits, описание на русском, инфинитив, ≤72 символа, без точки.
- Ветки `feat/xxx`, `fix/xxx`. Не коммитить `.env`, `web/.env.production`, `output/*.pptx`, `web/out`, `web/node_modules`, кэш-снапшоты SQLite.
