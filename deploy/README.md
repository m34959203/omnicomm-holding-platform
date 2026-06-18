# Деплой и авто-перезапуск

Процессы держат код в памяти — после изменений их нужно перезапускать. Здесь —
средства, чтобы это было одной командой или автоматически при деплое.

## Быстро (любой хост)

```bash
deploy/run.sh        # перезапустить платформу + планировщик (идемпотентно)
deploy/redeploy.sh   # git pull + зависимости + run.sh — полный деплой после push
```

`run.sh` поднимает Streamlit (`:8501`, переопределяется `PORT=`) и демон
планировщика, подхватывает `.env` (SMTP и пр.), пишет логи в `logs/`.
Cloudflared-туннель не трогается (смотрит на порт). Для смены кода:
`git push` → на сервере `deploy/redeploy.sh`.

## Авто-перезапуск через systemd (рекомендуется для прода)

Юниты пользовательские (без root). Скопировать и включить:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/omnicomm-*.service ~/.config/systemd/user/
loginctl enable-linger "$USER"          # чтобы работало без активной сессии
systemctl --user daemon-reload
systemctl --user enable --now omnicomm-report omnicomm-scheduler
```

`Restart=always` — процессы сами поднимаются после падения/перезагрузки.
Обновление кода:

```bash
git pull && systemctl --user restart omnicomm-report omnicomm-scheduler
```

Статусы/логи:

```bash
systemctl --user status omnicomm-report omnicomm-scheduler
journalctl --user -u omnicomm-scheduler -f
```

> Если `systemctl --user` недоступен на хосте — используйте `deploy/run.sh`
> (через cron `@reboot` или supervisor).
