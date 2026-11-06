"""Small SQLite + file caches for MTG lookups (Scryfall cards, MTGJSON files)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import db

_lock = threading.Lock()
_DB = db.DB_PATH.parent / "mtg_cache.db"
FILE_DIR = db.DB_PATH.parent / "mtg"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cards (key TEXT PRIMARY KEY, data TEXT NOT NULL, fetched_at REAL NOT NULL)"
    )
    return conn


def get_card(key: str, ttl: float) -> dict | None:
    """Cached card summary; ``{}`` means "known not to exist"; None means not cached/expired."""
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT data, fetched_at FROM cards WHERE key = ?", (key,)).fetchone()
        conn.close()
    if not row or time.time() - row[1] > ttl:
        return None
    return json.loads(row[0])


def set_card(key: str, data: dict) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO cards (key, data, fetched_at) VALUES (?, ?, ?)",
            (key, json.dumps(data), time.time()),
        )
        conn.commit()
        conn.close()


def file_path(name: str) -> Path:
    FILE_DIR.mkdir(parents=True, exist_ok=True)
    return FILE_DIR / name


def read_file(name: str, max_age: float | None = None) -> bytes | None:
    path = file_path(name)
    if not path.exists():
        return None
    if max_age is not None and time.time() - path.stat().st_mtime > max_age:
        return None
    return path.read_bytes()


def write_file(name: str, data: bytes) -> None:
    path = file_path(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
