import json
import sqlite3
from pathlib import Path

import numpy as np

from wrag.chunk import Chunk

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
    project TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, mtime REAL NOT NULL,
    PRIMARY KEY (project, path)
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, project TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
    heading TEXT NOT NULL, text TEXT NOT NULL, files TEXT NOT NULL, mtime REAL NOT NULL,
    vector BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_location ON chunks (project, path);
CREATE TABLE IF NOT EXISTS commits_cursor (project TEXT PRIMARY KEY, last_hash TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def commit(self) -> None:
        self.db.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def reset(self) -> None:
        for table in ("meta", "files", "chunks", "commits_cursor"):
            self.db.execute(f"DELETE FROM {table}")

    def projects(self) -> set[str]:
        rows = self.db.execute(
            "SELECT project FROM files UNION SELECT project FROM chunks "
            "UNION SELECT project FROM commits_cursor"
        )
        return {r[0] for r in rows}

    def drop_project(self, project: str) -> None:
        for table in ("files", "chunks", "commits_cursor"):
            self.db.execute(f"DELETE FROM {table} WHERE project = ?", (project,))

    def file_hashes(self, project: str) -> dict[str, str]:
        rows = self.db.execute("SELECT path, sha256 FROM files WHERE project = ?", (project,))
        return dict(rows.fetchall())

    def put_file(
        self,
        project: str,
        path: str,
        sha256: str,
        mtime: float,
        chunks: list[Chunk],
        vectors: np.ndarray,
    ) -> None:
        self.delete_file(project, path)
        self.db.execute("INSERT INTO files VALUES (?, ?, ?, ?)", (project, path, sha256, mtime))
        self.add_chunks(chunks, vectors)

    def delete_file(self, project: str, path: str) -> None:
        self.db.execute("DELETE FROM files WHERE project = ? AND path = ?", (project, path))
        self.db.execute(
            "DELETE FROM chunks WHERE project = ? AND path = ? AND kind != 'commit'",
            (project, path),
        )

    def add_chunks(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        self.db.executemany(
            "INSERT INTO chunks (project, path, kind, heading, text, files, mtime, vector) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    c.project,
                    c.path,
                    c.kind,
                    c.heading,
                    c.text,
                    json.dumps(c.files),
                    c.mtime,
                    np.asarray(v, dtype=np.float32).tobytes(),
                )
                for c, v in zip(chunks, vectors, strict=True)
            ],
        )

    def get_cursor(self, project: str) -> str | None:
        row = self.db.execute(
            "SELECT last_hash FROM commits_cursor WHERE project = ?", (project,)
        ).fetchone()
        return row[0] if row else None

    def set_cursor(self, project: str, last_hash: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO commits_cursor VALUES (?, ?)", (project, last_hash))

    def drop_commits(self, project: str) -> None:
        self.db.execute("DELETE FROM chunks WHERE project = ? AND kind = 'commit'", (project,))
        self.db.execute("DELETE FROM commits_cursor WHERE project = ?", (project,))

    def vectors(self) -> tuple[np.ndarray, np.ndarray]:
        """Returns (chunk ids, matrix) for all chunks."""
        rows = self.db.execute("SELECT id, vector FROM chunks ORDER BY id").fetchall()
        if not rows:
            return np.zeros(0, dtype=np.int64), np.zeros((0, 0), dtype=np.float32)
        ids = np.array([r[0] for r in rows], dtype=np.int64)
        return ids, np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])

    def chunks(self, ids: list[int]) -> dict[int, Chunk]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.db.execute(
            f"SELECT id, project, path, kind, heading, text, files, mtime FROM chunks "
            f"WHERE id IN ({marks})",
            [int(i) for i in ids],
        )
        return {
            r[0]: Chunk(r[1], r[2], r[3], r[4], r[5], r[7], tuple(json.loads(r[6]))) for r in rows
        }

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT kind, COUNT(*) FROM chunks GROUP BY kind")
        return dict(rows.fetchall())
