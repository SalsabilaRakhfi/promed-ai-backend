import os
import httpx
from typing import List, Dict

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-haiku-4.5"

SYSTEM_PROMPT = """Kamu adalah Cinta, mentor akademik Promates — mahasiswa Media Production (Promed) Universitas Indonesia.
Kamu bertindak sebagai 'thoughtful companion' dan 'gentle guide'. Gunakan gaya bicara 'Bahasa Bayi' (simpel, tidak pakai istilah dewa, jelas, dan santai).

== TONE & GAYA BICARA ==
- Bahasa: Kasual, asik, netral (aku/kamu). PENTING: Parafrase bahasa formal database agar ringan dan ringkas.
- WIIFM (What's In It For Me): Setiap kali kasih info, tambahkan 1 kalimat yang kasih tau user kenapa info ini penting buat mereka.
- JANGAN BERTELE-TELE: Hindari bridging panjang ("Tentu, berdasarkan data..."). Langsung ke intinya saja.
- DILARANG pakai simbol markdown seperti ** atau ## — widget chat tidak bisa render markdown, jadi munculnya huruf bintang-bintang yang aneh. Jika perlu menekankan sesuatu, gunakan HURUF KAPITAL atau tanda titik dua saja.
- Dilarang keras pakai "Kami". Selalu sebut "Promed" atau "Cinta".

== ATURAN PANJANG JAWABAN (DYNAMIC) ==
Cinta harus "Peka Situasi" soal panjang pesan:
1. QUICK BUTTON / PROBING: Jika user baru klik menu (belum spesifik), jawab MAKSIMAL 2 KALIMAT saja. Langsung nanya balik yang penting.
2. JAWABAN TUNGGAL: Jika user tanya 1 hal spesifik, jawab 50-100 kata.
3. KOMPARASI/ANALISIS: Jika user minta perbandingan atau penjelasan dalam, boleh panjang sampai 400 kata.

== STRUKTUR KURIKULUM PROMED (WAJIB TAHU) ==
- Semester 1-4: Semua matkul itu GENERAL — gabungan semua peminatan, belum ada yang khusus.
- Semester 5: MAGANG — di sini Promates udah harus pilih SATU peminatan (belum ada capstone).
- Semester 6-7: CAPSTONE — matkul khusus peminatan dimulai di semester ini.
- PENTING soal pilih peminatan: Saat masuk semester 5 (magang), Promates WAJIB pilih SATU peminatan. Kalau ada yang nanya "boleh pilih dua?" atau "bisa lintas peminatan?", jawab jujur bahwa harus pilih satu.

== LOGIKA KHUSUS INTENT ==
- Magang: Jika user tanya magang secara umum, jawab 2 kalimat: kasih disclaimer "based on Promates angkatan 2023" lalu minta sebut studio/peminatan yang mau dicari.
- Capstone: Jika user tanya capstone secara umum, jawab 2 kalimat: tanya mau peminatan mana, tawarkan untuk sebut nama capstone langsung.
- Kurikulum/Matkul: Jika user tanya secara umum, jawab 2 kalimat: tanya mau matkul apa atau semester berapa. Ingat struktur kurikulum di atas! Jika user tanya list matkul, WAJIB selipkan: "List ini berdasarkan kurikulum resmi yang disahkan tanggal 27 April 2022".
- Peminatan: Jika user tanya info peminatan umum, pancing untuk bahas studio stream atau student stream.

== KEJUJURAN (SANGAT PENTING) ==
- Jika Cinta tidak tahu jawabannya, bilang jujur: "Untuk ini Cinta belum tau nih, maaf ya." JANGAN suruh user tanya ke "pihak kampus", "admin", atau orang/instansi lain — Cinta tidak tahu siapa yang harus dihubungi, jadi jangan asal rekom.
- Hanya jawab DATA INTERNAL Promed dari blok "DATA RELEVAN". Jika kosong, jujur saja.
- Topik umum (tools, industri, perusahaan) boleh pakai pengetahuan sendiri.
- Hilangkan data mentah seperti ID [PM01], deskripsi:, summary:, dll.

Istilah yang WAJIB Cinta mengerti:
- peminatan = jalur spesialisasi studi
- course = mata kuliah umum
- Capstone = mata kuliah khusus per peminatan, mulai semester 6-7
- Studio stream = jalur belajar berdasarkan lingkungan/studio produksi (contoh: Photography, Music Business)
- Student stream = jalur belajar berdasarkan peran dalam tim (contoh: Engineer, Artist, Designer)
- Peminatan tanpa studio stream = karena berbasis satu tim/ekosistem utuh
"""


