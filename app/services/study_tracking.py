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


def get_sheet():
    """Connect to Google Sheets."""
    try:
        gc = gspread.service_account(filename="google_services.json")
        return gc.open("Find offer").sheet1
    except FileNotFoundError as e:
        logging.error("google_services.json file not found!")
        raise HTTPException(
            status_code=500, detail="Google API credentials are missing on the server."
        ) from e
    except Exception as e:
        logging.error(f"Google authorization error: {e}")
        raise HTTPException(status_code=500, detail=f"Google API error: {str(e)}") from e


def get_row_index(sheet):
    """Find the row for today's date."""
    today = datetime.datetime.now().strftime("%a, %b %-d")
    try:
        return sheet.find(today).row
    except gspread.CellNotFound:
        logging.warning(f"Date '{today}' not found in the sheet!")
        return None
    except Exception as e:
        logging.error(f"Date lookup error: {e}")
        return None


async def update_study_data(email: str, activity: str, hours: float):
    """Validate the user and write study data to the sheet."""
    if email not in USER_EMAILS_MAPPING:
        raise HTTPException(status_code=403, detail="Your email is not linked to report columns.")

    sheet = get_sheet()
    row_idx = get_row_index(sheet)
    if not row_idx:
        raise HTTPException(status_code=404, detail="Today's date was not found in the sheet.")

    cols = USER_EMAILS_MAPPING[email]
    try:
        sheet.update_cell(row_idx, cols["learned"] + 1, activity)
        sheet.update_cell(row_idx, cols["hours"] + 1, str(hours))
        return True
    except Exception as e:
        logging.error(f"Cell update error: {e}")
        raise HTTPException(status_code=500, detail=f"Google Sheets update error: {str(e)}") from e
