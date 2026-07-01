"""Клиент Omnicomm Online REST API (ТЗ §4).

Отвечает за транспорт: авторизацию (JWT + refresh), упреждающее обновление
токена, ретраи, самоограничение по лимитам контура и трактовку кодов ошибок
Omnicomm. Возвращает «сырые» dict/list — маппинг в `VehicleMetrics` делает
`data_loader`, чтобы клиент не зависел от внутренней модели данных.

Почему так:
- заголовок строго `Authorization: JWT <token>` (с пробелом) — требование контура;
- токен обновляем заранее (за `SKEW_SECONDS` до `exp`), чтобы не ловить 401 в середине отчёта;
- коды ошибок 5/7/9/10/11 по одному ТС НЕ должны валить весь отчёт — возвращаем маркер.

Секреты (логин/пароль/токены) никогда не логируются.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time
from typing import Any, Optional

import requests

from omnicomm_report import config
from omnicomm_report.config import ErrorAction, Settings
from omnicomm_report.models import ReportPeriod

logger = logging.getLogger(__name__)


# --- Имена полей тела POST отчётов (сверено с developers.omnicomm.ru/api.yaml) -
# consolidatedReport вызывается POST'ом с телом:
#   {"vehicleIds": [<terminal_id int>], "timeBegin": <unix_sec>, "timeEnd": <unix_sec>}
# Размер запроса: ≤50 ТС и ≤31 суток на один запрос — ЭМПИРИЧЕСКИЙ предел (батч 50
# эмпирически принимается сервером, прод-синк КАП на нём работает), НЕ официальный.
# Официальная док-ция (doc.omnicomm.ru/.../rest_api/restriction) ограничивает ТОЛЬКО
# частоту: 180 запросов/мин на пользователя; лимита на vehicleIds/период там НЕТ.
# Эталонная конфигурация в той же док-ции советует батч 15 ID (см. config.MAX_IDS_PER_REQUEST).
PARAM_VEHICLE_IDS = "vehicleIds"   # массив terminal_id (int) для consolidatedReport
PARAM_TIME_BEGIN = "timeBegin"     # начало интервала, UNIX UTC, секунды
PARAM_TIME_END = "timeEnd"         # конец интервала, UNIX UTC, секунды

MAX_VEHICLES_PER_REPORT = 50       # ТС в запросе consolidatedReport — эмпирич. предел (не офиц.)
MAX_DAYS_PER_REPORT = 31           # длина периода, суток — эмпирич. предел (не офиц.)

# Возможное имя поля кода ошибки Omnicomm в теле ответа (ТЗ §16).
# TODO: сверить со Swagger — на разных методах поле называют по-разному.
ERROR_CODE_KEYS = ("error", "errorCode", "code", "err")


# Спец-маркер: по конкретному ТС/интервалу данных нет (коды 5/7/9/10/11).
# Не исключение — отчёт по остальным ТС продолжается (ТЗ §4.5, бизнес-инвариант).
class NoData:
    """Маркер «нет данных» по объекту. Несёт код и человекочитаемую причину."""

    __slots__ = ("code", "reason")

    def __init__(self, code: int, reason: str) -> None:
        self.code = code
        self.reason = reason

    def __repr__(self) -> str:  # для логов/отладки
        return f"NoData(code={self.code}, reason={self.reason!r})"


NO_DATA = NoData  # тип-алиас для аннотаций вызывающего кода


# --- Исключения --------------------------------------------------------------

class OmnicommError(Exception):
    """Базовая ошибка интеграции с Omnicomm (транспорт/протокол/код ошибки)."""


class OmnicommAuthError(OmnicommError):
    """Ошибка авторизации: неверные учётные данные либо невозможность получить токен."""


# --- Вспомогательное: разбор JWT ---------------------------------------------

def _decode_jwt_exp(token: str) -> Optional[int]:
    """Достать `exp` (UNIX UTC) из payload JWT без проверки подписи.

    Подпись нам не нужна — токен выдал доверенный контур; нам важен лишь срок,
    чтобы обновлять токен упреждающе. Возвращает None, если разобрать не вышло.
    """
    try:
        payload_b64 = token.split(".")[1]
        # base64url без паддинга — дополняем до кратного 4.
        padding = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + padding)
        exp = json.loads(raw).get("exp")
        return int(exp) if exp is not None else None
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        # Кривой/нестандартный токен — не падаем, просто не знаем срок.
        return None


# --- Клиент ------------------------------------------------------------------

class OmnicommClient:
    """REST-клиент Omnicomm Online.

    Управляет JWT-сессией и самоограничением по лимитам контура. Публичные
    методы-отчёты возвращают «сырые» данные; элементы списка по ТС, для которых
    Omnicomm вернул код «нет данных», заменяются маркером `NoData`.
    """

    def __init__(self, settings: Settings, *, session: Optional[requests.Session] = None) -> None:
        self._settings = settings
        self._session = session or requests.Session()

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._access_exp: Optional[int] = None      # UNIX UTC срока access-токена
        self._last_request_at: float = 0.0           # для паузы SLEEP_TIME между запросами
        # Общий на процесс лимитер ЗА АККАУНТ — все клиенты под одним логином делят
        # бюджет 180/мин (защита сервера Omnicomm при параллельном синке).
        from . import rate_limit
        self._limiter = rate_limit.get_limiter(
            getattr(settings, "login", "") or "", config.MAX_REQUESTS_PER_MINUTE)

    # --- URL и пауза ---------------------------------------------------------

    def _url(self, endpoint_key: str) -> str:
        """Полный URL по ключу из config.ENDPOINTS (не хардкодим пути)."""
        return self._settings.base_url.rstrip("/") + config.ENDPOINTS[endpoint_key]

    def _throttle(self) -> None:
        """Самоограничение по лимитам Omnicomm: глобальный token-bucket на аккаунт
        (≤MAX_REQUESTS_PER_MINUTE по всем потокам) + пер-клиентный пол SLEEP_TIME."""
        self._limiter.acquire()
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < config.SLEEP_TIME:
            time.sleep(config.SLEEP_TIME - elapsed)

    # --- Авторизация ---------------------------------------------------------

    def login(self) -> None:
        """Получить access/refresh JWT через POST /auth/login?jwt=1.

        Учётные данные берём из Settings (только ENV). До LOGIN_MAX_RETRIES
        попыток на ретраебельных статусах. Токены не логируем.
        """
        if not self._settings.login or not self._settings.password:
            raise OmnicommAuthError("Не заданы LOGIN/PASSWORD в окружении")

        url = self._url("login")
        body = {"login": self._settings.login, "password": self._settings.password}
        if self._settings.service:
            body["service"] = self._settings.service

        last_exc: Optional[Exception] = None
        for attempt in range(1, config.LOGIN_MAX_RETRIES + 1):
            try:
                self._throttle()
                resp = self._session.post(url, json=body, timeout=config.DEFAULT_TIMEOUT)
                self._last_request_at = time.monotonic()

                if resp.status_code in config.RETRY_STATUSES:
                    logger.warning("login: статус %s, попытка %s", resp.status_code, attempt)
                    self._backoff(attempt)
                    continue
                if resp.status_code == 401 or resp.status_code == 403:
                    # Неверные учётные данные — ретрай бессмысленен (и есть лимит 10/мин).
                    raise OmnicommAuthError(f"Авторизация отклонена (HTTP {resp.status_code})")
                resp.raise_for_status()

                data = resp.json()
                self._apply_error_action_for_auth(data)
                self._store_tokens(data)
                logger.info("login: токен получен, срок exp=%s", self._access_exp)
                return
            except OmnicommAuthError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                logger.warning("login: сетевая ошибка, попытка %s: %s", attempt, exc)
                self._backoff(attempt)

        raise OmnicommAuthError(f"Не удалось авторизоваться за {config.LOGIN_MAX_RETRIES} попыток") from last_exc

    def refresh(self) -> None:
        """Обновить access-токен через POST /auth/refresh.

        refresh-JWT уходит в заголовке `Authorization: JWT <refresh>`. До
        REFRESH_MAX_RETRIES попыток; при провале — fallback на полный login.
        """
        if not self._refresh_token:
            logger.info("refresh: нет refresh-токена — выполняю полный login")
            self.login()
            return

        url = self._url("refresh")
        headers = {"Authorization": f"JWT {self._refresh_token}"}

        last_exc: Optional[Exception] = None
        for attempt in range(1, config.REFRESH_MAX_RETRIES + 1):
            try:
                self._throttle()
                resp = self._session.post(url, headers=headers, timeout=config.DEFAULT_TIMEOUT)
                self._last_request_at = time.monotonic()

                if resp.status_code in config.RETRY_STATUSES:
                    logger.warning("refresh: статус %s, попытка %s", resp.status_code, attempt)
                    self._backoff(attempt)
                    continue
                if resp.status_code in (401, 403):
                    # refresh протух — нужен полный login.
                    logger.info("refresh: токен отклонён, перехожу на login")
                    self.login()
                    return
                resp.raise_for_status()

                data = resp.json()
                self._store_tokens(data)
                logger.info("refresh: токен обновлён, срок exp=%s", self._access_exp)
                return
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                logger.warning("refresh: ошибка, попытка %s: %s", attempt, exc)
                self._backoff(attempt)

        # Все попытки refresh исчерпаны — последняя надежда полный login.
        logger.warning("refresh: исчерпаны попытки (%s), fallback на login", last_exc)
        self.login()

    def _store_tokens(self, data: dict[str, Any]) -> None:
        """Извлечь access/refresh JWT из ответа и распарсить срок access-токена.

        Имена полей у контура варьируются — перебираем известные варианты.
        """
        access = _first_present(data, ("jwt", "access", "accessToken", "access_token", "token"))
        refresh = _first_present(data, ("refresh", "refreshToken", "refresh_token"))

        if not access:
            raise OmnicommAuthError("В ответе авторизации не найден access-JWT")

        self._access_token = access
        if refresh:
            self._refresh_token = refresh
        self._access_exp = _decode_jwt_exp(access)

    def _apply_error_action_for_auth(self, data: dict[str, Any]) -> None:
        """На авторизации код ошибки 1 (неверный логин/пароль) — это OmnicommAuthError."""
        code = _extract_error_code(data)
        if code is None:
            return
        action = _action_for(code)
        if action is ErrorAction.ABORT:
            _, ru, _ = config.OMNICOMM_ERRORS.get(code, ("", "ошибка авторизации", action))
            raise OmnicommAuthError(f"Авторизация: код {code} — {ru}")

    # --- Жизненный цикл токена ----------------------------------------------

    def _ensure_token(self) -> None:
        """Гарантировать валидный access-токен с упреждающим обновлением.

        Если токена нет — login. Если до `exp` осталось < SKEW_SECONDS — refresh.
        """
        if self._access_token is None:
            self.login()
            return
        if self._access_exp is not None:
            if self._access_exp - time.time() < config.SKEW_SECONDS:
                logger.info("Токен близок к истечению — упреждающий refresh")
                self.refresh()

    def _auth_header(self) -> dict[str, str]:
        """Заголовок авторизации строго в формате `JWT <token>` (с пробелом)."""
        return {"Authorization": f"JWT {self._access_token}"}

    # --- Бэкофф --------------------------------------------------------------

    @staticmethod
    def _backoff(attempt: int) -> None:
        """Экспоненциальная задержка между ретраями (база — SLEEP_TIME)."""
        time.sleep(config.SLEEP_TIME * (2 ** (attempt - 1)))

    # --- Базовый запрос ------------------------------------------------------

    def _request(self, method: str, endpoint_key: str, *,
                 params: Optional[dict[str, Any]] = None,
                 json_body: Optional[dict[str, Any]] = None,
                 timeout: Optional[int] = None,
                 max_retries: int = 3) -> Any:
        """Выполнить авторизованный запрос с ретраями и трактовкой кодов ошибок.

        Возвращает разобранный JSON (dict/list). Коды ошибок уровня всего ответа
        обрабатываются через таблицу config.OMNICOMM_ERRORS:
        OK→вернуть, REAUTH→reauth+повтор, ABORT→raise, MARK_NO_DATA→NoData,
        RETRY→ретрай затем лог.
        """
        url = self._url(endpoint_key)
        reauthed = False

        last_exc: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            self._ensure_token()
            try:
                self._throttle()
                resp = self._session.request(
                    method, url,
                    params=params, json=json_body,
                    headers=self._auth_header(),
                    timeout=timeout or config.DEFAULT_TIMEOUT,
                )
                self._last_request_at = time.monotonic()

                # 401/403 — токен протух/отклонён: один реавторизованный повтор.
                if resp.status_code in (401, 403):
                    if not reauthed:
                        logger.info("%s %s: HTTP %s — reauth", method, endpoint_key, resp.status_code)
                        self.refresh()
                        reauthed = True
                        continue
                    raise OmnicommAuthError(f"{endpoint_key}: повторный HTTP {resp.status_code} после reauth")

                if resp.status_code in config.RETRY_STATUSES:
                    logger.warning("%s %s: HTTP %s, попытка %s", method, endpoint_key, resp.status_code, attempt)
                    self._backoff(attempt)
                    continue

                resp.raise_for_status()
                data = resp.json()

                # Код ошибки Omnicomm на уровне всего ответа.
                result = self._handle_response_error(data, endpoint_key, reauthed)
                if result is _REAUTH_RETRY:
                    self.refresh()
                    reauthed = True
                    continue
                if result is _RETRY:
                    self._backoff(attempt)
                    continue
                return result  # data или NoData

            except OmnicommError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                logger.warning("%s %s: ошибка, попытка %s: %s", method, endpoint_key, attempt, exc)
                self._backoff(attempt)

        raise OmnicommError(f"{endpoint_key}: запрос не удался за {max_retries} попыток") from last_exc

    def _handle_response_error(self, data: Any, endpoint_key: str, reauthed: bool) -> Any:
        """Применить ErrorAction к коду ошибки в теле ответа.

        Возвращает сами данные (OK), маркер NoData (MARK_NO_DATA) либо
        внутренние сигналы `_REAUTH_RETRY` / `_RETRY` для цикла ретраев.
        """
        code = _extract_error_code(data) if isinstance(data, dict) else None
        if code is None:
            return data

        action = _action_for(code)
        _, ru, _ = config.OMNICOMM_ERRORS.get(code, ("", "неизвестный код", action))

        if action is ErrorAction.OK:
            return data
        if action is ErrorAction.MARK_NO_DATA:
            logger.info("%s: код %s (%s) — помечаю «нет данных»", endpoint_key, code, ru)
            return NoData(code, ru)
        if action is ErrorAction.REAUTH:
            if reauthed:
                raise OmnicommAuthError(f"{endpoint_key}: код {code} ({ru}) повторно после reauth")
            return _REAUTH_RETRY
        if action is ErrorAction.RETRY:
            logger.warning("%s: код %s (%s) — ретрай", endpoint_key, code, ru)
            return _RETRY
        # ABORT и всё прочее — прерываем.
        raise OmnicommError(f"{endpoint_key}: код {code} — {ru}")

    # --- Батчинг -------------------------------------------------------------

    def _batched(self, ids: list[str]) -> list[list[str]]:
        """Разбить список ID на пачки по MAX_IDS_PER_REQUEST (лимит контура)."""
        size = config.MAX_IDS_PER_REQUEST
        return [ids[i:i + size] for i in range(0, len(ids), size)]

    def _report_post(self, endpoint_key: str, vehicle_ids: list[str],
                     period: ReportPeriod, extra_body: Optional[dict] = None) -> list[dict]:
        """Сбор отчёта POST'ом: батчинг ТС (≤50) × нарезка периода (≤31 дня).

        Тело каждого запроса: {vehicleIds, timeBegin, timeEnd}. vehicleIds —
        terminal_id (целые). Возвращает «сырые» элементы ответа (items[]);
        агрегация по дням — на стороне data_loader. Элементы-`NoData`
        сохраняются маркером, чтобы ТС не потерялись молча.
        """
        # vehicleIds для consolidatedReport — целочисленные terminal_id.
        int_ids: list[int] = []
        for vid in vehicle_ids:
            try:
                int_ids.append(int(vid))
            except (TypeError, ValueError):
                logger.warning("Пропускаю нечисловой ID ТС для отчёта: %r", vid)

        out: list[dict] = []
        for batch in _chunks(int_ids, MAX_VEHICLES_PER_REPORT):
            for begin, end in _period_windows(period.start_ts, period.end_ts):
                body = {
                    PARAM_VEHICLE_IDS: batch,
                    PARAM_TIME_BEGIN: begin,
                    PARAM_TIME_END: end,
                }
                if extra_body:
                    body.update(extra_body)
                data = self._request("POST", endpoint_key, json_body=body,
                                     timeout=config.REPORT_TIMEOUT)
                if isinstance(data, NoData):
                    for vid in batch:
                        out.append({"vehicle_id": str(vid), "no_data": True,
                                    "code": data.code, "reason": data.reason})
                    continue
                out.extend(_as_list(data))
        return out

    # --- Публичные методы (возвращают «сырые» dict/list) ---------------------

    def get_vehicle_tree(self, timeout: int = None, max_retries: int = None) -> list[dict]:
        """Сырое дерево ТС: GET /ls/api/v2/tree/vehicle.

        Возвращает список корневых узлов как есть. ТС лежат вложенно в
        `children[].objects[]` — для плоского списка используйте `list_vehicles`.

        Тяжёлый эндпоинт (~2000 ТС): длинный таймаут + больше попыток с backoff —
        под нагрузкой копия отвечает медленно (деградация 24.06 уходила в таймаут 30с).
        `timeout`/`max_retries` можно переопределить (напр. health-проба хочет быстрый
        отказ: короткий таймаут, 1 попытка — не ждать 120с×4 на больной копии).
        """
        data = self._request("GET", "vehicle_tree",
                             timeout=timeout or config.TREE_TIMEOUT,
                             max_retries=max_retries or config.TREE_MAX_RETRIES)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [n for n in data if isinstance(n, dict)]
        return []

    def list_vehicles(self) -> list[dict]:
        """Плоский список всех ТС из дерева (рекурсивно по `children`).

        Каждый элемент — объект ТС с полями uuid/name/terminal_type/terminal_id.
        """
        return _flatten_vehicle_tree(self.get_vehicle_tree())

    def list_vehicle_ids(self) -> list[str]:
        """UUID всех ТС (fallback на terminal_id, если uuid отсутствует)."""
        ids: list[str] = []
        for v in self.list_vehicles():
            vid = v.get("uuid") or v.get("id") or v.get("terminal_id")
            if vid is not None:
                ids.append(str(vid))
        return ids

    def get_reports_catalog(self) -> list[dict]:
        """Каталог отчётов: GET /ls/api/v1/reports/ (id/code/group/objectTypes)."""
        return _as_list(self._request("GET", "reports_catalog"))

    def get_activity(self) -> list[dict]:
        """Активность терминалов: GET /ls/api/v1/activity/vehicles.

        Возвращает по терминалу время последних данных: [{id, dateID(ms), uuid}].
        Это «светофор» давности (Sensor Health, путь C). Фильтр по vehicleIds
        контур игнорирует — отдаёт весь доступный список.
        """
        return _as_list(self._request("GET", "activity_vehicles"))

    def get_vehicle_state(self, vehicle_id: str) -> dict:
        """Текущее состояние ТС: GET /ls/api/v1/vehicles/{id}/state.

        Мгновенные значения последнего пакета (раздел «Посл. данные» карточки):
        `voltage` (НАПРЯЖЕНИЕ БОРТСЕТИ), `currentSpeed`, `currentFuel`, `currentIgn`,
        `lastGPS{latitude,longitude}`, `lastGPSDir`, `lastGPSSat`, `address`,
        `lastDataDate`, `speedExceed`. Работает по terminal_id и по uuid.
        Лёгкий быстрый вызов (не отчёт) — годится для карточки ТС онлайн.
        """
        url = self._settings.base_url.rstrip("/") + f"/ls/api/v1/vehicles/{vehicle_id}/state"
        reauthed = False
        for _ in range(2):
            self._ensure_token()
            try:
                self._throttle()
                resp = self._session.get(url, headers=self._auth_header(),
                                         timeout=config.DEFAULT_TIMEOUT)
                self._last_request_at = time.monotonic()
                if resp.status_code in (401, 403) and not reauthed:
                    self.refresh()
                    reauthed = True
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {}
            except (requests.RequestException, ValueError) as exc:
                logger.warning("state %s: %s", vehicle_id, exc)
                return {}
        return {}

    def get_journal(self, terminal_id: str, period: ReportPeriod, *,
                    groups: Optional[list[str]] = None,
                    columns: Optional[list[str]] = None) -> list[dict]:
        """Отчёт «Журнал» (сырьё по узлам): POST /ls/api/v1/click/log.

        Возвращает пакеты терминала (строка на пакет) со всеми узлами и флагами
        наличия `*_PRESENT`: ДУТ (`LLS_ID/LLS_CODE/LLS_CODE_PRESENT/LLS_STATUS`),
        напряжение бортсети (`U_BOARD`), питание (`IS_EXTERNAL_SUPPLY_BROKEN`),
        CAN/OBD/UNIVAL/IQFREEZE, акселерометр. Это даёт сенсор-уровневую детекцию.

        ⚠️ ТЯЖЁЛЫЙ отчёт (все узлы каждого пакета) — звать ТОЧЕЧНО: один ТС,
        короткое окно (часы/1–2 суток), при нужде фильтровать `groups`/`columns`.
        `groups` ⊂ {GENERAL,NAVI,UNIVAL,CAN,OBD,MODBUS,LLS,IQFREEZE}.
        """
        body: dict[str, Any] = {"terminalId": int(terminal_id),
                                "dateFrom": period.start_ts,
                                "dateTo": period.end_ts}
        if groups:
            body["groups"] = list(groups)
        if columns:
            body["columns"] = list(columns)
        data = self._request("POST", "journal", json_body=body,
                             timeout=config.REPORT_TIMEOUT)
        if isinstance(data, dict):
            rows = data.get("columns")
            return rows if isinstance(rows, list) else []
        return _as_list(data)

    def list_geozones(self, *, page_size: int = 200) -> list[dict]:
        """Геозоны клиента: GET /api/service/geozones/geozones (rows[]).

        Ответ ПАГИНИРОВАН (`{total,page,pageSize,rows}`) — тянем ВСЕ страницы, иначе
        берётся лишь первая (напр. 200 из 401, включая внутренние геозоны ДЗО).
        Дедуп по id/uuid; страховочный кап на число страниц."""
        first = self._request("GET", "geozones_list",
                               params={"page": 1, "pageSize": page_size})
        if not isinstance(first, dict):
            return _as_list(first)
        rows = list(first.get("rows") or [])
        total = int(first.get("total") or len(rows))
        size = int(first.get("pageSize") or page_size) or page_size
        pages = (total + size - 1) // size
        for pg in range(2, min(pages, 100) + 1):     # кап 100 страниц (защита от цикла)
            more = self._request("GET", "geozones_list",
                                 params={"page": pg, "pageSize": size})
            batch = (more or {}).get("rows") if isinstance(more, dict) else None
            if not batch:
                break
            rows.extend(batch)
        # дедуп по id (иначе uuid), сохраняя порядок
        seen, out = set(), []
        for gz in rows:
            key = gz.get("id") or gz.get("uuid") or id(gz)
            if key in seen:
                continue
            seen.add(key)
            out.append(gz)
        return out

    def get_geozones_report(self, vehicle_ids: list[str], period: ReportPeriod
                            ) -> list[dict]:
        """Отчёт по геозонам: POST /ls/api/v1/reports/geozones.

        Визиты в геозоны: [{vehicleId, geozoneName, geoInfo{startDate,endDate,
        duration}, mv, fuel}]. Пусто, если геозоны не заведены/не посещались.
        """
        return self._report_post(
            "geozones_report", vehicle_ids, period,
            extra_body={"minDurationTime": config.GEOZONE_MIN_VISIT_MIN})

    def get_track(self, vehicle_id: str, period: ReportPeriod) -> list[dict]:
        """GPS-трек ТС: GET /ls/api/v1/reports/track/{id}?timeBegin&timeEnd.

        Возвращает список точек [{date,latitude,longitude,speed,satellitesCount}].
        Ошибки сети/прав не валят отчёт — возвращаем пустой список.
        """
        url = self._settings.base_url.rstrip("/") + f"/ls/api/v1/reports/track/{vehicle_id}"
        params = {"timeBegin": period.start_ts, "timeEnd": period.end_ts}
        reauthed = False
        for _ in range(2):
            self._ensure_token()
            try:
                self._throttle()
                resp = self._session.get(url, params=params,
                                         headers=self._auth_header(),
                                         timeout=config.REPORT_TIMEOUT)
                self._last_request_at = time.monotonic()
                if resp.status_code in (401, 403) and not reauthed:
                    self.refresh()
                    reauthed = True
                    continue
                resp.raise_for_status()
                data = resp.json()
                track = data.get("track", []) if isinstance(data, dict) else data
                return [p for p in (track or []) if isinstance(p, dict)]
            except (requests.RequestException, ValueError) as exc:
                logger.warning("track %s: %s", vehicle_id, exc)
                return []
        return []

    def get_consolidated_report(self, vehicle_ids: list[str],
                                period: ReportPeriod) -> list[dict]:
        """Сводный отчёт: POST /ls/api/v1/reports/consolidatedReport.

        Возвращает «сырые» items[] (по строке на ТС × сутки) с блоками
        mv/fuel — агрегаты пробега/расхода/моточасов/холостого хода. Тело:
        {vehicleIds:[terminal_id], timeBegin, timeEnd}; батчинг ≤50 ТС и
        нарезка периода ≤31 дня — внутри `_report_post`.
        """
        return self._report_post("consolidated_report", vehicle_ids, period)


# --- Внутренние сигналы цикла ретраев ----------------------------------------
# Уникальные объекты-маркеры (сравнение по идентичности), наружу не утекают.
_REAUTH_RETRY = object()
_RETRY = object()


# --- Модульные утилиты -------------------------------------------------------

def _action_for(code: int) -> ErrorAction:
    """Действие клиента по коду ошибки; неизвестный код трактуем как RETRY."""
    entry = config.OMNICOMM_ERRORS.get(code)
    return entry[2] if entry else ErrorAction.RETRY


def _extract_error_code(data: dict[str, Any]) -> Optional[int]:
    """Найти числовой код ошибки Omnicomm в теле ответа по известным ключам.

    Код 0 («ошибок нет») — валидное значение, поэтому отличаем «нет ключа»
    (None) от «есть 0».
    """
    for key in ERROR_CODE_KEYS:
        if key in data:
            val = data[key]
            if isinstance(val, bool):  # bool — подкласс int, отбрасываем
                continue
            if isinstance(val, int):
                return val
            if isinstance(val, str) and val.lstrip("-").isdigit():
                return int(val)
    return None


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    """Первое непустое строковое значение по списку возможных ключей."""
    for key in keys:
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _chunks(items: list, size: int) -> list[list]:
    """Разбить список на пачки длиной ≤ size."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def _period_windows(begin_ts: int, end_ts: int) -> list[tuple[int, int]]:
    """Нарезать [begin, end] на окна ≤ MAX_DAYS_PER_REPORT суток (лимит метода)."""
    if end_ts <= begin_ts:
        return [(begin_ts, end_ts)]
    span = MAX_DAYS_PER_REPORT * 86400
    windows: list[tuple[int, int]] = []
    cur = begin_ts
    while cur < end_ts:
        windows.append((cur, min(cur + span, end_ts)))
        cur += span
    return windows


