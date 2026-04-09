import re
from difflib import SequenceMatcher
from typing import List, Dict, Optional

BOOST_COLUMNS = {"nama_mata_kuliah", "peminatan", "focus", "nama_peminatan", "nama_capstone", "nama_perusahaan", "studio_stream", "course_type"}
PEMINATAN_COLUMNS = {"nama_peminatan", "peminatan", "focus", "nama_fokus", "nama_jurusan", "nama_studio", "studio", "studio_stream", "student_stream"}
TOP_K = 15

# Kata "Stopwords" yang tidak penting dalam searching
STOPWORDS = {"yang", "di", "ke", "dari", "dan", "atau", "untuk", "dengan", "buat", "ada", "apa", "aja", "mau", "dong", "sih", "kok", "itu", "ini"}

def _get_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _score_row(row: Dict, query_words: List[str]) -> float:
    score = 0.0
    for col, val in row.items():
        val_str = str(val).lower().strip()
        if not val_str:
            continue
            
        # Punctuation replaced with space to preserve boundaries ("OX-Laboratory" -> "OX Laboratory")
        val_clean = re.sub(r'[^\w\s]', ' ', val_str)
        col_lower = col.lower()
        col_clean = re.sub(r'[^\w\s]', ' ', col_lower)
        
        boost = 2.0 if col_lower in BOOST_COLUMNS else 1.0
        
        # Ekstrak kata-kata dari sel (tokenization)
        val_tokens = val_clean.split()
        
        for word in query_words:
            if word in STOPWORDS:
                continue
                
            # Exact Substring Match (menangkap singkatan atau potongan kata utuh)
            if word in val_str or word in val_clean or word in col_lower or word in col_clean:
                score += boost
                continue
                
            # Fuzzy match untuk mentolerir typo
            # Bandingkan word dengan tiap token di val_tokens
            for vt in val_tokens:
                # Filter selisih panjang ekstrim untuk efisiensi
                if abs(len(vt) - len(word)) <= 4:
                    sim = _get_similarity(word, vt)
                    if sim > 0.70:
                        score += (boost * sim)
                        break  # cukup 1 match saja per word untuk kolom ini
    return score

def retrieve(rows: List[Dict], query: str, top_k: int = TOP_K) -> List[Dict]:
    if not rows:
        return []
    # HAPUS pengecualian len(w) > 2
    query_clean = re.sub(r'[^\w\s]', ' ', query.lower())
    query_words = [w for w in query_clean.split() if w]
    
    if not query_words:
        return rows[:top_k]
        
    scored = [(row, _score_row(row, query_words)) for row in rows]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = [row for row, score in scored[:top_k] if score > 0.0]
    return top

def filter_by_label(rows: List[Dict], label: Optional[str]) -> List[Dict]:
    """
    Hard-filter rows: hanya kembalikan baris yang kolom peminatan-nya
    mengandung `label` (case-insensitive, toleran tanda baca seperti & vs dan, dan fuzzy).
    Kalau tidak ada yang lolos filter, kembalikan rows semula (fallback).
    """
    if not label or not rows:
        return rows

    label_clean = re.sub(r'[^\w\s]', ' ', label.lower()).strip()
    label_words = [w for w in label_clean.split() if w not in STOPWORDS]
    
    if not label_words:
        return rows

    filtered = []
    for row in rows:
        for col in PEMINATAN_COLUMNS:
            val = row.get(col)
            if not val:
                continue
            val_clean = re.sub(r'[^\w\s]', ' ', str(val).lower())
            
            # Row lolos kalau semua word dari label ada (sub string atau fuzzy > 0.7)
            match_all = True
            for lw in label_words:
                if lw in val_clean:
                    continue
                # Coba fuzzy per token
                fuzzy_matched = False
                for vt in val_clean.split():
                    if abs(len(vt) - len(lw)) <= 3 and _get_similarity(lw, vt) > 0.75:
                        fuzzy_matched = True
                        break
                if not fuzzy_matched:
                    match_all = False
                    break
                    
            if match_all:
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
