# Dokumentasi Promed Mentor AI (Estella)

Catatan ini merupakan rangkuman dari arsitektur, komponen, dan cara kerja dari chatbot **Promed Mentor AI (Estella)** berdasarkan _source code_ yang ada pada folder `Promed_ai2`.

---

## 1. Arsitektur Umum & Stack Teknologi
Promed AI dibangun menggunakan pendekatan **RAG (Retrieval-Augmented Generation)** secara spesifik untuk kasus akademik (kurikulum, peminatan, magang, capstone).
- **Backend Framework:** FastAPI (Python)
- **Model LLM:** Claude Haiku API (via OpenRouter)
- **Knowledge Base (Database):** Google Sheets (di-load via library `gspread`)
- **Frontend / Client:** Widget HTML standalone & embed WordPress
- **Memori:** In-memory dictionary list (`deque`) untuk session tracking
- **Deployment Strategy:** Dioptimasi untuk Railway / Fly.io

---

## 2. Struktur Direktori Utama

- `backend/main.py`: Titik masuk (entry point) aplikasi FastAPI. Berisi *routing* `/chat` dan logika *orchestration* gabungan antara pencarian konteks dan pemanggilan OpenRouter.
- `backend/sheets_loader.py`: Modul untuk menarik data asli dari Google Sheets. Data ini otomatis di-*cache* selama 10 menit untuk mencegah *rate limit* Google API.
- `backend/retriever.py`: Mesin pencari internal. Digunakan untuk mencocokkan kata kunci pertanyaan (query) dari *user* dengan data *rows* dari Google Sheets. Mendukung mekanisme *fuzzy match*.
- `backend/context_builder.py`: Modul yang mengubah kumpulan dari hasil *retrieval* menjadi teks agar muat dalam *prompt* LLM.
- `backend/memory.py`: Menyimpan riwayat obrolan maksimal 40 pesan per `session_id`.
- `backend/openrouter_service.py`: Mengatur panggilan API Claude dan di sinilah letak **System Prompt Utama** ("Persona Estella").
- `frontend/widget.html`: Antarmuka *chat* di website untuk berinteraksi dengan AI ini.

---

## 3. Cara Kerja Sistem RAG (Alur Eksekusi Chat)

Ketika *user* mengirimkan pesan ke `/chat`, berikut adalah rentetan peristiwanya:

### A. Pre-processing & Context Rollover (`main.py`)
1. Pesan masuk menggunakan `session_id` tertentu.
2. Filter typo kecil, seperti "gim" otomatis di-translate jadi "game".
3. **Context Rollover:** Bot mengeksekusi metode heuristik pelacakan percakapan masa lalu (riwayat). Misalnya, bot mendeteksi bahwa percakapan saat ini sedang membicarakan "HCI" (Human Computer Interaction), maka saat sistem ditanya "kapan matkul ini?", *query* pencarian internal ditambahkan teks "HCI" secara transparan.

### B. Menarik Data Google Sheets (`sheets_loader.py` & `main.py`)
Sistem menarik 6 lembar (sheet) spesifik:
- `peminatan_master`
- `curriculum_course_master`, `course_description_detail`
- `capstone_master`, `capstone_weekly_detail`
- `internship_reference_2023`

Untuk efisiensi, data dari `peminatan_master` "ditempelkan" (*denormalized joined*) ke setiap data baris (*row*) *curriculum*, *internship*, dan *capstone* berdasarkan `peminatan_id`. Semuanya ini disimpan dalam **Cache selama 10 Menit**.

### C. Retreival & Pencarian Cerdas (`retriever.py`)
Menggunakan **Dual-Pool Retrieval**: 
*Data Kurikulum* dan *Data Magang* sengaja dipisahkan *pool*-nya. Backend akan menilai apakah pertanyaan ada unsur kata-kata magang (`["magang", "internship", "perusahaan", dst]`).
- Jika iya, porsi pencarian data magang (Top-K) diperbesar.
- *Retriever* memecah kalimat *user*, mengabaikan *stopwords* (dan, yang, ke, dll), lalu melakukan **Exact Substring Match** serta **Fuzzy Matching** ke dalam masing-masing baris data. Kata di kolom tertentu seperti `nama_mata_kuliah` atau `peminatan` mendapatkan skor dobel (*boosted*).

### D. Pembangunan Konteks Teks (`context_builder.py`)
Baris-baris data sheet yang dapat nilai relevansi tertinggi (Top-K) lantas diubah menjadi teks sederhana. 
> *Catatan Menarik:* Tersedia mekanisme filter (*Fisik Strip*) yang sengaja **menghapus kolom-kolom deskriptif panjang** apabila topik yang dibahas adalah "capstone" atau "magang", agar LLM menjawab via urutan sederhana (List) ketimbang *ngelantur*.

### E. Eksekusi LLM & Persona Injection (`openrouter_service.py`)
Membangun instruksi kepada Claude dengan menyusun `System Prompt` Estella.
Persona Estella dikonstruksi secara masif:
- Gen-Z, kasual, "Estella", "kamu/lo" (Dilarang pakai kata "kami").
- Memiliki sifat **Teguh Pendirian**: Diinstruksikan keras agar tidak sembarangan bilang "maaf" terpengaruh oleh keraguan *user* jika datanya sesuai di *database* kampus.
- Konteks kurikulum asli 13 sheet yang didapat dari poin (D) dimasukkan ("inject") langsung di parameter sistem bahwa ini adalah data "Database Kampus".

### F. Menyimpan Log Obrolan
Perbincangan disimpan ke riwayat `backend/memory.py` saat itu juga dan juga ditulis format permanennya ke file `logs/chat_logs.json` untuk keperluaan analisis dan validasi.

---

## 4. Keunikan & Fitur Pintar

1. **Dual-Pool Search (Anti-Tenggelam):** Baris data internship (magang) berisiko sulit ditemukan apabila digabung dengan kurikulum karena datanya sedikit, sehingga sistem memperlakukannya dalam kolam kompetisi pencarian yang diisolasi.
2. **Context Rollover:** Menyelesaikan masalah RAG di mana pengguna sering kali memotong subjek. (Tanya "Apa itu HCI", lalu *chat* ke-2 tanya "magangnya di mana?").
3. **Anti Cache-Poisoning:** Sheets hanya di-cache jika semua *request data* Google berhasil ditarik 100%. Mencegah aplikasi secara tiba-tiba kembali ke mode pasif merespons tidak mendeteksi data kurikulum.
4. **Safety Filter - Railway Keys:** Sengaja disediakan logika `_parse_service_account_json` super defensif untuk memotong error karakter *backslash-n* (newline liar) spesifik karena anomali platform deploy di Railway.
5. **Akurasi Persona Konstan:** Prompts yang dengan ketat melarang AI untuk mengarahkan pengguna ke kating/dosen ("Mencegah Hallucination HelpDesk").

Demikian rangkuman analisis struktur Promed AI v2. Jika ada area bot tertentu yang ingin dikembangkan lagi, catatan ini bisa dijadikan dasar logika yang kuat.
