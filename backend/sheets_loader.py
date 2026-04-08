import os
import json
import time
import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
# Di Railway: isi env var ini dengan isi JSON service_account.json (copy-paste seluruh isinya)
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# TTL cache: data spreadsheet di-cache selama 10 menit.
# Setelah 10 menit, data ditarik ulang dari Google Sheets secara otomatis.
# Ini mencegah stale data sekaligus tidak membombardir API Google.
CACHE_TTL_SECONDS = 600  # 10 menit

_client = None
_cache: Dict[str, dict] = {}  # {sheet_name: {"data": [...], "timestamp": float}}


def _parse_service_account_json(raw: str) -> dict:
    """
    Parse GOOGLE_SERVICE_ACCOUNT_JSON dari Railway env var secara robust.
    Railway sering menyimpan private_key dengan \\n yang ter-escape dobel
    (literal backslash-n, bukan newline asli). Fungsi ini menangani dua kasus:
    1. JSON valid langsung → parse biasa
    2. private_key berisi \\n literal → fix dulu, baru parse
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Coba fix: Railway kadang simpan env var dengan newline asli di dalam string
        # yang merusak format JSON. Kita escape newline liar di luar konteks JSON string.
        fixed = raw.replace('\n', '\\n')
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

    # Last resort: parsing manual — Railway sering mangle private_key saja
    # Coba bersihkan hanya field private_key
    try:
        import re
        def fix_private_key(m):
            key = m.group(1).replace('\n', '\\n').replace('\r', '')
            return f'"private_key": "{key}"'
        fixed2 = re.sub(
            r'"private_key"\s*:\s*"(.*?)"(?=\s*[,}])',
            fix_private_key,
            raw,
            flags=re.DOTALL
        )
        return json.loads(fixed2)
    except Exception as e:
        raise ValueError(f"Gagal parse GOOGLE_SERVICE_ACCOUNT_JSON: {e}\n"
                         f"Pastikan value di Railway tidak ada newline liar di luar private_key.") from e


def _get_client() -> gspread.Client:
    """
    Buat atau re-authorize gspread client.
    PENTING: Jika token expired / koneksi mati, client lama di-buang
    dan dibuat ulang supaya tidak terus-terusan gagal.
    """
    global _client
    if _client is None:
        if SERVICE_ACCOUNT_JSON:
            creds_dict = _parse_service_account_json(SERVICE_ACCOUNT_JSON)
            # Fix private_key: pastikan \n di dalam key adalah newline asli, bukan '\\n'
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


def _reset_client():
    """Force reconnect di panggilan berikutnya."""
    global _client
    _client = None


def load_sheet(sheet_name: str) -> List[Dict]:
    """
    Load all rows from a sheet as list of dicts.
    - Cached selama CACHE_TTL_SECONDS (10 menit).
    - Jika Google API error, client di-reset dan dicoba 1x lagi.
    - TIDAK meng-cache hasil error (mencegah cache-poisoning).
    """
    now = time.time()

    # Cek cache: apakah data masih fresh?
    if sheet_name in _cache:
        entry = _cache[sheet_name]
        age = now - entry["timestamp"]
        if age < CACHE_TTL_SECONDS and entry["data"]:
            return entry["data"]

    # Cache miss atau expired → tarik dari Google Sheets
    for attempt in range(2):  # maksimal 2 percobaan (retry 1x jika auth expired)
        try:
            client = _get_client()
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
            worksheet = spreadsheet.worksheet(sheet_name)
            rows = worksheet.get_all_records()

            # Simpan ke cache HANYA jika berhasil dan data tidak kosong
            if rows:
                _cache[sheet_name] = {"data": rows, "timestamp": now}
                print(f"[SHEETS] Loaded '{sheet_name}': {len(rows)} rows (cached for {CACHE_TTL_SECONDS}s)")
            else:
                print(f"[SHEETS] WARNING: '{sheet_name}' returned 0 rows from Google Sheets!")

            return rows

        except Exception as e:
            print(f"[SHEETS] Attempt {attempt+1} failed for '{sheet_name}': {e}")
            if attempt == 0:
                # Kemungkinan token expired → reset client dan coba lagi
                _reset_client()
            else:
                # Sudah retry, masih gagal. Cek apakah ada data stale di cache
                # Lebih baik kasih data lama daripada kosong (graceful degradation)
                if sheet_name in _cache and _cache[sheet_name]["data"]:
                    print(f"[SHEETS] Falling back to stale cache for '{sheet_name}'")
                    return _cache[sheet_name]["data"]
                raise  # beneran gagal, lempar error ke caller


def clear_cache(sheet_name: str = None):
    """Manual cache invalidation. Tanpa argumen = clear semua."""
    if sheet_name:
        _cache.pop(sheet_name, None)
    else:
        _cache.clear()
    print(f"[SHEETS] Cache cleared: {'all' if not sheet_name else sheet_name}")
