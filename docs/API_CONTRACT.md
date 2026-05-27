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
- `DELETE /forms/{form_id}`

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

`form_structure` is stored as raw JSON object data. The backend does not inspect
or validate the component structure inside it.

```json
{
  "any_random_key": "random_value",
  "components": []
}
```

`schedule_crons` is stored as a JSON array of strings. `DELETE /forms/{form_id}`
physically deletes the form; `/archive` and `/restore` remain available for
soft-archive workflows. Submitted answers are also stored as raw JSON and are not
validated against `form_structure`.

## Reminders

- `GET /reminders/current`
- `GET /reminders?status=pending&status=skipped&form_id=45&due_only=false&limit=100&offset=0`
- `POST /reminders`
- `POST /reminders/{id}/skip`
- `POST /reminders/{id}/complete`
- `POST /reminders/{id}/cancel`

`GET /reminders/current` is the startup/offline recovery endpoint for the frontend.

## Answers

- `POST /answers`
- `POST /forms/{form_id}/answers`
- `GET /forms/{form_id}/answers?created_from=...&created_to=...&limit=100&offset=0`
- `GET /forms/{form_id}/answers/stats`
- `POST /form-groups/{group_id}/answers`

`POST /answers` accepts `form_id` and arbitrary JSON object data in
`answers_data`, then returns `201 Created` with `answer_id`.

The legacy `POST /forms/{form_id}/answers` route is still available. Posting an
answer completes active reminders for that form and returns
`completed_reminder_ids`.

`POST /form-groups/{group_id}/answers` accepts one raw JSON answer object per
form in the group and stores them under one `submission_id`.

```json
{
  "answers": [
    { "form_id": 5, "answers_data": { "amount": 42.5 } },
    { "form_id": 6, "answers_data": { "mood": "good" } }
  ]
}
```

## Form Groups

- `POST /form-groups`
- `GET /form-groups`
- `GET /form-groups/{group_id}`
- `PUT /form-groups/{group_id}`
- `POST /form-groups/{group_id}/archive`
- `POST /form-groups/{group_id}/restore`

Groups let one reminder ask several forms at once. A group owns ordering through
`form_ids`, has its own schedule/reminder settings, and reminders can target it
with `form_group_id`.

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
