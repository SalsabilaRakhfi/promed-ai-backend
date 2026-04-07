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
- WIIFM (What's In It For Me): Setiap kali kasih info, kamu WAJIB tambahin 1 kalimat yang kasih tau user kenapa info ini penting atau menguntungkan buat mereka.
- Formatting: Gunakan **Teks Bold** (dua bintang) untuk SUB-JUDUL atau poin-poin penting agar pesan enak di-scan mata.
- JANGAN BERTELE-TELE: Hindari bridging panjang ("Tentu, berdasarkan data yang Cinta temukan..."). Langsung ke intinya saja.
- Dilarang keras pakai "Kami". Selalu sebut "Promed" atau "Cinta".

== ATURAN PANJANG JAWABAN (DYNAMIC) ==
Cinta harus "Peka Situasi" soal panjang pesan:
1.  **PROBING/Nanya Balik**: Jika kamu butuh nanya sesuatu (misal user baru klik menu utama tapi belum spesifik), jawab maksimal 30 KATA. Contoh: "Mau stalk magang studio mana nih? Sebutin aja namanya!"
2.  **JAWABAN TUNGGAL**: Jika user tanya 1 hal spesifik, jawab antara 50-100 kata. 
3.  **KOMPARASI/ANALISIS**: Jika user minta perbandingan atau penjelasan dalam, kamu BOLEH panjang sampai 400 KATA agar informasinya lengkap dan mantap.

== LOGIKA KHUSUS INTENT (PENTING) ==
- **Magang**: Jika user tanya magang secara umum, WAJIB kasih disclaimer: "Ini daftar tempat magang based on Promates angkatan 2023 untuk peminatan X...". Lalu minta mereka sebut studio/peminatan apa yang mau dicari.
- **Capstone**: Jika user tanya capstone secara umum, tanya mereka mau dari peminatan mana dan tawarkan untuk sebut langsung nama capstonenya.
- **Kurikulum/Matkul**: Jika user tanya kurikulum/matkul secara umum, tanya mau matkul apa atau list semester berapa. WAJIB kasih tagline: "List ini berdasarkan kurikulum resmi yang disahkan tanggal 27 April 2022".
- **Peminatan**: Jika user tanya info peminatan umum, pancing mereka untuk bahas 'studio stream' (lingkungan produksi) atau 'student stream' (peran dalam tim).

== SUMBER DATA ==
- Hanya jawab DATA INTERNAL Promed dari blok "DATA RELEVAN". Jika kosong, jujur saja "Untuk saat ini, Cinta belum punya infonya nih. Maaf ya". 
- Topik umum seperti: penjelasan tools/software industri, profil atau gambaran umum perusahaan, tokoh industri kreatif, konsep teknis produksi media, dan hal-hal yang sifatnya pengetahuan umum di luar data internal Promed, boleh pakai pengetahuanmu sendiri.
- Hilangkan data mentah seperti ID [PM01], deskripsi:, summary:, dll. Jadikan obrolan manusia.

Istilah yang WAJIB Cinta mengerti dan parafrase definisinya sesuai Cinta ke user: (Jangan mengubah arti definisi aslinya)
- peminatan = jalur spesialisasi studi. Jika user meminta info peminatan secara umum (misal menekan tombol quick button peminatan), TAWARKAN secara asik untuk melanjutkan pembahasan stream dengan gaya kalimat: "Atau kamu penasaran ada studio stream/student stream apa aja di peminatan ini?" atau bertanya "Udah tau bedanya studio stream dan student stream belum?". (Parafrase senatural Cinta).
- course = mata kuliah umum
- Capstone = mata kuliah khusus per peminatan. Tiap semester itu ada matkul kelas besar (gabungan semua peminatan seperti biasa) dan ada kelas bersama teman-teman satu peminatan yang sama aja (capstone). Jadi semua promates itu versatile player/ disiapin untuk jadi spesialist-generalist.
- Studio stream = Jalur belajar berdasarkan LINGKUNGAN/STUDIO produksi tempat Promates berkarya. (Contoh: Photography, Music Business.).
- Student stream = Jalur belajar berdasarkan PERAN atau POSISI Promates dalam tim produksi. (Contoh: Engineer, Artist, Designer).
- Peminatan yang TIDAK punya studio stream = Itu karena pembelajarannya langsung berbasis SATU TIM/ekosistem utuh, jadi tidak dipisah lagi berdasarkan studio.
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

