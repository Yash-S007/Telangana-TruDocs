"""In-memory village hierarchy loader and search.

Loaded once at first access (lru_cache) from the pre-scraped JSON files.
Returns empty list gracefully if the file doesn't exist yet so the app
starts fine even before the scrape completes.
"""
import json
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(filename: str) -> list[dict]:
    path = _DATA_DIR / filename
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _pattadar() -> list[dict]:
    return _load("pattadar_hierarchy.json")


@lru_cache(maxsize=1)
def _adangal() -> list[dict]:
    return _load("adangal_hierarchy.json")


@lru_cache(maxsize=1)
def _survey_map() -> list[dict]:
    return _load("survey_map_villages.json")


@lru_cache(maxsize=1)
def _survey_map_by_dmv() -> dict[str, dict]:
    return {r["dmv"]: r for r in _survey_map()}


@lru_cache(maxsize=1)
def _market_value() -> list[dict]:
    return _load("market_value_hierarchy.json")


@lru_cache(maxsize=1)
def _prohibited_lands() -> list[dict]:
    return _load("prohibited_lands_hierarchy.json")


def survey_map_village(dmv: str) -> dict | None:
    return _survey_map_by_dmv().get(dmv)


def _search(data: list[dict], q: str, limit: int = 15) -> list[dict]:
    if len(q) < 2:
        return []
    q_lower = q.lower()
    prefix = [r for r in data if r["village"].lower().startswith(q_lower)]
    rest = [r for r in data if not r["village"].lower().startswith(q_lower) and q_lower in r["village"].lower()]
    return (prefix + rest)[:limit]


def search_pattadar_villages(q: str, limit: int = 15) -> list[dict]:
    return _search(_pattadar(), q, limit)


def search_adangal_villages(q: str, limit: int = 15) -> list[dict]:
    return _search(_adangal(), q, limit)


def search_survey_map_villages(q: str, limit: int = 15) -> list[dict]:
    return _search(_survey_map(), q, limit)


def search_market_value_villages(q: str, limit: int = 15) -> list[dict]:
    return _search(_market_value(), q, limit)


def search_prohibited_lands_villages(q: str, limit: int = 15) -> list[dict]:
    return _search(_prohibited_lands(), q, limit)
