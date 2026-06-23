# Интеграция с Omnicomm Online REST API

> Контур авторизации, лимиты, коды ошибок и состав эндпоинтов выверены по
> официальной OpenAPI-спеке (`developers.omnicomm.ru/api.yaml`, 1.3.7).
> **Точные тела/поля методов и единицы — в [api-appendix.md](api-appendix.md)
> (Техническое приложение §16).**

## Контуры

| Контур | Адрес | Доступ |
|---|---|---|
| Демо (отладка) | `http://online.omnicomm.ru` (именно **http**) | логин `rudemoru`, пароль `rudemo123456` |
| Боевой kz | `https://kz.omnicomm.online` — **подтвердить у отдела техобслуживания** | права REST API выдаёт Omnicomm |

Формат времени во всех запросах — **UNIX timestamp (секунды, UTC)**.

## Авторизация (подтверждено документацией)

- Получение JWT: `POST /auth/login?jwt=1`.
- Обновление: `POST /auth/refresh` — refresh-JWT передаётся в заголовке `Authorization`.
- Все вызовы (кроме авторизации): заголовок `Authorization: JWT <token>` (пробел между `JWT` и токеном).
- Срок токена — в payload `exp` (Unix UTC). По истечении — `401`, нужен `refresh` или повторный `login`.

## Эндпоинты (ТЗ §4.3)

| Назначение | Метод / путь |
|---|---|
| Авторизация | `POST /auth/login?jwt=1` |
| Обновление токена | `POST /auth/refresh` |
| Дерево / список ТС | `GET /ls/api/v2/tree/vehicle` |
| Каталог отчётов | `GET /ls/api/v1/reports/` |
| Сводный отчёт | `GET /ls/api/v1/reports/consolidatedReport` |
| События (v1/v2) | `GET /ls/api/v1/reports/events/` · `GET /ls/api/v2/reports/events/` |
| Активность ТС | `GET /ls/api/v1/activity/vehicles` |
| Водители | `GET /ls/api/v1/drivers` |
| Трек ТС | `GET /ls/api/v1/reports/track/{id}` |
| Ссылки общего доступа (опц.) | `POST /ls/api/v1/reports/links` |

ТС идентифицируется строковым **UUID** (или ID терминала); одно ТС может входить в несколько групп.

## Каталог отчётов (ТЗ §4.4)

`GET /ls/api/v1/reports/` → по каждому отчёту: `id`, `code`, `group`
(`favourite`/`reports`/`maps`/`graphs`/`charts`), `objectTypes`
(`FAS` ТС, `FTC` топливозаправщик, `DRV` водитель, `GEOZONE`, `ROUTE`).

Ключевые: **consolidatedreport** (id 32, `FAS`/`FTC`) — агрегаты;
**fueleventsreport** (id 8) — топливные события.

## Лимиты (подтверждено разделом «Ограничения»)

- авторизованные вызовы — **180 / мин** на пользователя;
- неуспешные авторизации — **10 / мин** с IP;
- неавторизованные вызовы — **60 / мин** с IP.

Эталонная конфигурация клиента: батч 15 ID, пауза 0.4 с, таймаут 30 с,
запас по токену 120 с, ретраи на `{429,500,502,503,504}` (login ≤5, refresh ≤3).

## Коды ошибок (полный официальный список)

| Код | Значение | Поведение клиента |
|---|---|---|
| 0 | Ошибок нет | норма |
| 1 | Неверный логин/пароль | прервать, не ретраить login |
| 2 | Требуется авторизация | login/refresh |
| 3 | Сессия закончена | повторная авторизация |
| 4 | Неверный интервал | прервать, исправить период |
| 5 | Объекта нет | пометить ТС, продолжить |
| 6 | Авторизация под админ-правами | прервать, сменить учётку |
| 7 | Значение не рассчитывается | ТС «нет данных» |
| 8 | Тип события не существует | прервать запрос события |
| 9 | Нет прав доступа | пометить ТС, продолжить |
| 10 | Данные не найдены | **не прерывать отчёт**, ТС «нет данных» |
| 11 | Период содержит блокировки | пометить интервал, продолжить |
| 12 | Тип объекта не существует | прервать, исправить запрос |
| 13 | Неверный формат | прервать, исправить запрос |
| 14 | Неопределённая ошибка | ретрай, затем лог |
| 15 | 404 | проверить путь метода |

**Ключевое правило:** код 10 по конкретному ТС не прерывает отчёт — ТС
помечается «нет данных». Аналогично коды 5/7/9/11 (по объекту/интервалу).

## Безопасность (ТЗ §4.6)

Логин/пароль/токены — только из ENV (`LOGIN`, `PASSWORD`, `SERVICE`),
не в коде. Токены не логировать; учётные данные не попадают в отчёты и логи.

---

## Техническое приложение (ТЗ §16) — заполняется на этапе разработки

