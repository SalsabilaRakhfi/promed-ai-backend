# Promed Mentor AI — Estella

AI chatbot akademik untuk Promates (Media Production, Universitas Indonesia).

---

## Struktur

```
promed-mentor/
├── backend/
│   ├── main.py                 ← FastAPI app, endpoint /chat
│   ├── sheets_loader.py        ← Google Sheets loader (cached)
│   ├── intent_detector.py      ← Keyword-based intent mapping
│   ├── retriever.py            ← Hybrid keyword scoring
│   ├── context_builder.py      ← Row → readable context
│   ├── memory.py               ← Last-40-message session memory
│   ├── openrouter_service.py   ← OpenRouter API (Claude 3 Haiku)
│   ├── requirements.txt
│   └── .env.example
├── logs/
│   └── chat_logs.json          ← Auto-generated
├── widget.html                 ← Standalone chat widget
└── wordpress-embed.html        ← Petunjuk embed ke WordPress
```

---

## Setup

### 1. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Konfigurasi environment

```bash
cp .env.example .env
# Edit .env:
# OPENROUTER_API_KEY=...
# GOOGLE_SPREADSHEET_ID=...
# GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
```

### 3. Google Service Account

- Buat project di Google Cloud Console
- Enable Google Sheets API dan Google Drive API
- Buat Service Account → download JSON → simpan sebagai `backend/service_account.json`
- Share spreadsheet ke email service account

### 4. Jalankan server

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 5. Test widget

Buka `widget.html` di browser. Ganti `BACKEND_URL` di JS sesuai URL server.

---

## API

### POST /chat

```json
// Request
{ "message": "Apa itu peminatan film?", "session_id": "optional-uuid" }

// Response
{
  "session_id": "uuid",
  "response": "Peminatan film di Promed mencakup...",
  "intent": "peminatan",
  "latency_seconds": 1.23
}
```

---

## Deploy ke Production

Rekomendasi: **Railway** atau **Fly.io**

1. Push backend ke repo
2. Set environment variables di dashboard
3. Ganti `BACKEND_URL` di widget.html dengan URL production
4. Embed di WordPress via Insert Headers and Footers plugin

---

## Sheets yang digunakan

| Sheet | Intent |
|-------|--------|
| `peminatan_master` | peminatan |
| `curriculum_course_master` | kurikulum |
| `course_description_detail` | kurikulum |
| `capstone_master` | capstone |
| `capstone_weekly_detail` | capstone |
| `internship_reference_2023` | magang |
