from __future__ import annotations

import os
import shutil
import sqlite3
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
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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
            cursor = connection.execute(
                """
                INSERT INTO documents(
                    book_id, title, source_path, entry_path, document_type, content, position, created_at, updated_at
                ) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?)
                """,
                (book["id"], title, str(source_path), document_type, content, position, now, now),
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

    def update_document_import(
        self,
        document_id: int,
        entry_path: str,
        document_type: str,
        content: str,
        resources: list[tuple[str, str, str]],
    ) -> sqlite3.Row:
        with self.connection() as connection:
            document = self.get_document(connection, document_id)
            now = utc_now()
            connection.execute(
                """
                UPDATE documents
                SET entry_path = ?, document_type = ?, content = ?, updated_at = ?
                WHERE id = ?
                """,
                (entry_path, document_type, content, now, document_id),
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
                       COALESCE(document_progress.scroll_ratio, 0) AS scroll_ratio
                FROM documents
                LEFT JOIN document_progress ON document_progress.document_id = documents.id
                WHERE documents.book_id = ?
                ORDER BY documents.position, documents.id
                """,
                (book_id,),
            ).fetchall()
            return {
                "id": book["id"],
                "title": book["title"],
                "description": book["description"],
                "theme": state["theme"] if state else "light",
                "last_document_id": state["last_document_id"] if state else None,
                "documents": [dict(row) for row in documents],
            }

    def list_books_for_web(self) -> list[dict[str, object]]:
        return [dict(row) for row in self.list_books()]

    def update_reader_state(
        self, book_id: int, last_document_id: int | None, theme: str | None = None
    ) -> dict[str, object]:
        if theme is not None and theme not in {"light", "dark"}:
            raise BookError("Theme must be 'light' or 'dark'.")
        with self.connection() as connection:
            book = self.get_book(connection, str(book_id))
            if last_document_id is not None:
                document = self.get_document(connection, last_document_id)
                if document["book_id"] != book["id"]:
                    raise BookError("The selected document does not belong to this book.")
            current = connection.execute(
                "SELECT * FROM reader_state WHERE book_id = ?", (book["id"],)
            ).fetchone()
            resolved_theme = theme or (current["theme"] if current else "light")
            connection.execute(
                """
                INSERT INTO reader_state(book_id, last_document_id, theme, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    last_document_id = excluded.last_document_id,
                    theme = excluded.theme,
                    updated_at = excluded.updated_at
                """,
                (book["id"], last_document_id, resolved_theme, utc_now()),
            )
            return {
                "book_id": book["id"],
                "last_document_id": last_document_id,
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

    def search(self, query: str, book_identifier: str | None = None) -> list[dict[str, object]]:
        needle = query.strip().casefold()
        if not needle:
            raise BookError("Search query cannot be empty.")
        with self.connection() as connection:
            values: tuple[object, ...] = ()
            clause = ""
            if book_identifier is not None:
                book = self.get_book(connection, book_identifier)
                clause = "WHERE documents.book_id = ?"
                values = (book["id"],)
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
        return results
