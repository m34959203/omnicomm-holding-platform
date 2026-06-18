# Архитектура

## Конвейер данных

```
                 ┌─────────────────────────────────────────────┐
Omnicomm REST ──►│ api_client  auth/refresh/retry/лимиты/ошибки  │──┐
                 └─────────────────────────────────────────────┘  │
                                                                   ▼
                                                          ┌──────────────┐
Excel (.xlsx) ───────────────────────────────────────────►│ data_loader  │  → единая модель (models.py)
                                                          └──────┬───────┘
                                                                 ▼
                                                          ┌──────────────┐
                                                          │  validator   │  пропуски, ошибки, аномалии
                                                          └──────┬───────┘
                                                                 ▼
                                                          ┌──────────────┐
                                                          │  analytics   │  KPI + управленческие выводы
                                                          └──────┬───────┘
                                                                 ▼
                                          ┌──────────────┐   ┌──────────────┐
                                          │    charts    │──►│ report_builder│  → .pptx (+ .pdf / .xlsx)
                                          └──────────────┘   └──────────────┘
```

## Модули (ТЗ §12)

| Модуль | Файл | Ответственность |
|---|---|---|
| `config` | `src/omnicomm_report/config.py` | Параметры, секреты (из ENV), лимиты, эндпоинты, коды ошибок |
| `models` | `src/omnicomm_report/models.py` | Единая модель данных (режимы А/Б) — контракт между модулями |
| `api_client` | `src/omnicomm_report/api_client.py` | JWT-авторизация, refresh, ретраи, лимиты, батчинг, коды ошибок |
| `data_loader` | `src/omnicomm_report/data_loader.py` | Загрузка из API или Excel → `list[VehicleMetrics]` |
| `validator` | `src/omnicomm_report/validator.py` | Проверка пропусков, ошибок, маркировка аномалий |
| `analytics` | `src/omnicomm_report/analytics.py` | Расчёт `FleetKPI` + управленческие выводы |
| `charts` | `src/omnicomm_report/charts.py` | Графики/диаграммы (matplotlib → PNG для слайдов) |
| `report_builder` | `src/omnicomm_report/report_builder.py` | Сборка `.pptx` (+ `.pdf` / `.xlsx` по флагу) |
| CLI | `src/omnicomm_report/__main__.py` | Точка входа, оркестрация конвейера |

## Ключевой контракт

Все модули после `data_loader` работают только с `models.py`:
`VehicleMetrics` (показатели ТС) → `FleetReport` (период, KPI, выводы, список ТС).
Это и есть «единая внутренняя модель данных» из ТЗ §16.5 — общая для API и Excel.

## Принципы устойчивости

- Коды ошибок Omnicomm 5/7/9/10/11 по конкретному ТС **не прерывают** отчёт — ТС помечается `has_data=False` (ТЗ §4.5).
- Лимиты Omnicomm соблюдаются клиентом: батчинг по 15 ID, пауза 0.4 с, упреждающий refresh токена.
- Источник данных абстрагирован: добавить CSV-режим — это новая функция в `data_loader`, остальной конвейер не меняется.