Заполняется после доступа к Swagger UI (`developers.omnicomm.ru`) под демо/боевой
учётной записью. Прямая ссылка на `api.yaml` в сыром виде недоступна.

### 16.1 `GET /ls/api/v1/reports/consolidatedReport`
- Параметры: период (UNIX UTC), список ID/UUID ТС, код/ID отчёта, набор полей.
- Структура ответа: _<заполнить>_ (пробег, расход, моточасы, время работы двигателя, работа без движения…).
- Маппинг ответ → `VehicleMetrics`: _<заполнить>_.

### 16.2 `GET /ls/api/v1/reports/events/{id}` (события) — проверено 2026-06-22
- **Метод/форма (подтверждено эмпирически):** `GET /ls/api/v1/reports/events/{id}`,
  тип события — в **пути `{id}`** (НЕ в теле; POST виснет). Query:
  `vehicleIds` (повторяющийся, целые terminal_id), `timeBegin`, `timeEnd` (**unix-сек**;
  ISO-даты `dateBegin/dateEnd` отвергаются — `code 3 "timeBegin is required"`).
- **Структура ответа:** `{"status":{"code":0,"message":"OK"},"events":[...]}`.
- **Коды типов (из КАП-проекта, под учёткой `kazatompromsd`):** `speeding=14`,
  `zone_speeding=94`; параметры события (по `event_params.param_index`):
  speeding `{0:allowed_speed, 1:average_speed, 2:duration}`,
  zone_speeding `{0:allowed_speed, 2:average_speed, 3:duration}`.
- ⚠️ **На нашей учётке `projectkap` события ПУСТЫ:** `{id}`=14/94/8/1/2/13/15 за 30 дней
  по известным нарушителям → `events:[]` (code 0 OK), каталог отчётов `GET /reports/`
  → 1 пустая запись. Endpoint доступен (не 403), но **данных нет — события не
  провиженены для аккаунта**. КАП-код получал их под `kazatompromsd` (другие права).
  Вывод: апгрейд детекции на реальные события требует аккаунта с включёнными
  событиями; на `projectkap` остаёмся на геозон-эвристике (`speeding.detect_from_visits`).
- **v2** `GET /ls/api/v2/reports/events/` (без `{id}`) с query → `404 PATH Not found`
  в нашей форме; контракт v2 не подтверждён.

### 16.3 `GET /ls/api/v1/activity/vehicles`
- Параметры и структура ответа (активность/простой ТС): _<заполнить>_.

### 16.5 `GET /ls/api/v1/vehicles/{id}/state` — текущее состояние ТС (проверено 2026-06-23)
- **Метод:** GET, `{id}` = terminal_id ИЛИ uuid (оба работают; v2 → 404). Лёгкий быстрый вызов (~0.5с).
- **Ответ:** мгновенные значения последнего пакета (раздел «Посл. данные» карточки Omnicomm):
  ```json
  {"lastGPS":{"latitude":..,"longitude":..}, "lastGPSDir":.., "lastGPSSat":..,
   "currentSpeed":68.5, "currentFuel":252.2, "currentIgn":true, "speedExceed":false,
   "voltage":27.6, "checkVoltage":0, "address":"…", "lastDataDate":<unix>, "currentInputValue":[]}
  ```
- ✅ **`voltage` = НАПРЯЖЕНИЕ БОРТСЕТИ доступно** (12В→~13.8, 24В→~27.6). Это исправляет прежний вывод
  «напряжение недоступно через REST»: оно НЕ в дневном `consolidatedReport` (там нет voltage ни в
  mv/fuel/uniDataList/ccan/canmt/can), но есть в текущем состоянии `/vehicles/{id}/state`.
  **Снимает блокер Sensor Health ур.1.5** («сбой ДУТ vs обесточенный терминал» — voltage как gate).
- Применено: карточка ТС (`api/vehicle.py` → `client.get_vehicle_state`).

### 16.4 Каталог отчётов
- Фактический вывод `GET /ls/api/v1/reports/` с подтверждёнными `id`/`code`/`group`/`objectTypes`: _<заполнить>_.

### Источники
- Авторизация — https://doc.omnicomm.ru/ru/omnicomm_online-integration/rest_api/authorization
- Ограничения — https://doc.omnicomm.ru/ru/omnicomm_online-integration/rest_api/restriction
- Отчёты — https://doc.omnicomm.ru/ru/omnicomm_online-integration/rest_api/report
- Управление ТС — https://doc.omnicomm.ru/ru/omnicomm_online-integration/rest_api/add_vehicle
- Демо-доступ — https://doc.omnicomm.ru/ru/omnicomm_online-integration/demo/rest
- Подключение — https://doc.omnicomm.ru/ru/omnicomm_online-integration/connection
- Коды ошибок — https://doc.omnicomm.ru/ru/omnicomm_online-integration/definition/error
- OpenAPI / Swagger UI — https://developers.omnicomm.ru
