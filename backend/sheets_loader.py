import os
import json
import gspread
from google.oauth2.service_account import Credentials
from functools import lru_cache
from typing import List, Dict

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
# Di Railway: isi env var ini dengan isi JSON service_account.json (copy-paste seluruh isinya)
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

_client = None


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        if SERVICE_ACCOUNT_JSON:
            # Mode Railway/Cloud: baca dari environment variable (JSON string)
            creds_dict = json.loads(SERVICE_ACCOUNT_JSON)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            # Mode lokal: baca dari file service_account.json
            creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


@lru_cache(maxsize=16)
def load_sheet(sheet_name: str) -> List[Dict]:
    """Load all rows from a sheet as list of dicts. Cached per sheet name."""
    client = _get_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(sheet_name)
    return worksheet.get_all_records()
