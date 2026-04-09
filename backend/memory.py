from collections import deque
from typing import List, Dict

MAX_MESSAGES = 40

# In-memory store per session_id
_stores: Dict[str, deque] = {}


def get_history(session_id: str) -> List[Dict]:
    return list(_stores.get(session_id, deque(maxlen=MAX_MESSAGES)))


def add_message(session_id: str, role: str, content: str):
    if session_id not in _stores:
        _stores[session_id] = deque(maxlen=MAX_MESSAGES)
    _stores[session_id].append({"role": role, "content": content})


def clear(session_id: str):
    if session_id in _stores:
        del _stores[session_id]
