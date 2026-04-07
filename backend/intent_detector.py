from typing import List

# Sheet mapping berdasarkan intent yang dideteksi LLM
SHEET_MAP = {
    "general": ["peminatan_master"],
    "peminatan": ["peminatan_master"],
    "kurikulum": ["curriculum_course_master", "course_description_detail"],
    "capstone": ["capstone_master", "capstone_weekly_detail"],
    "magang": ["internship_reference_2023"],
}

DEFAULT_INTENT = "general"


def get_sheets_for_intent(intent: str) -> List[str]:
    return SHEET_MAP.get(intent, SHEET_MAP[DEFAULT_INTENT])
