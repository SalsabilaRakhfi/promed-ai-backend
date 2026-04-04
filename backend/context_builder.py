from typing import List, Dict

MAX_CONTEXT_LENGTH = 20000
SKIP_KEYS = {"id", "ID", "no", "No", "nomor", "peminatan_id"}

def build_context(rows: List[Dict], intent: str = "umum") -> str:
    if not rows:
        return ""
        
    banned_keys_for_lists = {"deskripsi", "description", "detail", "catatan", "penjelasan", "fokus", "kompetensi"}
    
    parts = []
    for i, row in enumerate(rows, 1):
        lines = [f"[{i}]"]
        for k, v in row.items():
            if k in SKIP_KEYS or not str(v).strip():
                continue
                
            # Fisik STRIP data deskriptif saat diminta list agar Cinta tidak punya bahasan buat cericit.
            if intent in ["capstone", "magang"] and any(b in k.lower() for b in banned_keys_for_lists):
                continue
                
            lines.append(f"{k}: {v}")
        parts.append("\n".join(lines))
        
    context = "\n\n".join(parts)
    return context[:MAX_CONTEXT_LENGTH]
