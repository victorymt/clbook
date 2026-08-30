from __future__ import annotations

import io
import json
import os
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from book.cli import main
from book.database import Library
from book.errors import BookError
from book.importer import archive_document
from book.rendering import markdown_to_html
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

    def test_search_finds_substrings_not_matched_by_fts_prefixes(self) -> None:
        prefix_match = self.sources / "prefix.txt"
        substring_match = self.sources / "substring.txt"
        prefix_match.write_text("foobar", encoding="utf-8")
        substring_match.write_text("xxfooxx", encoding="utf-8")
        self.add_book()
        self.add_document("Study", prefix_match)
        self.add_document("Study", substring_match)

        results = Library(self.data_dir).search("foo")

        self.assertEqual({result["title"] for result in results}, {"prefix", "substring"})

    def test_bulk_import_rolls_back_unless_continue_is_requested(self) -> None:
        first = self.sources / "first.txt"
        missing = self.sources / "missing.txt"
        first.write_text("first", encoding="utf-8")
        self.add_book()

        status, _, error = self.invoke("doc", "add", "Study", str(first), str(missing))
        self.assertEqual(status, 1)
        self.assertIn("missing.txt", error)
        self.assertEqual(Library(self.data_dir).list_documents("Study")[1], [])

        status, _, error = self.invoke(
            "doc", "add", "Study", str(first), str(missing), "--continue-on-error"
        )
        self.assertEqual(status, 1)
        self.assertIn("missing.txt", error)
        _, documents = Library(self.data_dir).list_documents("Study")
        self.assertEqual([document["title"] for document in documents], ["first"])

    def test_stale_detection_catches_same_size_content_changes(self) -> None:
        source = self.sources / "stable.txt"
        source.write_text("abc", encoding="utf-8")
        self.add_book()
        document_id = self.add_document("Study", source)
        original_mtime = source.stat().st_mtime

        source.write_text("xyz", encoding="utf-8")
        os.utime(source, (original_mtime, original_mtime))

        library = Library(self.data_dir)
        self.assertTrue(library.is_document_stale(document_id))
        self.assertTrue(library.get_book_for_web(1)["documents"][0]["source_stale"])

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
            with urlopen(f"{base}/documents/{document_id}/content?theme=dark") as response:
                body = response.read().decode("utf-8")
                self.assertIn('data-book-theme="dark"', body)
            asset_path = resources[0]["relative_path"]
            with urlopen(f"{base}/documents/{document_id}/{asset_path}") as response:
                self.assertGreater(len(response.read()), 0)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_web_refresh_reuses_persisted_resource_root(self) -> None:
        shared_root = self.root / "course"
        chapters = shared_root / "chapters"
        chapters.mkdir(parents=True)
        image = shared_root / "images" / "figure.png"
        image.parent.mkdir()
        image.write_bytes(b"figure")
        source = chapters / "lesson.html"
        source.write_text("<html><body><img src='../images/figure.png'></body></html>", encoding="utf-8")

        self.add_book()
        status, output, error = self.invoke(
            "doc", "add", "Study", str(source), "--resource-root", str(shared_root)
        )
        self.assertEqual(status, 0, error)
        document_id = int(output.split("Added document ", 1)[1].split(" ", 1)[0])
        library = Library(self.data_dir)
        document, resources = library.document_info(document_id)
        self.assertEqual(document["resource_root"], str(shared_root.resolve()))
        self.assertEqual(len(resources), 1)

        server = create_server(library, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            request = Request(f"{base}/api/documents/{document_id}/refresh", method="POST")
            with urlopen(request) as response:
                refreshed = json.load(response)
            self.assertEqual(refreshed["id"], document_id)
            self.assertNotIn("resource_root", refreshed)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        document, resources = library.document_info(document_id)
        self.assertEqual(document["resource_root"], str(shared_root.resolve()))
        self.assertEqual(len(resources), 1)
        self.assertTrue((library.document_dir(document_id) / resources[0]["relative_path"]).is_file())

    def test_html_void_tags_do_not_remove_following_content(self) -> None:
        source = self.sources / "void.html"
        source.write_text(
            "<html><body><base href='/'><p>Visible after base.</p></body></html>",
            encoding="utf-8",
        )
        self.add_book()
        document_id = self.add_document("Study", source)
        library = Library(self.data_dir)
        document, _ = library.document_info(document_id)
        entry = (library.document_dir(document_id) / document["entry_path"]).read_text(encoding="utf-8")
        self.assertIn("Visible after base.", entry)
        self.assertNotIn("<base", entry)

    def test_archive_does_not_copy_files_outside_source_directory(self) -> None:
        nested = self.sources / "nested"
        nested.mkdir()
        secret = self.sources / "secret.txt"
        secret.write_text("private", encoding="utf-8")
        source = nested / "outside.html"
        source.write_text("<img src='../secret.txt'>", encoding="utf-8")
        self.add_book()
        document_id = self.add_document("Study", source)
        library = Library(self.data_dir)
        _, resources = library.document_info(document_id)
        self.assertEqual(resources, [])
        self.assertFalse(any(path.name == "secret.txt" for path in library.document_dir(document_id).rglob("*")))

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
            self.assertAlmostEqual(book["progress"], 0.21)
            progress_by_document = {document["id"]: document["scroll_ratio"] for document in book["documents"]}
            self.assertEqual(progress_by_document[first_id], 0.42)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_progress_updates_do_not_change_selected_document(self) -> None:
        first = self.sources / "first.txt"
        second = self.sources / "second.txt"
        first.write_text("First chapter", encoding="utf-8")
        second.write_text("Second chapter", encoding="utf-8")
        self.add_book()
        first_id = self.add_document("Study", first)
        second_id = self.add_document("Study", second)
        library = Library(self.data_dir)
        library.update_reader_state(1, second_id, "light")
        library.update_progress(first_id, 0.5)
        self.assertEqual(library.get_book_for_web(1)["last_document_id"], second_id)

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

    def test_metadata_bulk_import_stale_detection_and_backup(self) -> None:
        first = self.sources / "first.txt"
        second = self.sources / "second.md"
        first.write_text("First", encoding="utf-8")
        second.write_text("# Second\n\ncontent", encoding="utf-8")
        self.add_book()
        status, _, error = self.invoke("edit", "Study", "--description", "Updated")
        self.assertEqual(status, 0, error)
        status, _, error = self.invoke("doc", "add", "Study", str(self.sources), "--recursive")
        self.assertEqual(status, 0, error)
        status, _, error = self.invoke("doc", "rename", "1", "First chapter")
        self.assertEqual(status, 0, error)
        library = Library(self.data_dir)
        self.assertEqual(library.list_books()[0]["description"], "Updated")
        first.write_text("Changed", encoding="utf-8")
        self.assertTrue(library.is_document_stale(1))
        backup = self.root / "backup.zip"
        status, _, error = self.invoke("export", str(backup))
        self.assertEqual(status, 0, error)
        restored = Library(self.root / "restored")
        restored.restore_archive(backup)
        self.assertEqual(len(restored.list_books()), 1)
        stale = restored.root / "stale.txt"
        stale.write_text("remove me", encoding="utf-8")
        restored.restore_archive(backup, replace=True)
        self.assertFalse(stale.exists())
        invalid = self.root / "invalid.zip"
        invalid.write_bytes(b"not a zip")
        with self.assertRaisesRegex(BookError, "valid ZIP"):
            Library(self.root / "invalid-restore").restore_archive(invalid)

    def test_markdown_common_syntax_and_local_document_links(self) -> None:
        self.assertIn("<table>", markdown_to_html("| A | B |\n| --- | --- |\n| 1 | 2 |"))
        self.assertIn("<ul><li>outer<ul>", markdown_to_html("- outer\n  - inner"))
        other = self.sources / "other.md"
        source = self.sources / "source.md"
        other.write_text("# Other", encoding="utf-8")
        source.write_text("[Other][other]\n\n[other]: other.md", encoding="utf-8")
        self.add_book()
        first_id = self.add_document("Study", source)
        second_id = self.add_document("Study", other)
        library = Library(self.data_dir)
        server = create_server(library, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(f"{base}/documents/{first_id}/content") as response:
                body = response.read().decode("utf-8")
            self.assertIn(f"/documents/{second_id}/content", body)
            self.assertNotIn(f'/documents/{second_id}/content" target="_blank"', body)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_html_removes_forms_refresh_and_archives_svg_resources(self) -> None:
        source = self.sources / "secure.html"
        image = self.sources / "picture.png"
        manifest = self.sources / "site.webmanifest"
        manifest_icon = self.sources / "manifest-icon.png"
        image.write_bytes(b"image")
        manifest_icon.write_bytes(b"manifest image")
        manifest.write_text('{"icons": [{"src": "manifest-icon.png"}]}', encoding="utf-8")
        source.write_text(
            "<html><head><meta http-equiv='refresh' content='0;url=https://example.com'></head>"
            "<link rel='manifest' href='site.webmanifest'>"
            "<body><form><input></form><svg><image href='picture.png'/></svg></body></html>",
            encoding="utf-8",
        )
        self.add_book()
        document_id = self.add_document("Study", source)
        library = Library(self.data_dir)
        document, resources = library.document_info(document_id)
        entry = (library.document_dir(document_id) / document["entry_path"]).read_text(encoding="utf-8")
        self.assertNotIn("<form", entry)
        self.assertNotIn("http-equiv='refresh'", entry)
        self.assertEqual(len(resources), 3)
        archived_manifest = next(item for item in resources if item["source_path"] == str(manifest.resolve()))
        manifest_text = (library.document_dir(document_id) / archived_manifest["relative_path"]).read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"src": "manifest-icon.png"', manifest_text)

    def test_web_management_and_partial_reader_state_api(self) -> None:
        library = Library(self.data_dir)
        server = create_server(library, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def request_json(path: str, payload: dict[str, object] | None = None, method: str = "GET") -> object:
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            request = Request(path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
            with urlopen(request) as response:
                return json.load(response)

        try:
            book = request_json(f"{base}/api/books", {"title": "Web book", "description": "D"}, "POST")
            self.assertEqual(book["title"], "Web book")
            source = self.sources / "web.txt"
            source.write_text("Web chapter", encoding="utf-8")
            document = request_json(
                f"{base}/api/books/{book['id']}/documents", {"path": str(source)}, "POST"
            )
            document_id = document["id"]
            self.assertNotIn("source_path", document)
            self.assertNotIn("content", document)
            updated_book = request_json(
                f"{base}/api/books/{book['id']}", {"description": "Updated"}, "PATCH"
            )
            self.assertEqual(updated_book["documents"][0]["id"], document_id)
            request_json(f"{base}/api/documents/{document_id}", {"title": "Renamed"}, "PATCH")
            request_json(f"{base}/api/books/{book['id']}/state", {"last_document_id": document_id, "theme": "dark"}, "PUT")
            state = request_json(f"{base}/api/books/{book['id']}/state", {"theme": "light"}, "PUT")
            self.assertEqual(state["last_document_id"], document_id)
            self.assertEqual(state["theme"], "light")
            second = self.sources / "second.txt"
            second.write_text("Second", encoding="utf-8")
            with self.assertRaises(HTTPError) as error:
                request_json(
                    f"{base}/api/books/{book['id']}/documents",
                    {"path": str(second), "title": "   "},
                    "POST",
                )
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
