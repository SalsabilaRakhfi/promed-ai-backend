import sys
from pathlib import Path
sys.path.append('/Users/salsabilarakhfi/Documents/Promed_ai2/backend')

import asyncio
from main import (
    load_sheet, get_sheets_for_intent, _infer_selected_peminatan_label,
    _get_peminatan_id, filter_by_peminatan_id, _extract_unique_values
)

async def test():
    msg = "capstone yang ada di peminatan FLUI"
    msg_lower = msg.lower()
    
    intent = "capstone"
    sheet_names = get_sheets_for_intent(intent)
    all_rows = []
    for sheet_name in sheet_names:
        all_rows.extend(load_sheet(sheet_name))
        
    master_rows = load_sheet("peminatan_master")
    peminatan_names = _extract_unique_values(
        master_rows,
        candidate_keys=["nama_peminatan", "peminatan", "focus", "nama_fokus", "nama_jurusan"],
        limit=30,
    )
    
    inferred_label = _infer_selected_peminatan_label(msg_lower, peminatan_names, master_rows)
    print("Inferred Label:", inferred_label)
    
    pid = _get_peminatan_id(inferred_label, master_rows)
    print("PID:", pid)
    
    top_rows = filter_by_peminatan_id(all_rows, pid)
    print("Top Rows Count:", len(top_rows))
    if len(top_rows) == 0:
        # What DOES capstone_master have?
        print("First row of capstone_master:", all_rows[0] if all_rows else "Empty")

asyncio.run(test())
