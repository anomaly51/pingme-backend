import asyncio
import calendar
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import User
from app.schemas.study_schemas import FindOfferExtendRequest, StudyTrackingCreate
from app.services.study_tracking import confirm_study_data, update_study_data
from app.sockets import sio
from db.database import get_db


GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
PARTICIPANT_GROUP_WIDTH = 6
PARTICIPANT_DATA_WIDTH = 5
TRACKER_COLUMN_COUNT = 24
SEPARATOR_ROW_HEIGHT_PX = 3
MONTH_STATUS_BLOCK_HEIGHT = 8
CHECKBOX_COLUMN_INDEXES = (3, 4, 5, 9, 10, 11, 15, 16, 17, 21, 22, 23)
TRACKER_BLUE = {"red": 0.043137256, "green": 0.3254902, "blue": 0.5803922}
WHITE = {"red": 1, "green": 1, "blue": 1}
PROGRESS_COLORS = (
    '"#CC0000", "#D31200", "#DA2400", "#E13600", "#E84800", '
    '"#EF5A00", "#F66C00", "#FD7E00", "#FF8A00", "#FF9600", '
    '"#FFA200", "#FFAE00", "#FFBA00", "#FFC600", "#FFD200", '
    '"#E6D400", "#CCD600", "#B3D800", "#99DA00", "#80DC00", '
    '"#66DE00", "#4DE000", "#33E200", "#1AE400", "#008000"'
)
logger = logging.getLogger(__name__)
EMAIL_TO_NAME = {
    "fesenko.kostya576@gmail.com": "Kostya",
    "vania@gmail.com": "Vania",
    "vlad@gmail.com": "Vlad",
    "kostya2@gmail.com": "Kostya2",
}


@dataclass(frozen=True)
class ParticipantTarget:
    name: str
    weekly_hours: int
    monthly_hours: int


DEFAULT_PARTICIPANT_TARGETS = (
    ParticipantTarget(name="Vania", weekly_hours=25, monthly_hours=100),
    ParticipantTarget(name="Kostya", weekly_hours=25, monthly_hours=100),
    ParticipantTarget(name="Vlad", weekly_hours=25, monthly_hours=100),
    ParticipantTarget(name="Kostya2", weekly_hours=25, monthly_hours=100),
)


