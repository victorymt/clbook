from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .errors import BookError


SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL COLLATE NOCASE UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    source_path TEXT NOT NULL,
    entry_path TEXT NOT NULL,
    document_type TEXT NOT NULL,
    content TEXT NOT NULL,
    position INTEGER NOT NULL,
    source_mtime REAL,
    source_size INTEGER,
    source_hash TEXT,
    resource_root TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(book_id, source_path)
);

CREATE INDEX IF NOT EXISTS documents_by_book_position
    ON documents(book_id, position, id);

CREATE TABLE IF NOT EXISTS document_resources (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    UNIQUE(document_id, source_path),
    UNIQUE(document_id, relative_path)
);

CREATE TABLE IF NOT EXISTS reader_state (
    book_id INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    last_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    theme TEXT NOT NULL DEFAULT 'light' CHECK(theme IN ('light', 'dark')),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_progress (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    scroll_ratio REAL NOT NULL DEFAULT 0 CHECK(scroll_ratio >= 0 AND scroll_ratio <= 1),
    updated_at TEXT NOT NULL
);
"""


_UNSET = object()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_data_dir() -> Path:
    configured = os.environ.get("BOOK_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "book"
    return Path.home() / ".local" / "share" / "book"


class Library:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_data_dir()).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self.root / "library.sqlite3"

    @property
    def documents_root(self) -> Path:
        return self.root / "documents"

    def document_dir(self, document_id: int) -> Path:
        return self.documents_root / str(document_id)

    def initialize(self) -> None:
        with self.connection():
            pass

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.root.mkdir(parents=True, exist_ok=True)
        self.documents_root.mkdir(exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(SCHEMA)
            self._migrate(connection)
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
        if "source_mtime" not in columns:
            connection.execute("ALTER TABLE documents ADD COLUMN source_mtime REAL")
        if "source_size" not in columns:
            connection.execute("ALTER TABLE documents ADD COLUMN source_size INTEGER")
        if "source_hash" not in columns:
            connection.execute("ALTER TABLE documents ADD COLUMN source_hash TEXT")
        if "resource_root" not in columns:
            connection.execute("ALTER TABLE documents ADD COLUMN resource_root TEXT")
        try:
            fts_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'documents_fts'"
            ).fetchone() is not None
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(title, content, content='documents', content_rowid='id')"
            )
            connection.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS documents_fts_insert AFTER INSERT ON documents BEGIN
                    INSERT INTO documents_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS documents_fts_delete AFTER DELETE ON documents BEGIN
                    INSERT INTO documents_fts(documents_fts, rowid, title, content)
                    VALUES ('delete', old.id, old.title, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS documents_fts_update AFTER UPDATE OF title, content ON documents BEGIN
                    INSERT INTO documents_fts(documents_fts, rowid, title, content)
                    VALUES ('delete', old.id, old.title, old.content);
                    INSERT INTO documents_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
                END;
                """
            )
            document_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            indexed_count = connection.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]
            if not fts_exists or document_count != indexed_count:
                connection.execute("INSERT INTO documents_fts(documents_fts) VALUES ('rebuild')")
        except sqlite3.OperationalError:
            # FTS5 is optional in some Python/SQLite builds; the search method has a safe fallback.
            pass

    @staticmethod
    def _source_metadata(path: Path) -> tuple[float | None, int | None]:
        try:
            stat = path.stat()
        except OSError:
            return None, None
        return stat.st_mtime, stat.st_size

    @staticmethod
    def _source_hash(path: Path) -> str | None:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()

    def add_book(self, title: str, description: str = "") -> sqlite3.Row:
        title = title.strip()
        if not title:
            raise BookError("Book title cannot be empty.")
        now = utc_now()
        try:
            with self.connection() as connection:
                cursor = connection.execute(
                    "INSERT INTO books(title, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (title, description.strip(), now, now),
                )
                return self.get_book(connection, str(cursor.lastrowid))
        except sqlite3.IntegrityError as error:
            raise BookError(f"A book named '{title}' already exists.") from error

    def get_book(self, connection: sqlite3.Connection, identifier: str) -> sqlite3.Row:
        row = None
        if identifier.isdigit():
            row = connection.execute("SELECT * FROM books WHERE id = ?", (int(identifier),)).fetchone()
        if row is None:
            row = connection.execute("SELECT * FROM books WHERE title = ? COLLATE NOCASE", (identifier,)).fetchone()
        if row is None:
            raise BookError(f"Book '{identifier}' was not found.")
        return row

    def list_books(self) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return connection.execute(
                """
                SELECT books.*, COUNT(documents.id) AS document_count
                FROM books
                LEFT JOIN documents ON documents.book_id = books.id
                GROUP BY books.id
                ORDER BY books.title COLLATE NOCASE, books.id
                """
            ).fetchall()

    def rename_book(self, identifier: str, title: str) -> sqlite3.Row:
        title = title.strip()
        if not title:
            raise BookError("Book title cannot be empty.")
        try:
            with self.connection() as connection:
                book = self.get_book(connection, identifier)
                connection.execute(
                    "UPDATE books SET title = ?, updated_at = ? WHERE id = ?",
                    (title, utc_now(), book["id"]),
                )
                return self.get_book(connection, str(book["id"]))
        except sqlite3.IntegrityError as error:
            raise BookError(f"A book named '{title}' already exists.") from error

    def update_book(
        self,
        identifier: str,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> sqlite3.Row:
        if title is None and description is None:
            raise BookError("Provide a title or description to update.")
        if title is not None:
            title = title.strip()
            if not title:
                raise BookError("Book title cannot be empty.")
        try:
            with self.connection() as connection:
                book = self.get_book(connection, identifier)
                resolved_title = title if title is not None else book["title"]
                resolved_description = description.strip() if description is not None else book["description"]
                connection.execute(
                    "UPDATE books SET title = ?, description = ?, updated_at = ? WHERE id = ?",
                    (resolved_title, resolved_description, utc_now(), book["id"]),
                )
                return self.get_book(connection, str(book["id"]))
        except sqlite3.IntegrityError as error:
            raise BookError(f"A book named '{title}' already exists.") from error

    def remove_book(self, identifier: str, with_documents: bool = False) -> sqlite3.Row:
        with self.connection() as connection:
            book = self.get_book(connection, identifier)
            documents = connection.execute(
                "SELECT id FROM documents WHERE book_id = ? ORDER BY position, id", (book["id"],)
            ).fetchall()
            if documents and not with_documents:
                raise BookError(
                    "This book has documents. Use --with-documents to remove its archived copies too."
                )
            document_dirs = [self.document_dir(row["id"]) for row in documents]
            connection.execute("DELETE FROM books WHERE id = ?", (book["id"],))

        for document_dir in document_dirs:
            shutil.rmtree(document_dir, ignore_errors=True)
        return book

    def list_documents(self, book_identifier: str) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
        with self.connection() as connection:
            book = self.get_book(connection, book_identifier)
            documents = connection.execute(
                """
                SELECT documents.*, COALESCE(document_progress.scroll_ratio, 0) AS scroll_ratio
                FROM documents
                LEFT JOIN document_progress ON document_progress.document_id = documents.id
                WHERE book_id = ?
                ORDER BY position, id
                """,
                (book["id"],),
            ).fetchall()
            return book, documents

    def get_document(self, connection: sqlite3.Connection, document_id: int | str) -> sqlite3.Row:
        try:
            numeric_id = int(document_id)
        except (TypeError, ValueError) as error:
            raise BookError(f"Document '{document_id}' was not found.") from error
        row = connection.execute(
            """
            SELECT documents.*, books.title AS book_title,
                   COALESCE(document_progress.scroll_ratio, 0) AS scroll_ratio
            FROM documents
            JOIN books ON books.id = documents.book_id
            LEFT JOIN document_progress ON document_progress.document_id = documents.id
            WHERE documents.id = ?
            """,
            (numeric_id,),
        ).fetchone()
        if row is None:
            raise BookError(f"Document '{document_id}' was not found.")
        return row

    def document_info(self, document_id: int | str) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
        with self.connection() as connection:
            document = self.get_document(connection, document_id)
            resources = connection.execute(
                "SELECT * FROM document_resources WHERE document_id = ? ORDER BY relative_path",
                (document["id"],),
            ).fetchall()
            return document, resources

    def insert_document(
        self,
        book_identifier: str,
        title: str,
        source_path: Path,
        document_type: str,
        content: str,
        resource_root: Path | None = None,
    ) -> tuple[sqlite3.Row, Path]:
        with self.connection() as connection:
            book = self.get_book(connection, book_identifier)
            duplicate = connection.execute(
                "SELECT id FROM documents WHERE book_id = ? AND source_path = ?",
                (book["id"], str(source_path)),
            ).fetchone()
            if duplicate:
                raise BookError(
                    f"This source is already document {duplicate['id']} in '{book['title']}'."
                )
            position = connection.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM documents WHERE book_id = ?",
                (book["id"],),
            ).fetchone()[0]
            now = utc_now()
            source_mtime, source_size = self._source_metadata(source_path)
            source_hash = self._source_hash(source_path)
            cursor = connection.execute(
                """
                INSERT INTO documents(
                    book_id, title, source_path, entry_path, document_type, content, position,
                    source_mtime, source_size, source_hash, resource_root, created_at, updated_at
                ) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book["id"], title, str(source_path), document_type, content, position,
                    source_mtime,
                    source_size,
                    source_hash,
                    str(resource_root) if resource_root else None,
                    now,
                    now,
                ),
            )
            document_id = int(cursor.lastrowid)
            connection.execute("UPDATE books SET updated_at = ? WHERE id = ?", (now, book["id"]))
            document = self.get_document(connection, document_id)
            return document, self.document_dir(document_id)

    def finish_document_import(
        self,
        document_id: int,
        entry_path: str,
        resources: list[tuple[str, str, str]],
        content: str,
    ) -> sqlite3.Row:
        with self.connection() as connection:
            document = self.get_document(connection, document_id)
            now = utc_now()
            connection.execute(
                "UPDATE documents SET entry_path = ?, content = ?, updated_at = ? WHERE id = ?",
                (entry_path, content, now, document_id),
            )
            connection.execute("DELETE FROM document_resources WHERE document_id = ?", (document_id,))
            connection.executemany(
                """
                INSERT INTO document_resources(document_id, source_path, relative_path, mime_type)
                VALUES (?, ?, ?, ?)
                """,
                [(document_id, source, relative, mime) for source, relative, mime in resources],
            )
            connection.execute("UPDATE books SET updated_at = ? WHERE id = ?", (now, document["book_id"]))
            return self.get_document(connection, document_id)

    def rename_document(self, document_id: int | str, title: str) -> sqlite3.Row:
        title = title.strip()
        if not title:
            raise BookError("Document title cannot be empty.")
        with self.connection() as connection:
            document = self.get_document(connection, document_id)
            now = utc_now()
            connection.execute(
                "UPDATE documents SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, document["id"]),
            )
            connection.execute("UPDATE books SET updated_at = ? WHERE id = ?", (now, document["book_id"]))
            return self.get_document(connection, document["id"])

    def update_document_import(
        self,
        document_id: int,
        entry_path: str,
        document_type: str,
        content: str,
        resources: list[tuple[str, str, str]],
        resource_root: Path | None = None,
    ) -> sqlite3.Row:
        with self.connection() as connection:
            document = self.get_document(connection, document_id)
            now = utc_now()
            connection.execute(
                """
                UPDATE documents
                SET entry_path = ?, document_type = ?, content = ?, source_mtime = ?, source_size = ?,
                    source_hash = ?, resource_root = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    entry_path,
                    document_type,
                    content,
                    *self._source_metadata(Path(document["source_path"])),
                    self._source_hash(Path(document["source_path"])),
                    str(resource_root) if resource_root else None,
                    now,
                    document_id,
                ),
            )
            connection.execute("DELETE FROM document_resources WHERE document_id = ?", (document_id,))
            connection.executemany(
                """
                INSERT INTO document_resources(document_id, source_path, relative_path, mime_type)
                VALUES (?, ?, ?, ?)
                """,
                [(document_id, source, relative, mime) for source, relative, mime in resources],
            )
            connection.execute("UPDATE books SET updated_at = ? WHERE id = ?", (now, document["book_id"]))
            return self.get_document(connection, document_id)

    def remove_document(self, document_id: int | str) -> sqlite3.Row:
        with self.connection() as connection:
            document = self.get_document(connection, document_id)
            connection.execute("DELETE FROM documents WHERE id = ?", (document["id"],))
            connection.execute(
                "UPDATE documents SET position = position - 1 WHERE book_id = ? AND position > ?",
                (document["book_id"], document["position"]),
            )
            connection.execute("UPDATE books SET updated_at = ? WHERE id = ?", (utc_now(), document["book_id"]))
        shutil.rmtree(self.document_dir(document["id"]), ignore_errors=True)
        return document

    def move_document(self, document_id: int | str, destination: int) -> sqlite3.Row:
        with self.connection() as connection:
            document = self.get_document(connection, document_id)
            documents = connection.execute(
                "SELECT id FROM documents WHERE book_id = ? ORDER BY position, id", (document["book_id"],)
            ).fetchall()
            if destination < 1 or destination > len(documents):
                raise BookError(f"Position must be between 1 and {len(documents)}.")
            ids = [row["id"] for row in documents]
            ids.remove(document["id"])
            ids.insert(destination - 1, document["id"])
            connection.executemany(
                "UPDATE documents SET position = ?, updated_at = ? WHERE id = ?",
                [(index, utc_now(), item_id) for index, item_id in enumerate(ids, 1)],
            )
            connection.execute("UPDATE books SET updated_at = ? WHERE id = ?", (utc_now(), document["book_id"]))
            return self.get_document(connection, document_id)

    def reorder_documents(self, book_id: int, document_ids: list[int]) -> list[sqlite3.Row]:
        with self.connection() as connection:
            book = self.get_book(connection, str(book_id))
            current = connection.execute(
                "SELECT id FROM documents WHERE book_id = ? ORDER BY position, id", (book["id"],)
            ).fetchall()
            current_ids = [row["id"] for row in current]
            if len(document_ids) != len(current_ids) or set(document_ids) != set(current_ids):
                raise BookError("The document order must contain every chapter in this book exactly once.")
            now = utc_now()
            connection.executemany(
                "UPDATE documents SET position = ?, updated_at = ? WHERE id = ?",
                [(position, now, item_id) for position, item_id in enumerate(document_ids, 1)],
            )
            connection.execute("UPDATE books SET updated_at = ? WHERE id = ?", (now, book["id"]))
            return connection.execute(
                "SELECT * FROM documents WHERE book_id = ? ORDER BY position, id", (book["id"],)
            ).fetchall()

    def get_book_for_web(self, book_id: int) -> dict[str, object]:
        with self.connection() as connection:
            book = self.get_book(connection, str(book_id))
            state = connection.execute(
                "SELECT * FROM reader_state WHERE book_id = ?", (book_id,)
            ).fetchone()
            documents = connection.execute(
                """
                SELECT documents.id, documents.title, documents.position, documents.document_type,
                       documents.source_path, documents.source_mtime, documents.source_size, documents.source_hash,
                       COALESCE(document_progress.scroll_ratio, 0) AS scroll_ratio
                FROM documents
                LEFT JOIN document_progress ON document_progress.document_id = documents.id
                WHERE documents.book_id = ?
                ORDER BY documents.position, documents.id
                """,
                (book_id,),
            ).fetchall()
            document_values = [dict(row) for row in documents]
            for item in document_values:
                if item["source_hash"] is not None:
                    item["source_stale"] = self._source_hash(Path(item["source_path"])) != item["source_hash"]
                else:
                    current_mtime, current_size = self._source_metadata(Path(item["source_path"]))
                    item["source_stale"] = item["source_mtime"] is not None and (
                        current_mtime is None
                        or current_mtime != item["source_mtime"]
                        or current_size != item["source_size"]
                    )
                item.pop("source_path", None)
                item.pop("source_mtime", None)
                item.pop("source_size", None)
                item.pop("source_hash", None)
            progress = (
                sum(float(item["scroll_ratio"] or 0) for item in document_values) / len(document_values)
                if document_values
                else 0.0
            )
            return {
                "id": book["id"],
                "title": book["title"],
                "description": book["description"],
                "theme": state["theme"] if state else "light",
                "last_document_id": state["last_document_id"] if state else None,
                "documents": document_values,
                "progress": progress,
            }

    def document_links(self, book_id: int) -> dict[str, int]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id, source_path FROM documents WHERE book_id = ?", (book_id,)
            ).fetchall()
        return {str(Path(row["source_path"]).resolve()): int(row["id"]) for row in rows}

    def is_document_stale(self, document_id: int | str) -> bool:
        document, _ = self.document_info(document_id)
        if document["source_hash"] is not None:
            return self._source_hash(Path(document["source_path"])) != document["source_hash"]
        current_mtime, current_size = self._source_metadata(Path(document["source_path"]))
        return document["source_mtime"] is not None and (
            current_mtime is None
            or current_mtime != document["source_mtime"]
            or current_size != document["source_size"]
        )

    def list_books_for_web(self) -> list[dict[str, object]]:
        return [dict(row) for row in self.list_books()]

    def update_reader_state(
        self,
        book_id: int,
        last_document_id: int | None | object = _UNSET,
        theme: str | None | object = _UNSET,
    ) -> dict[str, object]:
        if theme is not _UNSET and theme is not None and theme not in {"light", "dark"}:
            raise BookError("Theme must be 'light' or 'dark'.")
        with self.connection() as connection:
            book = self.get_book(connection, str(book_id))
            if last_document_id is not _UNSET and last_document_id is not None:
                document = self.get_document(connection, last_document_id)
                if document["book_id"] != book["id"]:
                    raise BookError("The selected document does not belong to this book.")
            current = connection.execute(
                "SELECT * FROM reader_state WHERE book_id = ?", (book["id"],)
            ).fetchone()
            resolved_document = (
                last_document_id
                if last_document_id is not _UNSET
                else (current["last_document_id"] if current else None)
            )
            resolved_theme = (
                theme
                if theme is not _UNSET and theme is not None
                else (current["theme"] if current else "light")
            )
            connection.execute(
                """
                INSERT INTO reader_state(book_id, last_document_id, theme, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    last_document_id = excluded.last_document_id,
                    theme = excluded.theme,
                    updated_at = excluded.updated_at
                """,
                (book["id"], resolved_document, resolved_theme, utc_now()),
            )
            return {
                "book_id": book["id"],
                "last_document_id": resolved_document,
                "theme": resolved_theme,
            }

    def update_progress(self, document_id: int, scroll_ratio: float) -> dict[str, object]:
        if not 0 <= scroll_ratio <= 1:
            raise BookError("Scroll position must be between 0 and 1.")
        with self.connection() as connection:
            document = self.get_document(connection, document_id)
            now = utc_now()
            connection.execute(
                """
                INSERT INTO document_progress(document_id, scroll_ratio, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    scroll_ratio = excluded.scroll_ratio,
                    updated_at = excluded.updated_at
                """,
                (document["id"], scroll_ratio, now),
            )
            return {"document_id": document["id"], "scroll_ratio": scroll_ratio}

    def search(
        self,
        query: str,
        book_identifier: str | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        needle = query.strip().casefold()
        if not needle:
            raise BookError("Search query cannot be empty.")
        if offset < 0 or (limit is not None and limit < 1):
            raise BookError("Search limit and offset must be non-negative.")
        with self.connection() as connection:
            values: tuple[object, ...] = ()
            clause = ""
            if book_identifier is not None:
                book = self.get_book(connection, book_identifier)
                clause = "WHERE documents.book_id = ?"
                values = (book["id"],)
            fts_ids: list[int] | None = None
            try:
                tokens = re.findall(r"[\w]+", needle, flags=re.UNICODE)
                if tokens:
                    match_query = " AND ".join(f'"{token.replace(chr(34), "")}"*' for token in tokens)
                    fts_ids = [
                        int(row[0])
                        for row in connection.execute(
                            "SELECT rowid FROM documents_fts WHERE documents_fts MATCH ?", (match_query,)
                        ).fetchall()
                    ]
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                fts_ids = None
            if fts_ids is not None:
                # FTS5 prefix matching is only a candidate accelerator. Search
                # semantics are case-insensitive substring matching, so include
                # rows whose title, book title, or content contains the complete
                # query as well. SQLite NOCASE is reliable for ASCII; for other
                # scripts, fall back to the Python casefold scan below rather
                # than risk excluding a valid match here.
                if needle.isascii():
                    title_like = f"%{needle}%"
                    substring_ids = [
                        int(row[0])
                        for row in connection.execute(
                            """
                            SELECT documents.id
                            FROM documents JOIN books ON books.id = documents.book_id
                            WHERE documents.title LIKE ? COLLATE NOCASE
                               OR books.title LIKE ? COLLATE NOCASE
                               OR documents.content LIKE ? COLLATE NOCASE
                            """,
                            (title_like, title_like, title_like),
                        ).fetchall()
                    ]
                    fts_ids = sorted(set(fts_ids).union(substring_ids))
                else:
                    fts_ids = None
                if not fts_ids:
                    # Prefix matching cannot represent arbitrary substring searches; retain the old behavior.
                    fts_ids = None
            if fts_ids is not None:
                placeholders = ", ".join("?" for _ in fts_ids)
                clause = f"{clause} {'AND' if clause else 'WHERE'} documents.id IN ({placeholders})"
                values = (*values, *fts_ids)
            rows = connection.execute(
                f"""
                SELECT documents.*, books.title AS book_title
                FROM documents
                JOIN books ON books.id = documents.book_id
                {clause}
                ORDER BY books.title COLLATE NOCASE, documents.position, documents.id
                """,
                values,
            ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            title_match = row["title"].casefold().find(needle)
            book_match = row["book_title"].casefold().find(needle)
            content_match = row["content"].casefold().find(needle)
            if max(title_match, book_match, content_match) < 0:
                continue
            match_at = content_match if content_match >= 0 else 0
            start = max(0, match_at - 80)
            end = min(len(row["content"]), match_at + len(query.strip()) + 160)
            snippet = " ".join(row["content"][start:end].split())
            if start:
                snippet = "..." + snippet
            if end < len(row["content"]):
                snippet += "..."
            results.append(
                {
                    "id": row["id"],
                    "book_id": row["book_id"],
                    "book_title": row["book_title"],
                    "title": row["title"],
                    "position": row["position"],
                    "snippet": snippet,
                }
            )
        if limit is None:
            return results[offset:]
        return results[offset : offset + limit]

    def export_archive(self, destination: Path) -> Path:
        destination = destination.expanduser().resolve()
        if destination.exists():
            raise BookError(f"Export destination '{destination}' already exists.")
        self.initialize()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.database_path, "library.sqlite3")
            if self.documents_root.exists():
                for path in self.documents_root.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(self.root).as_posix())
        return destination

    def restore_archive(self, source: Path, *, replace: bool = False) -> None:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise BookError(f"Backup '{source}' was not found.")
        if self.root.exists() and not self.root.is_dir():
            if not replace:
                raise BookError(f"The data path '{self.root}' is not a directory.")
        elif self.root.exists() and any(self.root.iterdir()) and not replace:
            raise BookError("The data directory is not empty. Use --replace to restore over it.")
        self.root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{self.root.name}.restore-", dir=self.root.parent))
        backup: Path | None = None

        def discard(path: Path) -> None:
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except FileNotFoundError:
                pass

        try:
            try:
                with zipfile.ZipFile(source) as archive:
                    names = archive.namelist()
                    members = [Path(name) for name in names]
                    if "library.sqlite3" not in names:
                        raise BookError("Backup does not contain a library database.")
                    if any(path.is_absolute() or ".." in path.parts for path in members):
                        raise BookError("Backup contains an unsafe path.")
                    for path in members:
                        target = (staging / path).resolve()
                        try:
                            target.relative_to(staging)
                        except ValueError as error:
                            raise BookError("Backup contains an unsafe path.") from error
                    archive.extractall(staging)
            except zipfile.BadZipFile as error:
                raise BookError(f"Backup '{source}' is not a valid ZIP archive.") from error

            if self.root.exists():
                if replace:
                    backup = self.root.parent / f".{self.root.name}.before-restore-{os.getpid()}"
                    suffix = 1
                    while backup.exists():
                        suffix += 1
                        backup = self.root.parent / f".{self.root.name}.before-restore-{os.getpid()}-{suffix}"
                    self.root.replace(backup)
                else:
                    # An empty destination can be removed so the staged tree can be
                    # moved into place without leaving stale files behind.
                    self.root.rmdir()
            staging.replace(self.root)
        except Exception:
            if staging.exists():
                discard(staging)
            if backup is not None and backup.exists() and not self.root.exists():
                backup.replace(self.root)
            raise
        else:
            if backup is not None:
                discard(backup)
