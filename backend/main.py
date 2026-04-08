import os
import json
import time
import uuid
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from sheets_loader import load_sheet
from intent_detector import get_sheets_for_intent
from retriever import retrieve, filter_by_label, filter_by_peminatan_id
from context_builder import build_context
from memory import get_history, add_message
from openrouter_service import chat, is_broad_request_llm, detect_intent_llm

app = FastAPI(title="Promed Mentor AI — Cinta")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

LOG_FILE = Path("../logs/chat_logs.json")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


def _truncate_words(text: str, max_words: int = 400) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip() + "…"


def _extract_unique_values(rows, candidate_keys, limit=None):
    seen = set()
    out = []
    for row in rows:
        for k in candidate_keys:
            if k not in row:
                continue
            v = row.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            if s in seen:
                continue
            seen.add(s)
            out.append(s)
            if limit is not None and len(out) >= limit:
                return out
    return out


def _contains_any_name(msg_lower: str, names) -> bool:
    """
    Cek apakah pesan user menyebutkan salah satu nama dari daftar.
    Menggunakan pencocokan dua arah:
    - "TOBO" ada di msg dan nama studionya "TOBO Studio" → True (kata dari nama ada di pesan)
    - "Toys & Bricks" ada di msg → True (nama lengkap ada di pesan)
    """
    for name in names:
        if not name:
            continue
        name_lower = name.lower()
        # Cara 1: nama lengkap ada di pesan
        if name_lower in msg_lower:
            return True
        # Cara 2: tiap kata dari nama ada di pesan (partial match untuk studio name)
        name_clean = re.sub(r'[^\w\s]', '', name_lower.replace('-', ' '))
        name_words = [w for w in name_clean.split() if len(w) > 1]
        if name_words and all(w in msg_lower for w in name_words[:1]):  # cek kata pertama yang signifikan
            return True
    return False


def _extract_topic_from_history(
    history: list,
    peminatan_names: list,
    studio_names: list,
) -> str | None:
    """
    Scan pesan-pesan sebelumnya (dari yang paling baru)
    untuk menemukan peminatan atau studio yang sedang dibicarakan.
    Kembalikan nama peminatan/studio yang ditemukan, atau None.
    """
    all_names = list(peminatan_names) + list(studio_names)
    # Sort names by length descending to prefer longer specific names over short ones
    all_names.sort(key=len, reverse=True)
    
    # Scan dari pesan terbaru ke yang lebih lama
    for msg in reversed(history):
        content_lower = msg.get("content", "").lower()
        
        matched_names = []
        for name in all_names:
            if name and name.lower() in content_lower:
                # Perawatan untuk substring palsu: pastikan bukan di tengah kata lain
                # Mengingat nama bisa berisi spasi, kita cek sederhana batas kata
                pattern = r'\b' + re.escape(name.lower()) + r'\b'
                if re.search(pattern, content_lower):
                    matched_names.append(name)
        
        if not matched_names:
            continue
            
        # Jika pesan ini mengandung terlalu banyak nama (> 2), ini pasti daftar menu dari bot.
        # Jangan ekstrak topik dari sini karena tidak merujuk ke topik tunggal.
        if len(matched_names) > 2:
            continue
            
        # Kembalikan topik yang paling pertama ditemukan (sudah diurutkan dari yang terpanjang)
        return matched_names[0]

    return None


def _format_numbered_list(items, max_items=None):
    items = list(items)
    if max_items is not None:
        items = items[:max_items]
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item}")
    return "\n".join(lines)


def _extract_first_value(rows, candidate_keys):
    for row in rows:
        for k in candidate_keys:
            if k not in row:
                continue
            v = row.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
    return None


def _infer_selected_peminatan_label(user_msg_lower: str, peminatan_names: list, peminatan_rows: list):
    """
    Infer peminatan label from user message using sheet data (RAG-style).
    - If user sends a number, map it to the numbered peminatan list (derived from Sheets).
    - Otherwise, run retrieval over peminatan_rows and extract a label from top rows.
    """
    if peminatan_names:
        # Numeric selection only when the message is essentially "just a number".
        # This prevents interpreting "daftar 13 peminatan ..." as a selection.
        if re.match(r"^\s*\d+\s*$", user_msg_lower):
            digits = re.findall(r"\d+", user_msg_lower)
            if digits:
                try:
                    idx = int(digits[0])
                    if 1 <= idx <= len(peminatan_names):
                        return peminatan_names[idx - 1]
                except Exception:
                    pass

    if not peminatan_rows:
        return None

    inferred_rows = retrieve(peminatan_rows, user_msg_lower, top_k=3)
    if not inferred_rows:
        return None

    return _extract_first_value(
        inferred_rows,
        candidate_keys=["nama_peminatan", "peminatan", "focus", "nama_fokus", "nama_jurusan"],
    )


