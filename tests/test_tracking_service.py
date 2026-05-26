from datetime import date
from types import SimpleNamespace

from app.services import study_tracking
from app.services.tracking_service import (
    ParticipantTarget,
    TrackingService,
    build_find_offer_month_rows,
    first_find_offer_month_date,
    is_penultimate_day_of_month,
    latest_tracker_date,
    next_find_offer_append_row,
    next_target_month_after_completed_block,
)


def test_is_penultimate_day_of_month():
    assert is_penultimate_day_of_month(date(2026, 2, 27))
    assert is_penultimate_day_of_month(date(2026, 5, 30))
    assert not is_penultimate_day_of_month(date(2026, 5, 29))
    assert not is_penultimate_day_of_month(date(2026, 5, 31))


def test_first_find_offer_month_date_starts_from_monday_of_first_month_week():
    assert first_find_offer_month_date(2026, 2) == date(2026, 1, 26)
    assert first_find_offer_month_date(2026, 6) == date(2026, 6, 1)


def test_build_find_offer_month_rows_adds_week_and_month_statuses():
    participants = [ParticipantTarget(name="Kostya", weekly_hours=25, monthly_hours=100)]

    rows = build_find_offer_month_rows(2026, 2, participants, start_sheet_row=40)

    assert rows[0] == ["Mon, Jan 26", "", 0, False, False, False]
    assert rows[7][0] == "Week status ➜"
    assert rows[7][1].startswith("=SPARKLINE({SUM(C40:C46),")
    assert rows[7][2] == '=SUM(C40:C46) & "/" & 25'
    assert rows[8] == ["", "", "", "", "", ""]
    assert rows[-8][0] == "Month status ➜"
    assert rows[-8][1].startswith("=SPARKLINE({SUM(C40:C46, C49:C55")
    assert rows[-8][2] == '=SUM(C40:C46, C49:C55, C58:C64, C67:C73, C76:C82) & "/" & 100'
    assert rows[-8][3:6] == [False, False, False]
    assert rows[-7:] == [["", "", "", "", "", ""] for _ in range(7)]


def test_build_find_offer_month_rows_matches_sheet_columns_for_all_participants():
    participants = [
        ParticipantTarget(name="Vania", weekly_hours=25, monthly_hours=100),
        ParticipantTarget(name="Kostya", weekly_hours=25, monthly_hours=100),
        ParticipantTarget(name="Vlad", weekly_hours=25, monthly_hours=100),
        ParticipantTarget(name="Kostya2", weekly_hours=25, monthly_hours=100),
    ]

    rows = build_find_offer_month_rows(2026, 6, participants, start_sheet_row=176)

    assert len(rows) == 53
    assert len(rows[0]) == 24
    assert rows[0] == [
        "Mon, Jun 1",
        "",
        0,
        False,
        False,
        False,
        "",
        "",
        0,
        False,
        False,
        False,
        "",
        "",
        0,
        False,
        False,
        False,
        "",
        "",
        0,
        False,
        False,
        False,
    ]
    assert rows[7][2] == '=SUM(C176:C182) & "/" & 25'
    assert rows[7][8] == '=SUM(I176:I182) & "/" & 25'
    assert rows[7][14] == '=SUM(O176:O182) & "/" & 25'
    assert rows[7][20] == '=SUM(U176:U182) & "/" & 25'
    assert rows[7][1].startswith("=SPARKLINE({SUM(C176:C182),")
    assert rows[-8][13].startswith("=SPARKLINE({SUM(O176:O182, O185:O191")
    assert rows[-8][2] == (
        '=SUM(C176:C182, C185:C191, C194:C200, C203:C209, C212:C218) & "/" & 100'
    )
    assert rows[-8][8] == (
        '=SUM(I176:I182, I185:I191, I194:I200, I203:I209, I212:I218) & "/" & 100'
    )
    assert rows[-8][14] == (
        '=SUM(O176:O182, O185:O191, O194:O200, O203:O209, O212:O218) & "/" & 100'
    )
    assert rows[-8][20] == (
        '=SUM(U176:U182, U185:U191, U194:U200, U203:U209, U212:U218) & "/" & 100'
    )
    assert rows[7][3:6] == [False, False, False]
    assert rows[-8][3:6] == [False, False, False]
    assert rows[-8][9:12] == [False, False, False]
    assert rows[-8][15:18] == [False, False, False]
    assert rows[-8][21:24] == [False, False, False]


def test_latest_tracker_date_parses_sheet_dates():
    assert latest_tracker_date({"Sun, Apr 26", "Mon, Jan 5", "Month status ➜"}, 2026) == date(
        2026, 4, 26
    )


def test_next_target_month_after_completed_block_handles_week_overlap():
    assert next_target_month_after_completed_block(date(2026, 2, 1)) == (2026, 2)
    assert next_target_month_after_completed_block(date(2026, 4, 26)) == (2026, 5)


def test_next_find_offer_append_row_skips_empty_month_status_block_tail():
    values = ["Mon, May 25", "Week status ➜", "", "Month status ➜"]

    assert next_find_offer_append_row(values) == 12


def test_study_tracking_row_lookup_returns_none_when_date_is_missing():
    class Sheet:
        def find(self, _query):
            return None

    assert study_tracking.get_row_index(Sheet()) is None


async def test_update_study_data_runs_sheet_update(monkeypatch):
    updates: list[tuple[int, int, str]] = []

    class Cell:
        row = 12

    class Sheet:
        def find(self, _query):
            return Cell()

        def update_cell(self, row: int, col: int, value: str) -> None:
            updates.append((row, col, value))

    monkeypatch.setattr(study_tracking, "get_sheet", lambda: Sheet())

    row = await study_tracking.update_study_data(
        "fesenko.kostya576@gmail.com",
        "Read docs",
        1.5,
    )

    assert row == 12
    assert updates == [(12, 10, "Read docs"), (12, 11, "1.5")]


async def test_tracking_notifications_use_socket_user_room(monkeypatch):
    emitted: list[tuple[str, dict, str]] = []

    class Scalars:
        def all(self):
            return [7, 8]

    class Result:
        def scalars(self):
            return Scalars()

    class Db:
        async def execute(self, _query):
            return Result()

    async def fake_update_study_data(**_kwargs):
        return 42

    async def fake_emit(event, payload, room):
        emitted.append((event, payload, room))

    monkeypatch.setattr("app.services.tracking_service.update_study_data", fake_update_study_data)
    monkeypatch.setattr("app.services.tracking_service.sio.emit", fake_emit)

    user = SimpleNamespace(id=1, email="fesenko.kostya576@gmail.com")
    data = SimpleNamespace(activity="Read docs", hours_spent=1.5)

    response = await TrackingService(Db()).add_study_tracking(data, user)

    assert response == {"message": "Data added to Google Sheet"}
    assert [room for _, _, room in emitted] == ["user_7", "user_8"]
    assert all(event == "study_record.created" for event, _, _ in emitted)
