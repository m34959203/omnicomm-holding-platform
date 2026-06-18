# Техническое приложение к ТЗ (§16) — выверенные схемы Omnicomm API

Источник: машинная OpenAPI-спецификация `https://developers.omnicomm.ru/api.yaml`,
выгружена через браузер (same-origin fetch — обычный `fetch`/WebFetch её не отдаёт
из-за клиентского рендеринга Swagger UI).

- **Версия спецификации:** OpenAPI 3.0.0, `version: 1.3.7`, title «Omnicomm API specification».
- **Server (из спеки):** `https://online.omnicomm.ru` (демо/общий контур; боевой kz-адрес выдаёт Omnicomm).
- **Всего путей в спеке:** 62.

> Статус кода: реализация в репозитории (`api_client._report_post`,
> `data_loader._aggregate_consolidated`) уже соответствует этой спеке — POST,
> лимиты 50/31, децилитры÷10, `deviation` не выводится. Этот документ закрывает
> открытый вопрос §16 ТЗ и фиксирует контракт.

---

## 1. Ключевые исправления к ТЗ v1.1 (по факту спеки)

| Что в ТЗ v1.1 | Факт по api.yaml 1.3.7 |
|---|---|
| Сводный отчёт — `GET /ls/api/v1/reports/consolidatedReport` | **POST**, не GET. Тело JSON `{vehicleIds:[int], timeBegin:int, timeEnd:int}` |
| Каталог отчётов — `GET /ls/api/v1/reports/` | путь `GET /ls/api/v1/reports` (без хвостового слэша; со слэшем тоже отвечает) |
| События v2 — `GET /ls/api/v2/reports/events/` | существует, но **без `{id}`** (v1 — по `{id}`, см. ниже) |
| Лимиты consolidatedReport | подтверждено спекой: **≤ 50 ТС и ≤ 31 дня** на запрос |

---

## 2. Авторизация

- `POST /auth/login` (query `jwt=1`) — «Возвращает токен jwt с правами пользователя».
  Тело — схема `loginParameters` (`login`, `password`, `service`).
- `POST /auth/refresh` — «Возвращает новый jwt»; refresh-JWT в заголовке `Authorization`.
- Заголовок вызовов: `Authorization: JWT <token>` (с пробелом). `security: []` стоит
  только у `login` (единственный публичный метод).

---

## 3. Сводный отчёт — `POST /ls/api/v1/reports/consolidatedReport`

**Запрос (application/json), required:**

```json
{
  "vehicleIds": [<terminal_id:int>, ...],
  "timeBegin": <unix>,
  "timeEnd":   <unix>
}
```

Ограничения метода: ≤ 50 ТС и ≤ 31 дня на запрос → батчинг по ТС и нарезка периода.

**Ответ 200 (`code = 0 — OK`):** `items[]`, по одному объекту на **ТС × сутки**:

```
items[].consolidatedReport:
  vehicleId : int            # ID ТС
  date      : int            # UNIX (сек, UTC+00), начало суток 00:00:00
  mv  : {...}                # блок «Движение и работа»
  fuel: {...}                # блок «Топливо (основная ёмкость)»
  can : {...}                # «Пробег/расход/моточасы по шине CAN»
```

Имени ТС в ответе нет → берётся из дерева ТС (`/ls/api/v2/tree/vehicle`).

### 3.1. Блок `mv` (движение и работа)

| Поле | Описание (из спеки) | Единица |
|---|---|---|
| `mileage` | Пробег | км |
| `mileageAtPeriodBegin/End` | Общий пробег на начало/конец периода | км |
| `motoHoursServiceCounter` | Счётчик моточасов на конец периода | мтч |
| `mileageSpeeding` | Пробег с превышением скорости | км |
| `maxSpeed` | Максимальная скорость | км/ч |
| `movement` / `worked` | Время движения / работы двигателя | **с (секунды)** |
| `workedOnMovement` / `workedNoMovement` | Работа двигателя в движении / без движения | **с** |
| `*Percent` | Те же доли | % от периода |
| `idlingRPM` / `normalRPM` / `excessRPM` / `workedUnderLoadRPM` | Режимы по оборотам | — |
| `layUp` | Простой | с / % |

### 3.2. Блок `fuel` (топливо) — **единицы критичны**

| Поле | Описание (из спеки) | Единица по спеке |
|---|---|---|
| `startVolume` / `endVolume` / `maxVolume` / `minVolume` | Объёмы в баке | **дл (децилитры)** |
| `fuelConsumption` | Фактический расход | **дл** |
| `fuelConsumptionOnMove` | Расход в движении | **дл** |
| `fuelConsumptionWOMovement` | Расход без движения | **дл** |
| `fuelCons100` / `fuelConsumptionOnMove100` | Расход на 100 км (общий / в движении) | **дл** |
| `refuelling` | Объём заправок | **дл** |
| `draining` | Объём сливов | **дл** |
| `delivery` | Объём выдач | сл |
| `deviation` | **«Возможный слив»** (для АТЗ) | сл |
| `dutyConsumption100` / `normCons100` | Норма / расчётный расход по норме на 100 км | **л** |
| `normConsumptionMH` | Расчётный расход по норме на моточас | **л** |
| `fuelCons100Dev` / `fuelConsDev` | Отклонение от нормы (100 км / моточас) | % |

> **Ловушка единиц:** фактический расход и объёмы — в **децилитрах** (÷10 = литры),
> а нормативные поля (`normCons100`, `normConsumptionMH`) — уже в **литрах**.
> Смешивать нельзя. Обрабатывается в `data_loader._aggregate_consolidated`.
>
> **Инвариант ТЗ:** `deviation` = «Возможный слив» — столбец, который **запрещено
> выводить** в клиентский отчёт (§9). Не показывается (тесты `test_*_no_forbidden_words`).

---

## 4. Прочие используемые эндпоинты (метод подтверждён спекой)

| Назначение | Метод / путь | Примечание |
|---|---|---|
| Дерево ТС | `GET /ls/api/v2/tree/vehicle` | ТС и группы; есть и `/{groupId}` |
| Активность ТС | `GET /ls/api/v1/activity/vehicles` | даты последнего поступления данных; есть и v2 |
| События (v1) | `GET /ls/api/v1/reports/events/{id}` | по `{id}`; query `tankIds` |
| События (v2) | `GET /ls/api/v2/reports/events/` | без `{id}` |
| Трек ТС | `GET /ls/api/v1/reports/track/{id}` | точки GPS; есть и `/track` |
| Каталог отчётов | `GET /ls/api/v1/reports` | список доступных отчётов |
| Ссылки общего доступа | `/ls/api/v1/reports/links`, `/links/{linkId}` | опционально |
| Прочие отчёты | `fuellevel`, `statistics`, `rpms`, `geozones`, `currentState`, `customreport`, `failures`, `clients` | при необходимости |

---

## 5. Коды ошибок (по руководству + ответам спеки)

0 — OK · 1 — доступ запрещён/нет ни одного доступного ТС · 2 — нужна авторизация ·
3 — сессия закончена · 4 — неверный интервал · 5 — нет объекта · 9 — нет прав ·
10 — данные не найдены · 13 — неверный формат · 14 — неопределённая ошибка
(полный список 0–15 — в `config.OMNICOMM_ERRORS`). Коды по конкретному ТС
(5/7/9/10/11) не прерывают отчёт — ТС помечается «нет данных».

---

_Выгружено и сверено через браузер по `developers.omnicomm.ru/api.yaml` (OpenAPI 1.3.7)._