def _label_is_valid(label: str, master_rows: list, user_msg_lower: str = "") -> bool:
    """
    Validasi ganda:
    1. Label harus merujuk ke salah satu peminatan yang ada di database.
    2. Setidaknya satu kata penting dari label (ATAU nama studio) harus muncul di pesan user.
    Ini mencegah label diam-diam ditebak retriever saat user nanya agregat.
    """
    if not label or not master_rows:
        return False
    label_clean = re.sub(r'[^\w\s]', '', label.lower().replace('-', ' '))
    label_words = [w for w in label_clean.split() if len(w) > 1]
    if not label_words:
        return False

    # Syarat 1: label ada di daftar peminatan yang dikenal
    exists_in_db = False
    studio_words = []
    
    for row in master_rows:
        pem = row.get("peminatan", "") or row.get("nama_peminatan", "")
        studio = row.get("nama_studio", "") or row.get("studio", "")
        pem_clean = re.sub(r'[^\w\s]', '', str(pem).lower().replace('-', ' '))
        if any(w in pem_clean for w in label_words):
            exists_in_db = True
            if studio:
                std_clean = re.sub(r'[^\w\s]', '', str(studio).lower().replace('-', ' '))
                studio_words.extend([w for w in std_clean.split() if len(w) > 1])
            break
            
    if not exists_in_db:
        return False

    # Syarat 2: label atau studio harus disebut di pesan user
    # PENGECUALIAN: jika user_msg murni hanya angka, lompati syarat 2.
    if user_msg_lower and not re.match(r"^\s*\d+\s*$", user_msg_lower):
        msg_clean = re.sub(r'[^\w\s]', '', user_msg_lower)
        valid_words = label_words + studio_words
        if not any(w in msg_clean for w in valid_words):
            return False

    return True


def _get_peminatan_id(label: str, master_rows: list) -> str | None:
    if not label or not master_rows:
        return None
    label_clean = re.sub(r'[^\w\s]', '', label.lower().replace('-', ' '))
    label_words = [w for w in label_clean.split() if len(w) > 1]
    
    for row in master_rows:
        pem = row.get("peminatan", "") or row.get("nama_peminatan", "")
        studio = row.get("nama_studio", "") or row.get("studio", "")
        pem_clean = re.sub(r'[^\w\s]', '', str(pem).lower().replace('-', ' '))
        std_clean = re.sub(r'[^\w\s]', '', str(studio).lower().replace('-', ' '))
        
        # Cek apakah ada satupun kata spesifik dari label di peminatan/studio database
        if any(w in pem_clean for w in label_words) or any(w in std_clean for w in label_words):
            return row.get("peminatan_id", None)
            
    return None


