"""Отправка готового отчёта по e-mail для scheduled-рассылки (P-product).

Все параметры SMTP — из переменных окружения (секреты не в коде):
    SMTP_HOST, SMTP_PORT (по умолчанию 587), SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM (по умолчанию = SMTP_USER), SMTP_TLS ("1"/"0", по умолчанию 1).

Если SMTP не сконфигурирован — `send_report` возвращает False и НЕ падает
(scheduled-запуск всё равно оставит файлы в outdir).
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger(__name__)

_MIME = {
    ".pptx": ("application",
              "vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".xlsx": ("application",
              "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".html": ("text", "html"),
    ".pdf": ("application", "pdf"),
}


def smtp_configured() -> bool:
    """True, если заданы минимально необходимые SMTP-переменные окружения."""
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER")
                and os.getenv("SMTP_PASSWORD"))


def send_report(to: str, subject: str, body: str, attachments: list[str]) -> bool:
    """Отправить письмо с вложениями. Возвращает True при успехе.

    Никогда не бросает наружу сетевые ошибки — логирует и возвращает False,
    чтобы не ронять scheduled-конвейер.
    """
    if not smtp_configured():
        logger.warning("SMTP не настроен (SMTP_HOST/USER/PASSWORD) — письмо не отправлено.")
        return False

    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    sender = os.getenv("SMTP_FROM", user)
    use_tls = os.getenv("SMTP_TLS", "1") != "0"

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    for path in attachments:
        if not path or not os.path.exists(path):
            continue
        maintype, subtype = _MIME.get(os.path.splitext(path)[1].lower(),
                                      ("application", "octet-stream"))
        with open(path, "rb") as fh:
            msg.add_attachment(fh.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(path))

    try:
        with smtplib.SMTP(host, port, timeout=60) as srv:
            if use_tls:
                srv.starttls(context=ssl.create_default_context())
            srv.login(user, password)
            srv.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("Не удалось отправить письмо на %s: %s", to, exc)
        return False
    logger.info("Отчёт отправлен на %s (вложений: %d)", to, len(attachments))
    return True