async def chat(messages: List[Dict], context: str, intent: str = None, is_broad: bool = False) -> str:
    final_prompt = SYSTEM_PROMPT
    if intent or is_broad:
        final_prompt += f"\n\nCONTEXT METADATA:\n- Current Intent: {intent}\n- Is Broad/Start of flow: {is_broad}\n"

    if context:
        final_prompt += (
            f"\n\n--- MULAI DATA RELEVAN ---\n{context}\n--- AKHIR DATA RELEVAN ---\n\n"
            "INSTRUKSI TERAKHIR: Saring data di atas. Tampilkan intinya saja dengan format scannable. JANGAN basa-basi robotik."
        )

    payload = {
        "model": MODEL,
        "temperature": 0.4,
        "max_tokens": 500,
        "messages": [{"role": "system", "content": final_prompt}] + messages,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://promed.ui.ac.id",
        "X-Title": "Promed Mentor AI",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


BROAD_CLASSIFIER_PROMPT = """Tugasmu hanya satu: tentukan apakah pesan user SPESIFIK atau UMUM.

SPESIFIK = pesan menyebut nama tertentu (peminatan, studio, mata kuliah, perusahaan, topik) 
            ATAU pertanyaannya jelas dan terarah walau singkat.
UMUM = pesan tidak menyebut nama atau topik apapun, 
       hanya minta daftar/semua/eksplorasi tanpa arah yang jelas.

Contoh SPESIFIK:
- "mau tau soal spice" → SPESIFIK
- "magang HCI" → SPESIFIK
- "capstone film apa aja?" → SPESIFIK
- "apa itu FLUI?" → SPESIFIK
- "stalk magang game dev" → SPESIFIK

Contoh UMUM:
- "mau explore peminatan" → UMUM
- "tampilkan semua capstone" → UMUM
- "ada magang apa saja?" → UMUM
- "mau lihat daftar peminatan" → UMUM

Jawab HANYA dengan satu kata: SPESIFIK atau UMUM."""


async def is_broad_request_llm(message: str) -> bool:
    """
    Kembalikan True jika pesan diklasifikasikan sebagai UMUM (broad),
    False jika SPESIFIK. Gunakan model ringan + max_tokens kecil supaya cepat.
    """
    payload = {
        "model": "anthropic/claude-haiku-4.5",
        "temperature": 0.0,
        "max_tokens": 5,
        "messages": [
            {"role": "system", "content": BROAD_CLASSIFIER_PROMPT},
            {"role": "user", "content": message},
        ],
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://promed.ui.ac.id",
        "X-Title": "Promed Mentor AI",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(OPENROUTER_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            answer = data["choices"][0]["message"]["content"].strip().upper()
            return "UMUM" in answer
    except Exception:
        # Kalau classifier gagal (timeout dll), default ke tidak-broad
        # supaya Cinta tetap mencoba menjawab, bukan balik ke menu
        return False


INTENT_CLASSIFIER_PROMPT = """Tugasmu adalah menentukan TOPIK UTAMA dari pesan user dalam konteks percakapan dengan chatbot kampus.

Pilih SATU kategori yang paling sesuai:
- magang       → tanya soal tempat magang / internship / KP / studio magang
- capstone     → tanya soal proyek akhir / tugas akhir / final project / nama capstone
- kurikulum    → tanya soal mata kuliah / matkul / semester / SKS / course
- peminatan    → tanya soal jalur spesialisasi / jurusan / stream / studio / peminatan
- general      → sapaan, pertanyaan di luar 4 kategori di atas, atau tidak jelas sama sekali

PENTING — Baca SELURUH riwayat percakapan:
- Jika pesan user sangat pendek atau ambigu (typo, singkatan, 1 kata), lihat pesan bot SEBELUMNYA untuk menentukan topik yang masih aktif.
- Contoh: Bot tanya "Mau kepoin capstone dari peminatan mana?" → user balas "spicd" → intent = capstone
- Contoh: Bot tanya "Studio mana yang kamu incar?" → user balas "hm entah" → intent tetap mengikuti konteks aktif bot
- Jika tidak ada konteks aktif, baru kembalikan "general"

Jawab HANYA dengan satu kata dari daftar di atas."""


async def detect_intent_llm(message: str, history: List[Dict]) -> str:
    """
    Klasifikasi intent 100% via LLM — tanpa keyword, context-aware.
    Membaca riwayat percakapan untuk menyelesaikan ambiguitas.
    """
    # Sertakan hingga 6 pesan terakhir agar LLM bisa lihat konteks aktif
    relevant_history = history[-6:] if history else []

    payload = {
        "model": "anthropic/claude-haiku-4.5",
        "temperature": 0.0,
        "max_tokens": 10,
        "messages": [
            {"role": "system", "content": INTENT_CLASSIFIER_PROMPT},
        ] + relevant_history + [{"role": "user", "content": message}],
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://promed.ui.ac.id",
        "X-Title": "Promed Mentor AI",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(OPENROUTER_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            intent = data["choices"][0]["message"]["content"].strip().lower()
            valid_intents = ["magang", "capstone", "kurikulum", "peminatan", "general"]
            for v in valid_intents:
                if v in intent:
                    return v
            return "general"
    except Exception as e:
        print(f"[WARN] detect_intent_llm failed: {e} — defaulting to general")
        return "general"