def _flatten_vehicle_tree(nodes: list[dict]) -> list[dict]:
    """Рекурсивно собрать все ТС из дерева групп Omnicomm.

    Узел дерева: {id, name, objects:[...ТС...], children:[...узлы...]}. ТС лежат
    в `objects` на любом уровне; обходим всё дерево. Дубли по uuid отсекаем.
    """
    vehicles: list[dict] = []
    seen: set[str] = set()

    def walk(node: dict) -> None:
        for obj in node.get("objects") or []:
            if not isinstance(obj, dict):
                continue
            key = str(obj.get("uuid") or obj.get("id") or obj.get("terminal_id") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            vehicles.append(obj)
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    for root in nodes:
        if isinstance(root, dict):
            walk(root)
    return vehicles


def _as_list(data: Any) -> list[dict]:
    """Привести ответ к списку dict.

    Контур может вернуть как массив, так и объект-обёртку с полем `data`/`rows`.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "rows", "items", "result", "objects"):
            inner = data.get(key)
            if isinstance(inner, list):
                return inner
        return [data]
    return []


# --- Self-check (без реального сетевого вызова) -------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _settings = Settings.from_env(demo=True)
    _client = OmnicommClient(_settings)
    # Проверяем сборку URL и формат заголовка без обращения к сети.
    assert _client._url("login").endswith(config.ENDPOINTS["login"])
    assert _action_for(10) is ErrorAction.MARK_NO_DATA
    assert _extract_error_code({"error": 0}) == 0
    assert _extract_error_code({"nope": 1}) is None
    assert len(_client._batched(list(range(40))[0:40] and [str(i) for i in range(40)])) == 3
    print("OmnicommClient self-check OK:", _settings.base_url)