class TrackingService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def add_study_tracking(self, data: StudyTrackingCreate, user: User) -> dict[str, Any]:
        row_idx = await update_study_data(
            email=user.email, activity=data.activity, hours=data.hours_spent
        )

        manager_query = select(User.id).where(User.roles.contains(["manager"]), User.id != user.id)
        result = await self.db.execute(manager_query)
        manager_ids = result.scalars().all()

        student_name = user.email.split("@")[0].capitalize()
        payload = {
            "student_name": student_name,
            "activity": data.activity,
            "hours": data.hours_spent,
            "sheet_row_id": row_idx,
        }

        for m_id in manager_ids:
            await sio.emit("study_record.created", payload, room=f"user_{m_id}")

        return {"message": "Data added to Google Sheet"}

    async def confirm_study(self, confirm_name: str, user: User) -> dict[str, Any]:
        manager_name = user.email.split("@")[0].capitalize()

        await confirm_study_data(student_name=confirm_name, manager_name=manager_name)

        return {"message": f"{manager_name} checked for {confirm_name}"}

    async def extend_find_offer_next_month(
        self,
        data: FindOfferExtendRequest | None = None,
    ) -> dict[str, Any]:
        request = data or FindOfferExtendRequest()
        today = request.today or date.today()
        target_year, target_month = self._next_month(today.year, today.month)

        spreadsheet_id = request.spreadsheet_id or os.getenv("FIND_OFFER_SPREADSHEET_ID")
        worksheet_name = request.worksheet_name or os.getenv("FIND_OFFER_WORKSHEET_NAME")
        if not spreadsheet_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="FIND_OFFER_SPREADSHEET_ID is not configured",
            )

        result = await asyncio.to_thread(
            self._append_find_offer_rows,
            spreadsheet_id,
            worksheet_name,
            request.today,
            target_year,
            target_month,
            self._participant_targets(),
        )
        return {
            "message": "Find offer tracker extended",
            "year": target_year,
            "month": target_month,
            **result,
        }

    async def auto_extend_find_offer_if_needed(self, today: date | None = None) -> dict[str, Any]:
        check_date = today or date.today()
        if not is_penultimate_day_of_month(check_date):
            return {"extended": False, "reason": "not_penultimate_day"}

        if not os.getenv("FIND_OFFER_SPREADSHEET_ID"):
            return {"extended": False, "reason": "spreadsheet_not_configured"}

        result = await self.extend_find_offer_next_month()
        return {"extended": True, **result}

    def _append_find_offer_rows(
        self,
        spreadsheet_id: str,
        worksheet_name: str | None,
        requested_date: date | None,
        year: int,
        month: int,
        participants: list[ParticipantTarget],
    ) -> dict[str, Any]:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Google Sheets dependencies are not installed",
            ) from exc

        credentials_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "google_services.json")
        try:
            credentials = Credentials.from_service_account_file(
                credentials_path,
                scopes=GOOGLE_SCOPES,
            )
            client = gspread.authorize(credentials)
            spreadsheet = client.open_by_key(spreadsheet_id)
            worksheet = (
                spreadsheet.worksheet(worksheet_name) if worksheet_name else spreadsheet.sheet1
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not open Find offer spreadsheet: {exc}",
            ) from exc

        existing_dates = set(worksheet.col_values(1))
        if requested_date is None:
            latest_date = latest_tracker_date(existing_dates, fallback_year=year)
            year, month = next_target_month_after_completed_block(latest_date)

        first_generated_date = first_find_offer_month_date(year, month)
        if format_tracker_date(first_generated_date) in existing_dates:
            return {"extended": False, "reason": "month_already_exists", "rows_added": 0}

        start_row = next_find_offer_append_row(worksheet.col_values(1))
        rows = build_find_offer_month_rows(year, month, participants, start_sheet_row=start_row)
        self._insert_formatted_rows(worksheet, start_row, len(rows))
        worksheet.update(
            values=rows,
            range_name=f"A{start_row}:X{start_row + len(rows) - 1}",
            value_input_option="USER_ENTERED",
        )
        self._squash_separator_rows(worksheet, start_row, len(rows))
        return {
            "extended": True,
            "year": year,
            "month": month,
            "rows_added": len(rows),
            "start_row": start_row,
        }

    def _insert_formatted_rows(self, worksheet: Any, start_row: int, row_count: int) -> None:
        sheet_id = worksheet.id
        start_index = start_row - 1
        week_template_start = self._find_latest_week_template_start(worksheet)
        month_template_start = self._find_latest_month_template_start(worksheet)
        week_count = (row_count - MONTH_STATUS_BLOCK_HEIGHT) // 9
        requests: list[dict[str, Any]] = [
            {
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start_index,
                        "endIndex": start_index + row_count,
                    },
                    "inheritFromBefore": True,
                }
            }
        ]

        for week_index in range(week_count):
            target_start = start_index + week_index * 9
            for paste_type in (
                "PASTE_FORMAT",
                "PASTE_DATA_VALIDATION",
            ):
                requests.append(
                    {
                        "copyPaste": {
                            "source": {
                                "sheetId": sheet_id,
                                "startRowIndex": week_template_start - 1,
                                "endRowIndex": week_template_start - 1 + 9,
                                "startColumnIndex": 0,
                                "endColumnIndex": TRACKER_COLUMN_COUNT,
                            },
                            "destination": {
                                "sheetId": sheet_id,
                                "startRowIndex": target_start,
                                "endRowIndex": target_start + 9,
                                "startColumnIndex": 0,
                                "endColumnIndex": TRACKER_COLUMN_COUNT,
                            },
                            "pasteType": paste_type,
                            "pasteOrientation": "NORMAL",
                        }
                    }
                )

        month_target_start = start_index + row_count - MONTH_STATUS_BLOCK_HEIGHT
        for paste_type in (
            "PASTE_FORMAT",
            "PASTE_DATA_VALIDATION",
        ):
            requests.append(
                {
                    "copyPaste": {
                        "source": {
                            "sheetId": sheet_id,
                            "startRowIndex": month_template_start - 1,
                            "endRowIndex": month_template_start - 1 + MONTH_STATUS_BLOCK_HEIGHT,
                            "startColumnIndex": 0,
                            "endColumnIndex": TRACKER_COLUMN_COUNT,
                        },
                        "destination": {
                            "sheetId": sheet_id,
                            "startRowIndex": month_target_start,
                            "endRowIndex": month_target_start + MONTH_STATUS_BLOCK_HEIGHT,
                            "startColumnIndex": 0,
                            "endColumnIndex": TRACKER_COLUMN_COUNT,
                        },
                        "pasteType": paste_type,
                        "pasteOrientation": "NORMAL",
                    }
                }
            )
        requests.extend(
            month_block_merge_requests(
                worksheet,
                month_template_start,
                month_target_start + 1,
            )
        )
        requests.extend(month_block_checkbox_style_requests(sheet_id, month_target_start + 1))
        worksheet.spreadsheet.batch_update({"requests": requests})

    @staticmethod
    def _squash_separator_rows(worksheet: Any, start_row: int, row_count: int) -> None:
        sheet_id = worksheet.id
        week_count = (row_count - MONTH_STATUS_BLOCK_HEIGHT) // 9
        separator_rows = [start_row + 8 + week_index * 9 for week_index in range(week_count)]
        worksheet.spreadsheet.batch_update(
            {
                "requests": [
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": separator_row - 1,
                                "endIndex": separator_row,
                            },
                            "properties": {"pixelSize": SEPARATOR_ROW_HEIGHT_PX},
                            "fields": "pixelSize",
                        }
                    }
                    for separator_row in separator_rows
                ]
            }
        )

    @staticmethod
    def _find_latest_week_template_start(worksheet: Any) -> int:
        values = worksheet.col_values(1)
        for row_number in range(len(values), 8, -1):
            if values[row_number - 1] != "Week status ➜":
                continue

            possible_start = row_number - 7
            if possible_start > 0 and values[possible_start - 1].startswith("Mon, "):
                return possible_start

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not find Find offer week template",
        )

    @staticmethod
    def _find_latest_month_template_start(worksheet: Any) -> int:
        values = worksheet.col_values(1)
        for row_number in range(len(values), 0, -1):
            if values[row_number - 1] == "Month status ➜":
                return row_number

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not find Find offer month template",
        )

    @staticmethod
    def _participant_targets() -> list[ParticipantTarget]:
        raw_targets = os.getenv("FIND_OFFER_TARGETS_JSON")
        if raw_targets:
            try:
                parsed = json.loads(raw_targets)
                return [
                    ParticipantTarget(
                        name=str(item["name"]),
                        weekly_hours=int(item.get("weekly_hours", 25)),
                        monthly_hours=int(item.get("monthly_hours", 100)),
                    )
                    for item in parsed
                ]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="FIND_OFFER_TARGETS_JSON has invalid format",
                ) from exc

        return list(DEFAULT_PARTICIPANT_TARGETS)

    @staticmethod
    def _next_month(year: int, month: int) -> tuple[int, int]:
        if month == 12:
            return year + 1, 1
        return year, month + 1


