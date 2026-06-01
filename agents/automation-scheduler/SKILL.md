---
name: automation-scheduler
description: Агент для настройки регулярных задач (расписание, cron). Позволяет запускать другие скиллы или скрипты по расписанию (каждое утро, раз в час, по пятницам).
license: MIT
metadata:
  author: kali-team
  version: "1.0"
allowed-tools: Read Write
---

# Automation Scheduler

Этот агент управляет расписанием задач. Используй его, когда пользователь просит делать что-то регулярно: "каждое утро", "раз в час", "по выходным".
Этот агент регистрирует задачу в ядре KALI.

## Script
Используй скрипт `scripts/schedule.py` для добавления новой задачи.

Пример использования:
```bash
python scripts/schedule.py --cron "0 8 * * *" --action "telegram_message" --payload "Доброе утро!"
```
