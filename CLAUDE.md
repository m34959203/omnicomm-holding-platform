# Omnicomm Holding Platform — Developer Guide (для Claude Code)

## Project Overview

Holding-scale аналитическая платформа автопарка: сбор телеметрии из Omnicomm Online
по всем ДЗО холдинга, нормализация в иерархическую модель (Холдинг → ДЗО → под-ДЗО →
подрядчик), перевод в деньги (₸) и раздача отчётов/дашбордов на каждое ДЗО без
посемест­ных лицензий. Выросла из `omnicomm-fleet-report` (single-client отчёт) —
его движок переиспользуется, поверх строится holding-слой.

- **▶ НАЧНИ С `docs/DEV_MEMORY.md` — живой снимок состояния для продолжения между сессиями.**
- **Целевой дизайн платформы — `docs/holding-architecture.md` (north star).**
- **Хронология разработки — `NOTES.md` (чек-поинты по ходу).**
- Унаследованный single-client движок (этот же `src/omnicomm_report/`) описан ниже —
  он остаётся фундаментом; holding-слой (dim_org, мульти-аккаунт, star schema) надстраивается.

## Tech Stack

- Python 3.10+ · `requests` · `pandas` · `openpyxl` · `matplotlib` · `python-pptx` · `python-dotenv` · `streamlit`
- БД нет — лёгкая персистентность в JSON: `output/norms/` (паспорта/нормы), `output/history/` (тренды), `data/clients/` (клиенты платформы). Всё в `.gitignore`.

## Running Locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m omnicomm_report --source excel --input samples/fleet_sample.xlsx
```

## Architecture conventions

- Конвейер: `data_loader → validator → analytics → charts → report_builder`. См. `docs/architecture.md`.
- Единый контракт — `models.py` (`VehicleMetrics`, `FleetReport`). Всё после `data_loader` работает только с ним.
- Источник (API/Excel) абстрагирован в `data_loader`; остальной конвейер не зависит от источника.
- Константы лимитов/эндпоинтов/кодов ошибок — только в `config.py`, не хардкодить по месту.

## Omnicomm API (критично, сверено с api.yaml + проверено на демо/боевом)

- Заголовок строго `Authorization: JWT <token>` (пробел!). Для доступа к отчётам нужен `service` (напр. `omnicomm`) + права у учётки.
- **Отчёты вызываются POST, не GET.** Сводный: `POST /ls/api/v1/reports/consolidatedReport`,
  тело `{"vehicleIds":[<terminal_id int>],"timeBegin":<unix>,"timeEnd":<unix>}`. Лимиты **≤50 ТС / ≤31 дня** — батчинг и нарезка периода в `api_client._report_post`.
- Ответ — строка на **ТС × сутки** (`mv`/`fuel`/`uniDataList`); имени нет → берём из дерева (`list_vehicles`).
- **Дерево ТС**: `GET /ls/api/v2/tree/vehicle` — ТС вложены в `children[].objects[]` (рекурсивный флэттен в `_flatten_vehicle_tree`).
- **ЕДИНИЦЫ (частый баг ×10):** топливо (`fuelConsumption`, `*WOMovement`, `univInputOnConsumption`, `fuelCons*`) — в **децилитрах → /10 = литры**; время — секунды → /3600; `deviation` — сл /100; `univInputHourConsumption` по факту дл (не доверять, считать из тоталов). Приведение в `data_loader._aggregate_consolidated` (Excel уже в литрах).
- Коды ошибок 0–15 — `config.OMNICOMM_ERRORS`. **Коды 5/7/9/10/11 НЕ прерывают отчёт** — ТС `has_data=False`.
- GPS: `GET /ls/api/v1/reports/track/{terminal_id}?timeBegin&timeEnd` → точки `{lat,lon,speed,satellitesCount}`.
- Демо-контур: `http://online.omnicomm.ru`, `rudemoru/rudemo123456`, service `omnicomm` (есть датчики надстройки у части ТС). Полное описание — `docs/platform.md`.

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

## Testing

- `python -m pytest -q` — проходит.
- `python -m compileall src` — синтаксис ок.
- Smoke: режим Б на `samples/fleet_sample.xlsx` должен собрать `.pptx` без ошибок.

## Git

- Conventional Commits, описание на русском, инфинитив, ≤72 символа, без точки.
- Ветки `feat/xxx`, `fix/xxx`. Не коммитить `.env`, `output/*.pptx`.