def is_penultimate_day_of_month(day: date) -> bool:
    _, days_in_month = calendar.monthrange(day.year, day.month)
    return day.day == days_in_month - 1


def build_find_offer_month_rows(
    year: int,
    month: int,
    participants: list[ParticipantTarget],
    start_sheet_row: int = 1,
) -> list[list[Any]]:
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    current_day = first_find_offer_month_date(year, month)

    rows: list[list[Any]] = []
    month_week_ranges: list[tuple[int, int]] = []
    month_week_status_rows: list[int] = []
    current_sheet_row = start_sheet_row

    while current_day <= last_day:
        week_start_row = current_sheet_row
        for _ in range(7):
            rows.append(_date_row(current_day, participants))
            current_sheet_row += 1
            current_day += timedelta(days=1)

        week_end_row = current_sheet_row - 1
        status_row = current_sheet_row
        rows.append(_week_status_row(week_start_row, week_end_row, status_row, participants))
        month_week_ranges.append((week_start_row, week_end_row))
        month_week_status_rows.append(status_row)
        current_sheet_row += 1
        rows.append([""] * tracker_column_count(len(participants)))
        current_sheet_row += 1

    rows.append(_month_status_row(month_week_ranges, month_week_status_rows, participants))
    for _ in range(MONTH_STATUS_BLOCK_HEIGHT - 1):
        rows.append([""] * tracker_column_count(len(participants)))
    return rows


