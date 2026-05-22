import datetime

import gspread
from fastapi import HTTPException
from uvicorn import logging


USER_EMAILS_MAPPING = {
    "fesenko.kostya576@gmail.com": {"learned": 9, "hours": 10},
    "vania@gmail.com": {"learned": 2, "hours": 3},
    "vlad@gmail.com": {"learned": 16, "hours": 17},
    "kostya2@gmail.com": {"learned": 23, "hours": 24},
}


VERIFICATION_MATRIX = {
    "Vania": {
        "Kostya": 5,
        "Vlad": 6,
        "Kostya2": 7,
    },
    "Kostya": {
        "Vania": 12,
        "Vlad": 13,
        "Kostya2": 14,
    },
    "Vlad": {
        "Vania": 19,
        "Kostya": 20,
        "Kostya2": 21,
    },
    "Kostya2": {
        "Vania": 26,
        "Kostya": 27,
        "Vlad": 28,
    },
}


def get_sheet():
    try:
        gc = gspread.service_account(filename="google_services.json")
        return gc.open("Find offer").sheet1
    except Exception as e:
        logging.error(f"Google Auth Error: {e}")
        raise HTTPException(status_code=500, detail="Google connection error") from e


def get_row_index(sheet):
    today = datetime.datetime.now().strftime("%a, %b %-d")
    try:
        return sheet.find(today).row
    except gspread.CellNotFound:
        return None


async def update_study_data(email: str, activity: str, hours: float):
    if email not in USER_EMAILS_MAPPING:
        raise HTTPException(status_code=403, detail="Your email is not linked to the table.")

    sheet = get_sheet()
    row_idx = get_row_index(sheet)
    if not row_idx:
        raise HTTPException(status_code=404, detail="Today's date not found in the table.")

    cols = USER_EMAILS_MAPPING[email]

    try:
        sheet.update_cell(row_idx, cols["learned"] + 1, activity)
        sheet.update_cell(row_idx, cols["hours"] + 1, str(hours))
        return row_idx
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recording error: {str(e)}") from e


async def confirm_study_data(student_name: str, manager_name: str):
    if student_name not in VERIFICATION_MATRIX:
        raise HTTPException(status_code=400, detail=f"Student {student_name} not found in matrix.")

    manager_map = VERIFICATION_MATRIX[student_name]
    if manager_name not in manager_map:
        raise HTTPException(
            status_code=403,
            detail=f"You ({manager_name}) cannot check for {student_name}.",
        )

    col_idx = manager_map[manager_name]

    sheet = get_sheet()
    row_idx = get_row_index(sheet)

    if not row_idx:
        raise HTTPException(status_code=404, detail="Today's date not found in the table.")

    try:
        sheet.update_cell(row_idx, col_idx, "TRUE")
        return True
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Sheets error: {str(e)}") from e
