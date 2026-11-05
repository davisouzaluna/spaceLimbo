"""Persistência das playlists em SQLite (módulo sqlite3 da biblioteca padrão)."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    duration    INTEGER NOT NULL DEFAULT 0,
    thumbnail   TEXT NOT NULL DEFAULT '',
    added_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_playlist ON tracks(playlist_id, position);
"""


@contextmanager
def db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with db() as c:
        c.executescript(SCHEMA)


# ---------- playlists ----------

def list_playlists() -> list[dict]:
    with db() as c:
        rows = c.execute(
            """SELECT p.id, p.name, COUNT(t.id) AS count, COALESCE(SUM(t.duration), 0) AS duration
               FROM playlists p LEFT JOIN tracks t ON t.playlist_id = p.id
               GROUP BY p.id ORDER BY p.name COLLATE NOCASE"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_playlist(playlist_id: int) -> dict | None:
    with db() as c:
        row = c.execute("SELECT id, name FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
    return dict(row) if row else None


def get_playlist_by_name(name: str) -> dict | None:
    with db() as c:
        row = c.execute("SELECT id, name FROM playlists WHERE name = ?", (name.strip(),)).fetchone()
    return dict(row) if row else None


def create_playlist(name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("O nome da playlist não pode ser vazio.")
    try:
        with db() as c:
            cur = c.execute("INSERT INTO playlists (name, created_at) VALUES (?, ?)", (name, time.time()))
            return {"id": cur.lastrowid, "name": name}
    except sqlite3.IntegrityError:
        raise ValueError(f"Já existe uma playlist chamada “{name}”.") from None


def rename_playlist(playlist_id: int, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("O nome da playlist não pode ser vazio.")
    try:
        with db() as c:
            c.execute("UPDATE playlists SET name = ? WHERE id = ?", (name, playlist_id))
    except sqlite3.IntegrityError:
        raise ValueError(f"Já existe uma playlist chamada “{name}”.") from None


def delete_playlist(playlist_id: int) -> None:
    with db() as c:
        c.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))


# ---------- músicas ----------

def get_tracks(playlist_id: int) -> list[dict]:
    with db() as c:
        rows = c.execute(
            "SELECT id, title, url, duration, thumbnail FROM tracks WHERE playlist_id = ? ORDER BY position",
            (playlist_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_tracks(playlist_id: int, tracks: list[dict]) -> int:
    with db() as c:
        start = c.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM tracks WHERE playlist_id = ?", (playlist_id,)
        ).fetchone()[0]
        now = time.time()
        c.executemany(
            """INSERT INTO tracks (playlist_id, position, title, url, duration, thumbnail, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (playlist_id, start + i, t["title"], t["url"], int(t.get("duration") or 0), t.get("thumbnail") or "", now)
                for i, t in enumerate(tracks)
            ],
        )
    return len(tracks)


def remove_track(track_id: int) -> None:
    with db() as c:
        c.execute("DELETE FROM tracks WHERE id = ?", (track_id,))


def reorder_tracks(playlist_id: int, ordered_ids: list[int]) -> None:
    with db() as c:
        existing = {r[0] for r in c.execute("SELECT id FROM tracks WHERE playlist_id = ?", (playlist_id,))}
        if set(ordered_ids) != existing or len(ordered_ids) != len(existing):
            raise ValueError("A lista de músicas mudou; recarregue o painel.")
        c.executemany("UPDATE tracks SET position = ? WHERE id = ?", [(i, tid) for i, tid in enumerate(ordered_ids)])