def first_find_offer_month_date(year: int, month: int) -> date:
    first_day = date(year, month, 1)
    return first_day - timedelta(days=first_day.weekday())


def verification_column_indexes(participant_count: int) -> list[int]:
    return [
        1 + participant_index * PARTICIPANT_GROUP_WIDTH + 2
        for participant_index in range(participant_count)
    ]


def hour_column_indexes(participant_count: int) -> list[int]:
    return [
        2 + participant_index * PARTICIPANT_GROUP_WIDTH
        for participant_index in range(participant_count)
    ]


def _date_row(day: date, participants: list[ParticipantTarget]) -> list[Any]:
    row: list[Any] = [format_tracker_date(day)]
    for participant_index, _participant in enumerate(participants):
        row.extend(["", 0, False, False, False])
        if participant_index != len(participants) - 1:
            row.append("")
    return row


def _week_status_row(
    week_start_row: int,
    week_end_row: int,
    status_row: int,
    participants: list[ParticipantTarget],
) -> list[Any]:
    row: list[Any] = ["Week status ➜"]
    for participant_index, participant in enumerate(participants):
        hours_column = _column_letter(3 + participant_index * PARTICIPANT_GROUP_WIDTH)
        week_range = f"{hours_column}{week_start_row}:{hours_column}{week_end_row}"
        progress_formula = _sparkline_formula(
            total_formula=f"SUM({week_range})",
            target_formula=f'INDEX(SPLIT({hours_column}{status_row}, "/"), 0, 2)',
        )
        status_formula = f'=SUM({week_range}) & "/" & {participant.weekly_hours}'
        row.extend([progress_formula, status_formula, False, False, False])
        if participant_index != len(participants) - 1:
            row.append("")
    return row


def _month_status_row(
    week_ranges: list[tuple[int, int]],
    week_status_rows: list[int],
    participants: list[ParticipantTarget],
) -> list[Any]:
    row: list[Any] = ["Month status ➜"]
    for participant_index, participant in enumerate(participants):
        hours_column = _column_letter(3 + participant_index * PARTICIPANT_GROUP_WIDTH)
        sum_ranges = ", ".join(
            f"{hours_column}{start_row}:{hours_column}{end_row}"
            for start_row, end_row in week_ranges
        )
        target_formula = str(participant.monthly_hours)
        progress_formula = _sparkline_formula(
            total_formula=f"SUM({sum_ranges})",
            target_formula=target_formula,
        )
        status_formula = f'=SUM({sum_ranges}) & "/" & {participant.monthly_hours}'
        row.extend([progress_formula, status_formula, False, False, False])
        if participant_index != len(participants) - 1:
            row.append("")
    return row


def _column_letter(column_number: int) -> str:
    result = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _sparkline_formula(total_formula: str, target_formula: str) -> str:
    return (
        f"=SPARKLINE({{{total_formula}, {target_formula}-{total_formula}}}, {{"
        '"charttype","bar"; '
        f'"max", {target_formula}; '
        '"color1", CHOOSE(MAX(1, MIN(ROUND(('
        f"{total_formula} / {target_formula}"
        f") * 25), 25)), {PROGRESS_COLORS}); "
        '"color2", "#EEEEEE"'
        "})"
    )


def format_tracker_date(day: date) -> str:
    weekday = calendar.day_abbr[day.weekday()]
    month = calendar.month_abbr[day.month]
    return f"{weekday}, {month} {day.day}"


def latest_tracker_date(date_values: set[str], fallback_year: int) -> date:
    parsed_dates = [
        parsed_date
        for value in date_values
        if (parsed_date := parse_tracker_date(value, fallback_year)) is not None
    ]
    if not parsed_dates:
        return date(fallback_year, 1, 1) - timedelta(days=1)
    return max(parsed_dates)


def next_target_month_after_completed_block(latest_date: date) -> tuple[int, int]:
    if latest_date.day <= 7:
        return latest_date.year, latest_date.month
    return TrackingService._next_month(latest_date.year, latest_date.month)


