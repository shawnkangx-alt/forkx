"""自选股管理。"""
import json
import os
from pathlib import Path
from typing import Dict, List

_CONFIG_DIR = Path.home() / ".forkx"
_CONFIG_DIR.mkdir(exist_ok=True)
_WATCHLIST_FILE = _CONFIG_DIR / "watchlist.json"


def load_watchlist() -> List[str]:
    if not _WATCHLIST_FILE.exists():
        return []
    try:
        return json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_watchlist(codes: List[str]):
    _WATCHLIST_FILE.write_text(
        json.dumps(codes, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def add_to_watchlist(code: str) -> bool:
    codes = load_watchlist()
    if code in codes:
        return False
    codes.append(code)
    save_watchlist(codes)
    return True


def remove_from_watchlist(code: str) -> bool:
    codes = load_watchlist()
    if code not in codes:
        return False
    codes.remove(code)
    save_watchlist(codes)
    return True
