# Frontend API contract

## Authentication

REST endpoints use `Authorization: Bearer <access_token>`.

Socket.IO connections must pass the same access token in auth:

```json
{
  "token": "<access_token>"
}
```

The backend joins the socket to `user_<id>` after validating the token.

## Reminder events

### `reminder.due`

Emitted when a reminder should be shown to the current user.

```json
{
  "id": 123,
  "form_id": 45,
  "title": "How long did you study?",
  "payload": {"activity": "study"},
  "retry_delay_seconds": 3600,
  "delivery_retry_delay_seconds": 900,
  "skip_count": 0,
  "delivery_count": 1,
  "next_run_at": "2026-05-22T12:30:00+00:00"
}
```

After showing it, the frontend should call one of:

- `POST /reminders/{id}/complete`
- `POST /reminders/{id}/skip`
- `POST /reminders/{id}/cancel`

If the app was offline, use `GET /reminders/current` on startup to fetch missed due reminders.

## Forms

- `GET /forms?include_archived=false`
- `POST /forms`
- `GET /forms/{form_id}`
- `PUT /forms/{form_id}`
- `PATCH /forms/{form_id}/reminder-settings`
- `POST /forms/{form_id}/archive`
- `POST /forms/{form_id}/restore`
- `DELETE /forms/{form_id}` archives the form for backwards compatibility.

Supported schedule strings:

- `@every 30m`
- `@every 1h`
- `@every 1d`
- `*/15 * * * *`
- `09:00`
- `daily 09:00`
- `weekdays 09:00`
- `weekends 10:00`
- `mon,wed,fri 18:30`

Time-of-day schedules are evaluated in the user's `timezone`.

`form_structure` is validated. The minimum shape is:

```json
{
  "fields": [
    {
      "name": "hours",
      "label": "Hours",
      "type": "number",
      "required": true,
      "min": 0,
      "max": 12
    }
  ]
}
```

Supported field types:

- `text`
- `number`
- `select`
- `checkbox`
- `boolean`
- `date`
- `time`

Answers are validated against the form structure. Unknown fields, missing required
fields, invalid select options, and out-of-range numeric values return `422`.

## Reminders

- `GET /reminders/current`
- `GET /reminders?status=pending&status=skipped&form_id=45&due_only=false&limit=100&offset=0`
- `POST /reminders`
- `POST /reminders/{id}/skip`
- `POST /reminders/{id}/complete`
- `POST /reminders/{id}/cancel`

`GET /reminders/current` is the startup/offline recovery endpoint for the frontend.

## Answers

- `POST /forms/{form_id}/answers`
- `GET /forms/{form_id}/answers?created_from=...&created_to=...&limit=100&offset=0`
- `GET /forms/{form_id}/answers/stats`

Posting an answer completes active reminders for that form and returns
`completed_reminder_ids`.

## User Profile

`PATCH /auth/me` supports:

- `first_name`
- `last_name`
- `phone`
- `birth_date`
- `gender`
- `avatar_url`
- `timezone`
- `notification_preferences`

Notification preferences currently understood by the backend:

```json
{
  "realtime": true,
  "email": false,
  "push": false
}
```

When `push` is enabled, set `push_token`. The backend sends push notifications
through `PUSH_WEBHOOK_URL` if configured.

## Health and Operations

- `GET /health/live`
- `GET /health/ready`
- `GET /admin/overview`
- `GET /admin/users`
- `GET /admin/reminders/failed`

Admin endpoints require the `admin` or `manager` role.
