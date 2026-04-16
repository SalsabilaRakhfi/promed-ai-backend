import os
import json
import time
import uuid
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from sheets_loader import load_sheet
from retriever import retrieve
from context_builder import build_context
from memory import get_history, add_message
from openrouter_service import chat

app = FastAPI(title="Promed Mentor AI — Cinta")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

LOG_FILE = Path("../logs/chat_logs.json")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# Cache hasil denormalisasi semua sheet (merge master + detail)
# Ini mencegah re-join 6 sheet setiap request. TTL 10 menit = sama dengan cache sheet individual.
_DENORAM_CACHE = {"data": None, "ts": 0.0}
DENORM_TTL = 600  # 10 menit


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""

def _truncate_words(text: str, max_words: int = 400) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip() + "…"

def _log(session_id: str, user_msg: str, bot_msg: str, latency: float):
    from datetime import timezone, timedelta
    WIB = timezone(timedelta(hours=7))
    entry = {
        "session_id": session_id,
        "user_time": datetime.now(WIB).strftime("%Y-%m-%dT%H:%M:%S+07:00"),
        "user_message": user_msg,
        "bot_message": bot_msg,
        "latency_seconds": round(latency, 3),
    }
    logs = []
    if LOG_FILE.exists():
        try:
            logs = json.loads(LOG_FILE.read_text())
        except Exception:
            pass
    logs.append(entry)
    LOG_FILE.write_text(json.dumps(logs, ensure_ascii=False, indent=2))
    print(f"\n[CHAT LOG] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"User ({session_id}): {user_msg}")
    print(f"Bot: {bot_msg}\n")

def _extract_topic_from_history(history: list, names: list) -> str | None:
    """
    Ekstrak topik (peminatan) dari pesan-pesan sebelumnya untuk meneruskan konteks (Context Rollover).
    Contoh: User nanya "HCI". Bot jawab. User nanya "kalo magangnya di mana?"
    Fungsi ini akan nemu "HCI" di histori dan meneruskannya ke depan.
    """
    sorted_names = sorted([n for n in names if n], key=len, reverse=True)
    
    for msg in reversed(history):
        content_lower = msg.get("content", "").lower()
        matched = []
        for name in sorted_names:
            if name.lower() in content_lower:
                pattern = r'\b' + re.escape(name.lower()) + r'\b'
                if re.search(pattern, content_lower):
                    matched.append(name)
        if not matched:
            continue
        if len(matched) > 2:
            continue  # Mengabaikan pesan yang isinya list panjang
        return matched[0]
    return None

def _load_sheet_safe(sheet_name: str) -> list:
    """Load sheet dengan graceful error handling."""
    try:
        rows = load_sheet(sheet_name)
        print(f"[SHEETS] Loaded '{sheet_name}': {len(rows)} rows")
        return rows
    except Exception as e:
        print(f"[WARN] Gagal load {sheet_name}: {e}")
        return []

def get_denormalized_sheets():
    """
    Muat Peminatan Master dan gabungkan (join) nama Peminatan & Studio 
    ke semua baris data di sheet lain yang memiliki peminatan_id.
    
    FIX: peminatan_id dicocokkan pakai .strip().lower() di KEDUA sisi untuk
    mencegah mismatch PM07 vs pm07 vs 'PM07 ' (spasi tersembunyi).
    FIX: Sheet di-load secara PARALEL untuk memotong cold-start latency ~60%.
    Hasil di-cache selama DENORM_TTL detik.
    """
    global _DENORAM_CACHE
    now = time.time()
    if _DENORAM_CACHE["data"] is not None and (now - _DENORAM_CACHE["ts"]) < DENORM_TTL:
        return _DENORAM_CACHE["data"]

    all_sheet_names = [
        "peminatan_master",
        "curriculum_course_master",
        "course_description_detail",
        "capstone_master",
        "capstone_weekly_detail",
        "internship_reference_2023",
    ]

    # Load semua sheet PARALEL (potong latency cold-start ~60%)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_load_sheet_safe, all_sheet_names))

    master_rows = results[0]
    detail_sheet_data = results[1:]

    # Bangun lookup: peminatan_id (strip+lower) -> info
    lookup = {}
    for r in master_rows:
        pid = str(r.get("peminatan_id", "")).strip().lower()
        if pid:
            lookup[pid] = {
                "_peminatan": str(r.get("nama_peminatan") or r.get("peminatan", "")),
                "_studio": str(r.get("nama_studio") or r.get("studio", "")),
                "_focus": str(r.get("focus") or r.get("nama_fokus", ""))
            }

    # Join: suntikkan nama peminatan & studio ke setiap baris detail
    all_detail_rows = []
    for rows in detail_sheet_data:
        for r in rows:
            # FIX: strip + lower di KEDUA sisi agar PM07, pm07, 'PM07 ' semua cocok
            pid = str(r.get("peminatan_id", "")).strip().lower()
            if pid and pid in lookup:
                r["_info_peminatan"] = lookup[pid]["_peminatan"]
                r["_info_studio"] = lookup[pid]["_studio"]
                r["_info_fokus"] = lookup[pid]["_focus"]
        all_detail_rows.extend(rows)

    result = (master_rows, all_detail_rows)
    if master_rows:
        _DENORAM_CACHE["data"] = result
        _DENORAM_CACHE["ts"] = now
        print(f"[CACHE] Denormalized sheets cached: {len(master_rows)} master + {len(all_detail_rows)} detail rows")
    return result


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    t0 = time.time()

    session_id = req.session_id or str(uuid.uuid4())
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    message = re.sub(r'\bgim\b', 'game', message, flags=re.IGNORECASE)
    
    # 1. Unified RAG Data Loading (In-Memory Database Join)
    master_rows, detail_rows = get_denormalized_sheets()
    
    all_names = set()
    for r in master_rows:
        for key in ["nama_peminatan", "peminatan", "nama_studio", "studio", "focus", "nama_jurusan"]:
            val = r.get(key)
            if val:
                all_names.add(str(val))
    
    # 2. Context Rollover
    prior_history = get_history(session_id)
    ctx_topic = _extract_topic_from_history(prior_history, list(all_names))
    
    search_query = message
    if ctx_topic:
        search_query = f"{message} {ctx_topic}"
        print(f"[CTX] Rollover: '{ctx_topic}' -> Query: '{search_query}'")

    # 3. Massive Retrieval (Single Shot)
    # Cinta langsung mencari jawaban dari LAUTAN data (semua detail kurikulum, magang, capstone digabung!)
    top_detail_rows = retrieve(detail_rows, search_query, top_k=25)
    
    # 4. Context Merging
    context_master = build_context(master_rows)
    context_detail = build_context(top_detail_rows)
    
    full_context = f"=== 13 DATA UTAMA PEMINATAN (HAFALKAN) ===\n{context_master}\n\n=== SPESIFIK DETAIL: MAGANG/KURIKULUM/CAPSTONE (HASIl PENCARIAN) ===\n{context_detail}"
    
    # 5. Connect to Brain (LLM)
    add_message(session_id, "user", message)
    messages_for_llm = get_history(session_id)
    
    try:
        response_text = await chat(messages_for_llm, full_context)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    response_text = _truncate_words(response_text, 400)
    add_message(session_id, "assistant", response_text)

    latency = time.time() - t0
    _log(session_id, message, response_text, latency)

    return {
        "session_id": session_id,
        "response": response_text,
        "intent": "unified_rag",
        "latency_seconds": round(latency, 3),
    }

@app.get("/health")
def health():
    return {"status": "ok", "service": "Promed Mentor AI — Cinta (Unified RAG)"}

@app.get("/export-logs")
def export_logs(start_date: str = None, end_date: str = None):
    if not LOG_FILE.exists():
        return {"logs": []}

    try:
        logs = json.loads(LOG_FILE.read_text())
    except Exception:
        return {"error": "Failed to parse logs file."}

    filtered_logs = logs

    if start_date:
        filtered_logs = [log for log in filtered_logs if log.get('user_time', '') >= start_date]
        
    if end_date:
        end_date_full = f"{end_date}T23:59:59"
        filtered_logs = [log for log in filtered_logs if log.get('user_time', '') <= end_date_full]

    return {"count": len(filtered_logs), "data": filtered_logs}