def next_find_offer_append_row(first_column_values: list[str]) -> int:
    for row_number in range(len(first_column_values), 0, -1):
        if not first_column_values[row_number - 1]:
            continue

        if first_column_values[row_number - 1] == "Month status ➜":
            return row_number + MONTH_STATUS_BLOCK_HEIGHT
        return row_number + 1

    return 1


def parse_tracker_date(value: str, fallback_year: int) -> date | None:
    try:
        parsed = datetime.strptime(value, "%a, %b %d").date()
    except ValueError:
        return None

    parsed = parsed.replace(year=fallback_year)
    if parsed.month == 12 and date.today().month == 1:
        return parsed.replace(year=fallback_year - 1)
    return parsed


def tracker_column_count(participant_count: int) -> int:
    return 1 + participant_count * PARTICIPANT_DATA_WIDTH + (participant_count - 1)


def month_block_merge_requests(
    worksheet: Any,
    source_start_row: int,
    target_start_row: int,
) -> list[dict[str, Any]]:
    metadata = worksheet.spreadsheet.fetch_sheet_metadata(params={"includeGridData": "false"})
    source_start_index = source_start_row - 1
    source_end_index = source_start_index + MONTH_STATUS_BLOCK_HEIGHT
    target_offset = target_start_row - source_start_row
    requests = []

    for sheet in metadata.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") != worksheet.id:
            continue

        for merge in sheet.get("merges", []):
            if (
                merge.get("startRowIndex", 0) < source_start_index
                or merge.get("endRowIndex", 0) > source_end_index
            ):
                continue

            requests.append(
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": worksheet.id,
                            "startRowIndex": merge["startRowIndex"] + target_offset,
                            "endRowIndex": merge["endRowIndex"] + target_offset,
                            "startColumnIndex": merge["startColumnIndex"],
                            "endColumnIndex": merge["endColumnIndex"],
                        },
                        "mergeType": "MERGE_ALL",
                    }
                }
            )

    return requests


def month_block_checkbox_style_requests(sheet_id: int, start_row: int) -> list[dict[str, Any]]:
    requests = []
    end_row = start_row + MONTH_STATUS_BLOCK_HEIGHT - 1

    for column_index in CHECKBOX_COLUMN_INDEXES:
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": start_row - 1,
                        "endRowIndex": end_row,
                        "startColumnIndex": column_index,
                        "endColumnIndex": column_index + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": TRACKER_BLUE,
                            "horizontalAlignment": "CENTER",
                            "textFormat": {
                                "foregroundColor": WHITE,
                                "fontFamily": "Arial",
                                "fontSize": 10,
                                "bold": True,
                            },
                        },
                        "dataValidation": {
                            "condition": {"type": "BOOLEAN"},
                            "strict": True,
                        },
                    },
                    "fields": (
                        "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat),"
                        "dataValidation"
                    ),
                }
            },
        )

    return requests


def number_format_request(
    sheet_id: int,
    row_number: int,
    column_index: int,
    target: int,
) -> dict[str, Any]:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_number - 1,
                "endRowIndex": row_number,
                "startColumnIndex": column_index,
                "endColumnIndex": column_index + 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "NUMBER",
                        "pattern": f'0"/{target}"',
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }


def add_progress_rule_request(
    sheet_id: int,
    ranges: list[dict[str, int]],
    max_value: int,
    index: int,
) -> dict[str, Any]:
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": ranges,
                "gradientRule": {
                    "minpoint": {
                        "type": "NUMBER",
                        "value": "0",
                        "colorStyle": {"rgbColor": {"red": 1}},
                    },
                    "maxpoint": {
                        "type": "NUMBER",
                        "value": str(max_value),
                        "colorStyle": {"rgbColor": {"green": 1}},
                    },
                },
            },
            "index": index,
        }
    }


async def run_find_offer_monthly_scheduler() -> None:
    service = TrackingService()
    while True:
        now = datetime.now(UTC)
        try:
            await service.auto_extend_find_offer_if_needed(now.date())
        except Exception:
            logger.exception("Find offer auto extension failed")
        tomorrow = (now + timedelta(days=1)).date()
        next_run = datetime.combine(tomorrow, datetime.min.time(), tzinfo=UTC)
        await asyncio.sleep((next_run - now).total_seconds())