def _log(session_id: str, user_msg: str, bot_msg: str, latency: float):
    entry = {
        "session_id": session_id,
        "user_time": datetime.now(timezone.utc).isoformat(),
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
    # Push to console logs so it's visible in Railway Dashboard
    print(f"\n[CHAT LOG] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"User ({session_id}): {user_msg}")
    print(f"Bot: {bot_msg}\n")


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    t0 = time.time()

    session_id = req.session_id or str(uuid.uuid4())
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Normalization for common slang so Exact Word Retriever doesn't fail
    # e.g., "gim" -> "game"
    message = re.sub(r'\bgim\b', 'game', message, flags=re.IGNORECASE)
    
    # 1. Detect intent — 100% LLM, no keywords
    prior_history = get_history(session_id)
    intent = await detect_intent_llm(message, prior_history)
    print(f"[INTENT] LLM detected: {intent} for: '{message}'")

    # 2. Load sheets
    sheet_names = get_sheets_for_intent(intent)
    all_rows = []
    for sheet_name in sheet_names:
        try:
            rows = load_sheet(sheet_name)
            all_rows.extend(rows)
        except Exception as e:
            print(f"[WARN] Could not load sheet {sheet_name}: {e}")

    # 3. Build message history (untuk multi-turn)
    add_message(session_id, "user", message)

    # 4. Tangani pertanyaan broad / tidak spesifik — pakai LLM classifier, bukan keyword list
    msg_lower = message.lower()
    try:
        master_rows = load_sheet("peminatan_master")
        peminatan_names = _extract_unique_values(
            master_rows,
            candidate_keys=["nama_peminatan", "peminatan", "focus", "nama_fokus", "nama_jurusan"],
            limit=30,
        )
        studio_names = _extract_unique_values(
            master_rows,
            candidate_keys=["nama_studio", "studio"],
            limit=30,
        )
    except Exception:
        peminatan_names = _extract_unique_values(
            all_rows,
            candidate_keys=["nama_peminatan", "peminatan", "focus", "nama_fokus", "nama_jurusan"],
            limit=30,
        )
        studio_names = []

    has_peminatan = _contains_any_name(msg_lower, peminatan_names) or \
                    _contains_any_name(msg_lower, studio_names)

    # Cek topik dari history percakapan sebelumnya (context rollover)
    # Supaya follow-up seperti "magangnya di mana?" bisa dipahami merujuk ke topik sebelumnya
    prior_history = get_history(session_id)[:-1]  # exclude pesan user yang barusan
    ctx_topic = None
    if not has_peminatan:
        ctx_topic = _extract_topic_from_history(prior_history, peminatan_names, studio_names)
        if ctx_topic:
            # Enriched query: gabungkan topik dari history ke pesan saat ini
            # supaya retrieval dan infer label bisa nyasar ke data yang benar
            message = f"{message} {ctx_topic}"
            msg_lower = message.lower()
            has_peminatan = True
            print(f"[CTX] Injected topic from history: '{ctx_topic}'")

    # Query Expansion: Menyambungkan struktur tabel yang bolong
    # (Sheet magang hanya punya nama studio. Jika user nanya "magang HCI", RAG gagal karena kata "HCI" tidak ada di sheet magang)
    # Solusinya: otomatis inject alias ke query.
    expanded_aliases = []
    if "master_rows" in locals():
        for row in master_rows:
            pem = str(row.get("nama_peminatan", row.get("peminatan", "")))
            studio = str(row.get("nama_studio", row.get("studio", "")))
            if pem and studio:
                if _contains_any_name(msg_lower, [pem]) and not _contains_any_name(msg_lower, [studio]):
                    expanded_aliases.append(studio)
                elif _contains_any_name(msg_lower, [studio]) and not _contains_any_name(msg_lower, [pem]):
                    expanded_aliases.append(pem)

    if expanded_aliases:
        message = f"{message} {', '.join(set(expanded_aliases))}"
        msg_lower = message.lower()
        print(f"[CTX] Expanded query with aliases: {expanded_aliases}")

    # Klasifikasi broad/spesifik pakai LLM — satu kali, hasilnya di-cache ke variabel
    is_broad = await is_broad_request_llm(message)
    
    # Hard override: Jika pesan sangat pendek (macam quick button) dan tidak memiliki nama spesifik (has_peminatan), WAJIB anggap broad
    if not has_peminatan and len(message.split()) <= 3:
        is_broad = True

    # Mode "menu" saat user tidak spesifik
    if intent == "general":
        if not peminatan_names:
            response_text = "Maaf, Cinta belum tau informasi ini,"
        else:
            inferred_label = _infer_selected_peminatan_label(msg_lower, peminatan_names, all_rows)

            # HAPUS hardcode menu awal. Biarkan LLM yang menceritakan 13 peminatan dengan personanya via master_rows!
            # Jadi kita langsung masuk ke pengecekan spesifik atau broad


            # Jika request menanyakan sesuatu yang spesifik, cek apakah merujuk ke SATU peminatan tertentu
            if _label_is_valid(inferred_label, master_rows, msg_lower):
                # Lakukan retrieval ulang dan jawab dengan context dari Sheets (RAG) untuk 1 peminatan
                bundle_rows = list(all_rows)
                already_loaded = set(sheet_names)
                bundle_intents = ["peminatan", "kurikulum", "magang", "capstone"]
                for bun_intent in bundle_intents:
                    for sn in get_sheets_for_intent(bun_intent):
                        if sn in already_loaded:
                            continue
                        try:
                            rows = load_sheet(sn)
                            bundle_rows.extend(rows)
                            already_loaded.add(sn)
                        except Exception as e:
                            print(f"[WARN] Could not load sheet {sn}: {e}")

                top_rows = retrieve(bundle_rows, inferred_label)
                top_rows = filter_by_label(top_rows, inferred_label)
                context = build_context(top_rows, intent=intent)
                if not context.strip():
                    response_text = "Maaf, Cinta belum tau informasi ini,"
                    add_message(session_id, "assistant", response_text)
                    latency = time.time() - t0
                    _log(session_id, message, response_text, latency)
                    return {
                        "session_id": session_id,
                        "response": response_text,
                        "intent": "peminatan",
                        "latency_seconds": round(latency, 3),
                        "selected_peminatan": inferred_label,
                        "context_empty": True,
                    }

                messages_for_llm = get_history(session_id)
                response_text = await chat(messages_for_llm, context, intent=intent, is_broad=is_broad)
                response_text = _truncate_words(response_text, 400)
                add_message(session_id, "assistant", response_text)
                latency = time.time() - t0
                _log(session_id, message, response_text, latency)
                return {
                    "session_id": session_id,
                    "response": response_text,
                    "intent": "peminatan",
                    "latency_seconds": round(latency, 3),
                    "selected_peminatan": inferred_label,
                    "handled_by_menu": False,
                }
            else:
                # User bertanya spesifik tapi tidak merujuk 1 peminatan (contoh: "nama studionya apa aja?" atau "studio stream apa aja?")
                # Filter master_rows agar LLM tidak mencerembet ke deskripsi/fokus (mencegah over-explaining) tapi JANGAN hapus kolom penting seperti studio_stream
                safe_master_rows = [
                    {k: v for k, v in row.items() if not any(x in k.lower() for x in ["summary", "deskripsi", "fokus", "description"])}
                    for row in master_rows
                ]
                context = build_context(safe_master_rows, intent=intent)
                if context.strip():
                    messages_for_llm = get_history(session_id)
                    response_text = await chat(messages_for_llm, context, intent=intent, is_broad=is_broad)
                    response_text = _truncate_words(response_text, 400)
                    add_message(session_id, "assistant", response_text)
                    latency = time.time() - t0
                    _log(session_id, message, response_text, latency)
                    return {
                        "session_id": session_id,
                        "response": response_text,
                        "intent": "general",
                        "latency_seconds": round(latency, 3),
                        "handled_by_menu": False,
                    }


        # fallback (peminatan_names kosong) tetap di sini
        response_text = _truncate_words(response_text, 300)
        add_message(session_id, "assistant", response_text)
        latency = time.time() - t0
        _log(session_id, message, response_text, latency)
        return {
            "session_id": session_id,
            "response": response_text,
            "intent": intent,
            "latency_seconds": round(latency, 3),
            "handled_by_menu": True,
        }

    # ── Peminatan: intent spesifik peminatan ────────────────────────────────
    if intent == "peminatan" and peminatan_names:
        # HAPUS hardcoded menu di sini. Jika user nanya broad, dia akan masuk ke blok `else` (master_rows)
        # dan Cinta akan menjawab dengan menceritakan 13 list secara natural.

        inferred_label = _infer_selected_peminatan_label(msg_lower, peminatan_names, all_rows)

        # Validasi: apakah label itu beneran merujuk ke satu peminatan yang ada? ATAU murni input nomor menu.
        if _label_is_valid(inferred_label, master_rows, msg_lower):
            # --- Mode satu peminatan: filter ketat ke label tersebut ---
            bundle_rows = list(all_rows)
            already_loaded = set(sheet_names)
            bundle_intents = ["peminatan", "kurikulum", "magang", "capstone"]
            for bun_intent in bundle_intents:
                for sn in get_sheets_for_intent(bun_intent):
                    if sn in already_loaded:
                        continue
                    try:
                        rows = load_sheet(sn)
                        bundle_rows.extend(rows)
                        already_loaded.add(sn)
                    except Exception as e:
                        print(f"[WARN] Could not load sheet {sn}: {e}")

            pid = _get_peminatan_id(inferred_label, master_rows)
            if pid:
                top_rows = filter_by_peminatan_id(bundle_rows, pid)
            else:
                top_rows = retrieve(bundle_rows, inferred_label)
                top_rows = filter_by_label(top_rows, inferred_label)
            context = build_context(top_rows, intent=intent)
            if not context.strip():
                response_text = "Maaf, Cinta belum tau informasi ini,"
                add_message(session_id, "assistant", response_text)
                latency = time.time() - t0
                _log(session_id, message, response_text, latency)
                return {
                    "session_id": session_id,
                    "response": response_text,
                    "intent": "peminatan",
                    "latency_seconds": round(latency, 3),
                    "selected_peminatan": inferred_label,
                    "context_empty": True,
                }

            messages_for_llm = get_history(session_id)
            response_text = await chat(messages_for_llm, context, intent=intent, is_broad=is_broad)
            response_text = _truncate_words(response_text, 400)
            add_message(session_id, "assistant", response_text)
            latency = time.time() - t0
            _log(session_id, message, response_text, latency)
            return {
                "session_id": session_id,
                "response": response_text,
                "intent": "peminatan",
                "latency_seconds": round(latency, 3),
                "selected_peminatan": inferred_label,
                "handled_by_menu": False,
            }
        else:
            # --- Mode semua peminatan: user nanya agregat (misal semua nama studio) ---
            # Langsung gunakan semua baris master_rows supaya LLM punya data lengkap
            print(f"[INFO] Label '{inferred_label}' tidak valid sebagai peminatan tunggal → gunakan all master rows")
            # Filter master_rows agar LLM tidak mencerembet ke deskripsi/fokus (mencegah over-explaining) tapi JANGAN hapus kolom penting seperti studio_stream
            safe_master_rows = [
                {k: v for k, v in row.items() if not any(x in k.lower() for x in ["summary", "deskripsi", "fokus", "description"])}
                for row in master_rows
            ]
            context = build_context(safe_master_rows, intent=intent)
            if context.strip():
                messages_for_llm = get_history(session_id)
                response_text = await chat(messages_for_llm, context, intent=intent, is_broad=is_broad)
                response_text = _truncate_words(response_text, 400)
                add_message(session_id, "assistant", response_text)
                latency = time.time() - t0
                _log(session_id, message, response_text, latency)
                return {
                    "session_id": session_id,
                    "response": response_text,
                    "intent": "peminatan",
                    "latency_seconds": round(latency, 3),
                    "handled_by_menu": False,
                }

    # 5. Handle Broad Requests (Quick Buttons / General Queries) via LLM
    # Jika broad dan tidak ada data spesifik (misal baru klik quick button), panggil LLM. 
    # LLM akan menjawab dengan disclaimer/probing sesuai rules di SYSTEM_PROMPT.
    if is_broad and not has_peminatan:
        # Load paminatan_master as context if possible for broad overview
        try:
             m_rows = load_sheet("peminatan_master")
             context = build_context(m_rows, intent=intent)
        except:
             context = ""
             
        messages_for_llm = get_history(session_id)
        response_text = await chat(messages_for_llm, context, intent=intent, is_broad=is_broad)
        response_text = _truncate_words(response_text, 400)
        add_message(session_id, "assistant", response_text)
        latency = time.time() - t0
        _log(session_id, message, response_text, latency)
        return {
            "session_id": session_id,
            "response": response_text,
            "intent": intent,
            "latency_seconds": round(latency, 3),
            "handled_by_menu": True,
        }

    # 6. Retrieve top rows (LLM mode - Specific Query)
    # Filter cerdas lintas sheet: Gunakan `peminatan_id` sebagai Foreign Key mutlak
    # Jika user nanya spesifik "magang HCI", kita cari ID HCI ("PM07") dan filter sheet magang yang HANYA memiliki "PM07".
    # Ini melindungi RAG dari kegagalan akibat ketidakcocokan kata (alias gap).
    inferred_label_global = _infer_selected_peminatan_label(msg_lower, peminatan_names, master_rows)
    if inferred_label_global and _label_is_valid(inferred_label_global, master_rows, msg_lower):
        pid = _get_peminatan_id(inferred_label_global, master_rows)
        if pid:
            # Guard capstone "coming soon": HANYA aktif jika:
            # 1. Intent memang capstone
            # 2. User benar-benar menyebut nama peminatan spesifik
            # 3. Pesan user mengandung kata capstone eksplisit (cegah false positive)
            CAPSTONE_KEYWORDS = ["capstone", "tugas akhir", "final project", "proyek akhir"]
            user_asking_capstone = any(kw in msg_lower for kw in CAPSTONE_KEYWORDS)

            if intent == "capstone" and has_peminatan and user_asking_capstone:
                label_lower = inferred_label_global.lower()
                if not any(x in label_lower for x in ["fashion & lifestyle", "flui", "hci", "spice", "game", "ox"]):
                    response_text = "Maaf ya Promates, untuk sementara info capstone selain di peminatan Fashion & Lifestyle (FLUI), HCI (S.P.I.C.E. Studio), dan Game Dev (OX-Laboratory) belum tersedia karena Cinta masih prototipe. *Coming soon*! ✨"
                    add_message(session_id, "assistant", response_text)
                    latency = time.time() - t0
                    _log(session_id, message, response_text, latency)
                    return {
                        "session_id": session_id,
                        "response": response_text,
                        "intent": intent,
                        "latency_seconds": round(latency, 3),
                        "handled_by_menu": True,
                    }
                    
            top_rows = filter_by_peminatan_id(all_rows, pid)
        else:
            top_rows = retrieve(all_rows, message)
    else:
        # Jika itu komparasi (is_comparison = True) atau tidak ada label valid, kita jangan di-lock ke 1 ID,
        # biarkan Retriever mengambil semua row yang bersinggungan dengan isi pesan.
        semester_match = re.search(r'\b(?:semester|smt|smst|sem|ke-)\s*(\d+)\b', msg_lower)
        if intent == "kurikulum" and semester_match:
            target_sem = str(semester_match.group(1))
            # Exact match filter for semester to prevent truncation and mix-ups
            filtered_courses = [r for r in all_rows if str(r.get("semester", "")).strip() == target_sem]
            if filtered_courses:
                top_rows = filtered_courses
            else:
                top_rows = retrieve(all_rows, message, top_k=40)
        else:
            top_rows = retrieve(all_rows, message, top_k=40 if intent == "kurikulum" else 15)

    # 6. Build context
    context = build_context(top_rows, intent=intent)

    # 7. Jika konteks kosong, tetap panggil LLM (Jalur 2 / General Knowledge)
    # Cinta akan menjawab jujur atau memberikan probing sesuai persona.
    if not context.strip():
        print("[WARN] Konteks kosong — memanggil LLM untuk jawaban fallback persona.")
        
    messages_for_llm = get_history(session_id)

    # 8. Call LLM
    try:
        response_text = await chat(messages_for_llm, context, intent=intent, is_broad=is_broad)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    response_text = _truncate_words(response_text, 400)
    add_message(session_id, "assistant", response_text)

    latency = time.time() - t0
    _log(session_id, message, response_text, latency)

    return {
        "session_id": session_id,
        "response": response_text,
        "intent": intent,
        "latency_seconds": round(latency, 3),
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "Promed Mentor AI — Cinta"}


@app.get("/export-logs")
def export_logs(start_date: str = None, end_date: str = None):
    """
    Endpoint untuk mendownload riwayat percakapan.
    start_date / end_date format: YYYY-MM-DD (e.g., 2026-04-01)
    """
    if not LOG_FILE.exists():
        return {"logs": []}

    try:
        logs = json.loads(LOG_FILE.read_text())
    except Exception:
        return {"error": "Failed to parse logs file."}

    filtered_logs = logs

    # Filter berdasarkan range tanggal jika diberikan
    if start_date:
        filtered_logs = [log for log in filtered_logs if log.get('user_time', '') >= start_date]
        
    if end_date:
        # Tambahkan 23:59:59 untuk mencakup full hari pada end_date
        end_date_full = f"{end_date}T23:59:59"
        filtered_logs = [log for log in filtered_logs if log.get('user_time', '') <= end_date_full]

    return {"count": len(filtered_logs), "data": filtered_logs}

