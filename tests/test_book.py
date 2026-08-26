from __future__ import annotations

import io
import json
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from book.cli import main
from book.database import Library
from book.web import create_server


class BookCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.data_dir = self.root / "library"
        self.sources = self.root / "sources"
        self.sources.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(["--data-dir", str(self.data_dir), *arguments])
        return status, stdout.getvalue(), stderr.getvalue()

    def add_book(self, title: str = "Study") -> None:
        status, _, error = self.invoke("add", title)
        self.assertEqual(status, 0, error)

    def add_document(self, book: str, path: Path, title: str | None = None) -> int:
        arguments = ["doc", "add", book, str(path)]
        if title:
            arguments.extend(["--title", title])
        status, output, error = self.invoke(*arguments)
        self.assertEqual(status, 0, error)
        return int(output.split("Added document ", 1)[1].split(" ", 1)[0])

    def test_archive_search_refresh_and_manual_order(self) -> None:
        image = self.sources / "matrix.png"
        image.write_bytes(b"png data")
        first = self.sources / "first.md"
        first.write_text("# Matrices\n\nA matrix is useful.\n\n![Matrix](matrix.png)\n", encoding="utf-8")
        second = self.sources / "second.txt"
        second.write_text("Eigenvalues are learning notes.", encoding="utf-8")

        self.add_book()
        first_id = self.add_document("Study", first)
        second_id = self.add_document("Study", second)

        library = Library(self.data_dir)
        document, resources = library.document_info(first_id)
        self.assertEqual(document["title"], "Matrices")
        self.assertEqual(len(resources), 1)
        self.assertTrue((library.document_dir(first_id) / resources[0]["relative_path"]).is_file())

        status, output, error = self.invoke("search", "matrix")
        self.assertEqual(status, 0, error)
        self.assertIn("Matrices", output)

        status, _, error = self.invoke("doc", "move", str(second_id), "1")
        self.assertEqual(status, 0, error)
        _, documents = library.list_documents("Study")
        self.assertEqual([document["id"] for document in documents], [second_id, first_id])

        first.write_text("# Matrices\n\nA determinant changes the matrix.\n", encoding="utf-8")
        status, _, error = self.invoke("doc", "refresh", str(first_id))
        self.assertEqual(status, 0, error)
        status, output, error = self.invoke("search", "determinant")
        self.assertEqual(status, 0, error)
        self.assertIn("Matrices", output)

    def test_remove_never_deletes_the_original_source(self) -> None:
        source = self.sources / "notes.txt"
        source.write_text("Keep this original file.", encoding="utf-8")
        self.add_book()
        document_id = self.add_document("Study", source)
        library = Library(self.data_dir)
        archive_dir = library.document_dir(document_id)
        self.assertTrue(archive_dir.exists())

        status, _, error = self.invoke("doc", "remove", str(document_id))
        self.assertEqual(status, 0, error)
        self.assertTrue(source.is_file())
        self.assertFalse(archive_dir.exists())

    def test_html_is_sanitized_and_local_assets_are_available(self) -> None:
        styles = self.sources / "page.css"
        styles.write_text("body { background: url(texture.png); }", encoding="utf-8")
        texture = self.sources / "texture.png"
        texture.write_bytes(b"texture")
        image = self.sources / "figure.png"
        image.write_bytes(b"figure")
        source = self.sources / "lesson.html"
        source.write_text(
            "<html><head><link rel='stylesheet' href='page.css'></head>"
            "<body><h1>Vectors</h1><img src='figure.png'><script>alert('bad')</script></body></html>",
            encoding="utf-8",
        )
        self.add_book()
        document_id = self.add_document("Study", source)
        library = Library(self.data_dir)
        document, resources = library.document_info(document_id)
        entry = (library.document_dir(document_id) / document["entry_path"]).read_text(encoding="utf-8")
        self.assertNotIn("script", entry)
        self.assertEqual(len(resources), 3)

        server = create_server(library, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(f"{base}/documents/{document_id}/content") as response:
                body = response.read().decode("utf-8")
                self.assertIn("Vectors", body)
                self.assertIn("script-src 'none'", response.headers["Content-Security-Policy"])
            asset_path = resources[0]["relative_path"]
            with urlopen(f"{base}/documents/{document_id}/{asset_path}") as response:
                self.assertGreater(len(response.read()), 0)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_web_api_persists_progress_theme_and_order(self) -> None:
        first = self.sources / "first.txt"
        second = self.sources / "second.txt"
        first.write_text("First chapter", encoding="utf-8")
        second.write_text("Second chapter", encoding="utf-8")
        self.add_book()
        first_id = self.add_document("Study", first)
        second_id = self.add_document("Study", second)
        library = Library(self.data_dir)
        server = create_server(library, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            payload = json.dumps({"scroll_ratio": 0.42}).encode("utf-8")
            request = Request(
                f"{base}/api/documents/{first_id}/progress",
                data=payload,
                method="PUT",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                self.assertEqual(json.load(response)["scroll_ratio"], 0.42)
            payload = json.dumps({"last_document_id": first_id, "theme": "dark"}).encode("utf-8")
            request = Request(
                f"{base}/api/books/1/state",
                data=payload,
                method="PUT",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                self.assertEqual(json.load(response)["theme"], "dark")
            payload = json.dumps({"document_ids": [second_id, first_id]}).encode("utf-8")
            request = Request(
                f"{base}/api/books/1/order",
                data=payload,
                method="PUT",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                self.assertEqual([row["id"] for row in json.load(response)], [second_id, first_id])
            with urlopen(f"{base}/api/books/1") as response:
                book = json.load(response)
            self.assertEqual(book["theme"], "dark")
            self.assertEqual(book["last_document_id"], first_id)
            progress_by_document = {document["id"]: document["scroll_ratio"] for document in book["documents"]}
            self.assertEqual(progress_by_document[first_id], 0.42)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_book_with_documents_requires_explicit_removal(self) -> None:
        source = self.sources / "notes.txt"
        source.write_text("notes", encoding="utf-8")
        self.add_book()
        self.add_document("Study", source)
        status, _, error = self.invoke("remove", "Study")
        self.assertEqual(status, 1)
        self.assertIn("--with-documents", error)
        status, _, error = self.invoke("remove", "Study", "--with-documents")
        self.assertEqual(status, 0, error)


if __name__ == "__main__":
    unittest.main()
