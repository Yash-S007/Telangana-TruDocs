"""In-memory village hierarchy loader and search.

Loaded once at first access (lru_cache) from the pre-scraped JSON files.
Returns empty list gracefully if the file doesn't exist yet so the app
starts fine even before the scrape completes.
"""
import json
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def _pattadar() -> list[dict]:
    path = _DATA_DIR / "pattadar_hierarchy.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _adangal() -> list[dict]:
    path = _DATA_DIR / "adangal_hierarchy.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _market_value() -> list[dict]:
    path = _DATA_DIR / "market_value_hierarchy.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _prohibited_lands() -> list[dict]:
    path = _DATA_DIR / "prohibited_lands_hierarchy.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def search_pattadar_villages(q: str, limit: int = 15) -> list[dict]:
    if len(q) < 2:
        return []
    q_lower = q.lower()
    # Prefix matches first, then substring matches
    data = _pattadar()
    prefix = [r for r in data if r["village"].lower().startswith(q_lower)]
    rest = [r for r in data if not r["village"].lower().startswith(q_lower) and q_lower in r["village"].lower()]
    return (prefix + rest)[:limit]


def search_adangal_villages(q: str, limit: int = 15) -> list[dict]:
    if len(q) < 2:
        return []
    q_lower = q.lower()
    data = _adangal()
    prefix = [r for r in data if r["village"].lower().startswith(q_lower)]
    rest = [r for r in data if not r["village"].lower().startswith(q_lower) and q_lower in r["village"].lower()]
    return (prefix + rest)[:limit]


def search_market_value_villages(q: str, limit: int = 15) -> list[dict]:
    if len(q) < 2:
        return []
    q_lower = q.lower()
    data = _market_value()
    prefix = [r for r in data if r["village"].lower().startswith(q_lower)]
    rest = [r for r in data if not r["village"].lower().startswith(q_lower) and q_lower in r["village"].lower()]
    return (prefix + rest)[:limit]


def search_prohibited_lands_villages(q: str, limit: int = 15) -> list[dict]:
    if len(q) < 2:
        return []
    q_lower = q.lower()
    data = _prohibited_lands()
    prefix = [r for r in data if r["village"].lower().startswith(q_lower)]
    rest = [r for r in data if not r["village"].lower().startswith(q_lower) and q_lower in r["village"].lower()]
    return (prefix + rest)[:limit]
