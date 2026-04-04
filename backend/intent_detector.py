import re
from typing import List

INTENT_MAP = {
    "kurikulum": ["kurikulum", "matkul", "mata kuliah", "kuliah", "kelas", "semester", "smt", "smst", "sem", "sks", "course"],
    "capstone": ["capstone", "tugas akhir", "ta", "proyek akhir", "final project"],
    "magang": ["magang", "internship", "kerja praktik", "kp", "pkl", "industri"],
    "peminatan": ["peminatan", "spesialisasi", "jurusan", "track", "jalur", "minat"],
}

SHEET_MAP = {
    "general": ["peminatan_master"],
    "peminatan": ["peminatan_master"],
    "kurikulum": ["curriculum_course_master", "course_description_detail"],
    "capstone": ["capstone_master", "capstone_weekly_detail"],
    "magang": ["internship_reference_2023"],
}

DEFAULT_INTENT = "general"


def detect_intent(message: str) -> str:
    msg = message.lower()
    for intent, keywords in INTENT_MAP.items():
        for kw in keywords:
            if len(kw) <= 3:
                pattern = r'\b' + re.escape(kw) + r'\b'
            else:
                pattern = r'\b' + re.escape(kw)
            if re.search(pattern, msg):
                return intent
    return DEFAULT_INTENT


def get_sheets_for_intent(intent: str) -> List[str]:
    return SHEET_MAP.get(intent, SHEET_MAP[DEFAULT_INTENT])
