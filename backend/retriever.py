import re
from typing import List, Dict, Optional

BOOST_COLUMNS = {"nama_mata_kuliah", "peminatan", "focus", "nama_peminatan", "nama_capstone", "nama_perusahaan", "studio_stream", "course_type"}
PEMINATAN_COLUMNS = {"nama_peminatan", "peminatan", "focus", "nama_fokus", "nama_jurusan", "nama_studio", "studio", "studio_stream", "student_stream"}
TOP_K = 15


def _score_row(row: Dict, query_words: List[str]) -> float:
    score = 0.0
    for col, val in row.items():
        val_str = str(val).lower()
        val_clean = re.sub(r'[^\w\s]', '', val_str)
        col_lower = col.lower()
        col_clean = re.sub(r'[^\w\s]', '', col_lower)
        boost = 2.0 if col_lower in BOOST_COLUMNS else 1.0
        for word in query_words:
            word_clean = re.sub(r'[^\w\s]', '', word)
            if not word_clean:
                continue
            # Match query word against column value OR column header itself
            if word_clean in val_str or word_clean in val_clean or word_clean in col_lower or word_clean in col_clean:
                score += boost
    return score


def retrieve(rows: List[Dict], query: str, top_k: int = TOP_K) -> List[Dict]:
    if not rows:
        return []
    query_words = [w for w in query.lower().split() if len(w) > 2 or w.isdigit()]
    if not query_words:
        return rows[:top_k]
    scored = [(row, _score_row(row, query_words)) for row in rows]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = [row for row, score in scored[:top_k] if score > 0]
    return top


def filter_by_label(rows: List[Dict], label: Optional[str]) -> List[Dict]:
    """
    Hard-filter rows: hanya kembalikan baris yang kolom peminatan-nya
    mengandung `label` (case-insensitive, toleran tanda baca seperti & vs dan).
    Kalau tidak ada yang lolos filter, kembalikan rows semula (fallback).
    """
    if not label or not rows:
        return rows

    label_clean = re.sub(r'[^\w\s]', '', label.lower()).strip()
    label_words = [w for w in label_clean.split() if len(w) > 2]

    filtered = []
    for row in rows:
        for col in PEMINATAN_COLUMNS:
            val = row.get(col)
            if not val:
                continue
            val_clean = re.sub(r'[^\w\s]', '', str(val).lower())
            # Row lolos kalau SEMUA kata penting dari label ada di nilai kolom
            if all(w in val_clean for w in label_words):
                filtered.append(row)
                break

    # Fallback: kalau filter terlalu ketat dan tidak ada yang lolos
    return filtered if filtered else rows


def filter_by_peminatan_id(rows: List[Dict], peminatan_id: str) -> List[Dict]:
    """
    Filter data lintas sheet menggunakan Foreign Key `peminatan_id`.
    Ini paling akurat karena data magang/kurikulum mungkin miskin kata kunci (misal magang=S.P.I.C.E., dicari HCI).
    """
    if not peminatan_id or not rows:
        return rows
        
    filtered = []
    pid_clean = str(peminatan_id).strip().lower()
    for row in rows:
        val = str(row.get("peminatan_id", "")).strip().lower()
        if val == pid_clean:
            filtered.append(row)
            
    return filtered
