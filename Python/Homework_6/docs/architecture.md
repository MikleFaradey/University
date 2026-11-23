# Архитектура и гарантии целостности

## Соответствие контрактам

Система реализует три независимо запускаемых сервиса: Task `:8001`, Notification `:8002`, Audit `:8003`. Авторизация и справочник сотрудников/отделов расположены внутри Task Service, поэтому отдельного четвёртого контейнера не требуется. Код организован по слоям `api`, `services`, `repositories`, `schemas`. Внешний клиент взаимодействует через HTTP/JSON и OpenAPI; межсервисная доставка событий — HTTP `POST /events`.

## Данные и целостность

- SQLite хранится на отдельных томах `task_data`, `notification_data`, `audit_data`. Ни один сервис не подключает том другого.
- Таблицы задач, комментариев, отделов, сотрудников и outbox содержатся только в БД Task Service.
- Сохранение задачи и событий для двух получателей выполняется одной SQLite-транзакцией `BEGIN IMMEDIATE`.
- Outbox отслеживает успешную доставку в Notification и Audit отдельно. Сбой сети не теряет событие; повторная доставка зависит от доступности получателя.
- Notification и Audit реализуют приём `event_id` с `UNIQUE` для исключения повторов.
- Аудит сохраняет `old_value` и `new_value` (JSON), `action`, `actor`, `task_id`, `timestamp`. Триггеры запрещают `UPDATE` и `DELETE` на уровне базы.
- SQLite на данном этапе рассчитана на один процесс каждого сервиса и не предполагает одновременную работу нескольких реплик с общей базой. Для масштабирования в нескольких экземплярах потребуется внешняя СУБД и координированный outbox worker.

## Правила изменения задачи

- Статусы `new → in_progress → on_review → done`; также `in_progress/on_review → rejected` с обязательным комментарием.
- Передача в другой отдел из `new/in_progress/on_review` возвращает статус в `new`.
- `in_progress` ставит сотрудник принимающего отдела; `on_review` — исполнитель или менеджер принимающего отдела; `done` — автор или менеджер инициатора.
- Закрытые задачи не редактируются и не переназначаются; ошибки переходов возвращают HTTP 409.
- При изменении записывается номер версии `version` и `updated_at`; операции записи сериализуются через `BEGIN IMMEDIATE`.

## Поток событий

```mermaid
sequenceDiagram
    participant U as Client (JWT)
    participant T as Task Service
    participant DB as Task DB + outbox
    participant N as Notification
    participant A as Audit
    U->>T: POST /tasks
    T->>DB: BEGIN IMMEDIATE; INSERT task; 2 INSERT outbox; COMMIT
    T->>N: POST /events (X-Service-Token)
    N-->>T: 202 accepted / duplicate
    T->>DB: mark delivered (notification)
    T->>A: POST /events
    A--xT: timeout / 503
    T->>DB: attempts++, last_error; audit pending
    T-->>U: 201 task created
    Note over T,DB: Retry worker or POST /outbox/retry
    T->>A: POST /events (same event_id)
    A-->>T: 202 accepted / duplicate
    T->>DB: mark delivered (audit)
```

## Конфигурация и безопасность

`JWT_SECRET` и `SERVICE_API_KEY` должны быть независимыми длинными случайными секретами. JWT подписан HS256 и содержит идентификатор сотрудника, роль, отдел и срок действия. Task API дополнительно перечитывает активность и роль сотрудника из своей SQLite-базы. Notification и Audit доверяют подписи JWT до срока истечения, поэтому деактивация пользователя не отзываёт уже выданный JWT в этих двух сервисах немедленно. Для продакшен-развёртывания также необходимы TLS, централизованный отзыв токенов и ограничение доступа к внутренним HTTP API.

При настройке `OUTBOX_RETRY_SECONDS=0` фоновая отправка отключена; ручной вызов `POST /outbox/retry` остаётся доступен. Параметры портов и адресов сервисов должны соответствовать друг другу в `.env`.
