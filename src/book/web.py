from __future__ import annotations

import json
import mimetypes
import re
import shutil
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse

from .database import Library
from .errors import BookError
from .importer import archive_document, document_type_for, read_text, replace_archive, suggested_title
from .rendering import render_document


APP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>book</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <div id="app"></div>
  <script src="/static/app.js"></script>
</body>
</html>
"""

CONTENT_SECURITY_POLICY = (
    "default-src 'self' data:; img-src 'self' data:; media-src 'self' data:; "
    "font-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'; connect-src 'none'; frame-ancestors 'self'"
)


def static_text(name: str) -> str:
    return files("book").joinpath("static", name).read_text(encoding="utf-8")


def document_payload(library: Library, document: object, *, stale: bool | None = None) -> dict[str, object]:
    """Return document metadata safe to expose through the JSON API."""
    payload = dict(document)  # type: ignore[arg-type]
    source_path = payload.pop("source_path", None)
    payload.pop("resource_root", None)
    payload.pop("source_mtime", None)
    payload.pop("source_size", None)
    payload.pop("content", None)
    if stale is None and source_path is not None:
        try:
            stale = library.is_document_stale(int(payload["id"]))
        except BookError:
            stale = False
    if stale is not None:
        payload["source_stale"] = stale
    return payload


def make_handler(library: Library) -> type[BaseHTTPRequestHandler]:
    class BookHandler(BaseHTTPRequestHandler):
        server_version = "book/0.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def send_bytes(
            self,
            status: HTTPStatus,
            payload: bytes,
            content_type: str,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)

        def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_bytes(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

        def fail(self, status: HTTPStatus, message: str) -> None:
            self.send_json({"error": message}, status)

        def parse_body(self) -> dict[str, object]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise BookError("Invalid request body length.") from error
            if length < 1 or length > 1_000_000:
                raise BookError("Request body must be between 1 byte and 1 MB.")
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise BookError("Request body must be valid JSON.") from error
            if not isinstance(body, dict):
                raise BookError("Request body must be a JSON object.")
            return body

        def do_GET(self) -> None:
            try:
                self.handle_get()
            except BookError as error:
                status = HTTPStatus.BAD_REQUEST if urlparse(self.path).path == "/api/search" else HTTPStatus.NOT_FOUND
                self.fail(status, str(error))
            except BrokenPipeError:
                return
            except Exception:
                self.fail(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to serve this request.")

        def handle_get(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path in {"/", "/index.html"} or re.fullmatch(r"/books/\d+", path):
                self.send_bytes(
                    HTTPStatus.OK,
                    APP_HTML.encode("utf-8"),
                    "text/html; charset=utf-8",
                    {"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'"},
                )
                return
            if path == "/static/app.css":
                self.send_bytes(HTTPStatus.OK, static_text("app.css").encode("utf-8"), "text/css; charset=utf-8")
                return
            if path == "/static/app.js":
                self.send_bytes(HTTPStatus.OK, static_text("app.js").encode("utf-8"), "text/javascript; charset=utf-8")
                return
            if path == "/api/books":
                self.send_json(library.list_books_for_web())
                return
            match = re.fullmatch(r"/api/books/(\d+)", path)
            if match:
                self.send_json(library.get_book_for_web(int(match.group(1))))
                return
            if path == "/api/search":
                values = query.get("q", [])
                if not values:
                    raise BookError("Search query cannot be empty.")
                book = query.get("book", [None])[0]
                try:
                    limit = int(query.get("limit", ["100"])[0])
                    offset = int(query.get("offset", ["0"])[0])
                except ValueError as error:
                    raise BookError("Search limit and offset must be integers.") from error
                self.send_json(library.search(values[0], book, limit=limit, offset=offset))
                return
            match = re.fullmatch(r"/documents/(\d+)/content", path)
            if match:
                document, _ = library.document_info(int(match.group(1)))
                theme = query.get("theme", [library.get_book_for_web(int(document["book_id"]))["theme"]])[0]
                document_html = render_document(
                    document,
                    library.document_dir(document["id"]),
                    theme,
                    library.document_links(int(document["book_id"])),
                )
                self.send_bytes(
                    HTTPStatus.OK,
                    document_html.encode("utf-8"),
                    "text/html; charset=utf-8",
                    {"Content-Security-Policy": CONTENT_SECURITY_POLICY, "Cache-Control": "no-store"},
                )
                return
            match = re.fullmatch(r"/documents/(\d+)/(assets/.+)", path)
            if match:
                self.serve_asset(int(match.group(1)), unquote(match.group(2)))
                return
            if path == "/health":
                self.send_json({"status": "ok"})
                return
            self.fail(HTTPStatus.NOT_FOUND, "Route not found.")

        def serve_asset(self, document_id: int, relative_path: str) -> None:
            parts = PurePosixPath(relative_path).parts
            if not parts or parts[0] != "assets" or ".." in parts:
                self.fail(HTTPStatus.NOT_FOUND, "Asset not found.")
                return
            root = (library.document_dir(document_id) / "assets").resolve()
            candidate = (library.document_dir(document_id) / relative_path).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                self.fail(HTTPStatus.NOT_FOUND, "Asset not found.")
                return
            if not candidate.is_file():
                self.fail(HTTPStatus.NOT_FOUND, "Asset not found.")
                return
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            headers = {"Cache-Control": "private, max-age=3600"}
            if content_type in {"text/html", "application/xhtml+xml"}:
                headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
            self.send_bytes(HTTPStatus.OK, candidate.read_bytes(), content_type, headers)

        def do_PUT(self) -> None:
            try:
                self.handle_put()
            except BookError as error:
                self.fail(HTTPStatus.BAD_REQUEST, str(error))
            except BrokenPipeError:
                return
            except Exception:
                self.fail(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to update the reader state.")

        def do_PATCH(self) -> None:
            try:
                self.handle_patch()
            except BookError as error:
                self.fail(HTTPStatus.BAD_REQUEST, str(error))
            except BrokenPipeError:
                return
            except Exception:
                self.fail(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to update the library.")

        def do_POST(self) -> None:
            try:
                self.handle_post()
            except BookError as error:
                self.fail(HTTPStatus.BAD_REQUEST, str(error))
            except BrokenPipeError:
                return
            except Exception:
                self.fail(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to update the library.")

        def do_DELETE(self) -> None:
            try:
                self.handle_delete()
            except BookError as error:
                self.fail(HTTPStatus.BAD_REQUEST, str(error))
            except BrokenPipeError:
                return
            except Exception:
                self.fail(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to update the library.")

        def handle_put(self) -> None:
            path = urlparse(self.path).path
            body = self.parse_body()
            match = re.fullmatch(r"/api/books/(\d+)/state", path)
            if match:
                kwargs: dict[str, object] = {}
                last_document_id = body.get("last_document_id")
                if "last_document_id" in body and last_document_id is not None and (isinstance(last_document_id, bool) or not isinstance(last_document_id, int)):
                    raise BookError("last_document_id must be an integer or null.")
                if "last_document_id" in body:
                    kwargs["last_document_id"] = last_document_id
                theme = body.get("theme")
                if "theme" in body and theme is not None and not isinstance(theme, str):
                    raise BookError("theme must be a string.")
                if "theme" in body:
                    kwargs["theme"] = theme
                self.send_json(library.update_reader_state(int(match.group(1)), **kwargs))
                return
            match = re.fullmatch(r"/api/documents/(\d+)/progress", path)
            if match:
                ratio = body.get("scroll_ratio")
                if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
                    raise BookError("scroll_ratio must be a number.")
                self.send_json(library.update_progress(int(match.group(1)), float(ratio)))
                return
            match = re.fullmatch(r"/api/books/(\d+)/order", path)
            if match:
                document_ids = body.get("document_ids")
                if not isinstance(document_ids, list) or any(
                    isinstance(item, bool) or not isinstance(item, int) for item in document_ids
                ):
                    raise BookError("document_ids must be an array of integers.")
                rows = library.reorder_documents(int(match.group(1)), document_ids)
                self.send_json([dict(row) for row in rows])
                return
            self.fail(HTTPStatus.NOT_FOUND, "Route not found.")

        def handle_patch(self) -> None:
            path = urlparse(self.path).path
            body = self.parse_body()
            match = re.fullmatch(r"/api/books/(\d+)", path)
            if match:
                title = body.get("title")
                description = body.get("description")
                if title is not None and not isinstance(title, str):
                    raise BookError("title must be a string.")
                if description is not None and not isinstance(description, str):
                    raise BookError("description must be a string.")
                book_id = int(match.group(1))
                library.update_book(str(book_id), title=title, description=description)
                self.send_json(library.get_book_for_web(book_id))
                return
            match = re.fullmatch(r"/api/documents/(\d+)", path)
            if match:
                title = body.get("title")
                if not isinstance(title, str):
                    raise BookError("title must be a string.")
                self.send_json(document_payload(library, library.rename_document(int(match.group(1)), title)))
                return
            self.fail(HTTPStatus.NOT_FOUND, "Route not found.")

        def handle_post(self) -> None:
            path = urlparse(self.path).path
            refresh_match = re.fullmatch(r"/api/documents/(\d+)/refresh", path)
            if refresh_match:
                document, _ = library.document_info(int(refresh_match.group(1)))
                source = Path(document["source_path"])
                if not source.is_file():
                    raise BookError("Original source is unavailable; the archived copy was not changed.")
                resource_root = Path(document["resource_root"]) if document["resource_root"] else None
                result = replace_archive(source, library.document_dir(document["id"]), resource_root)
                updated = library.update_document_import(
                    document["id"],
                    result.entry_path,
                    result.document_type,
                    result.content,
                    result.resources,
                    resource_root,
                )
                self.send_json(document_payload(library, updated))
                return
            body = self.parse_body()
            if path == "/api/books":
                title = body.get("title")
                description = body.get("description", "")
                if not isinstance(title, str) or not isinstance(description, str):
                    raise BookError("title and description must be strings.")
                self.send_json(dict(library.add_book(title, description)), HTTPStatus.CREATED)
                return
            match = re.fullmatch(r"/api/books/(\d+)/documents", path)
            if match:
                source_value = body.get("path")
                title_value = body.get("title")
                resource_root_value = body.get("resource_root")
                if not isinstance(source_value, str):
                    raise BookError("path must be a string.")
                if title_value is not None and not isinstance(title_value, str):
                    raise BookError("title must be a string.")
                if resource_root_value is not None and not isinstance(resource_root_value, str):
                    raise BookError("resource_root must be a string.")
                source = Path(source_value).expanduser().resolve()
                resource_root = Path(resource_root_value).expanduser().resolve() if resource_root_value else None
                if not source.is_file():
                    raise BookError(f"'{source}' is not a readable file.")
                kind = document_type_for(source)
                source_content = read_text(source)
                if title_value is not None:
                    title = title_value.strip()
                    if not title:
                        raise BookError("Document title cannot be empty.")
                else:
                    title = suggested_title(source, kind, source_content)
                document, archive_dir = library.insert_document(
                    str(int(match.group(1))), title, source, kind, "", resource_root=resource_root
                )
                try:
                    result = archive_document(
                        source,
                        archive_dir,
                        resource_root,
                    )
                    document = library.finish_document_import(
                        document["id"], result.entry_path, result.resources, result.content
                    )
                except Exception:
                    shutil.rmtree(archive_dir, ignore_errors=True)
                    try:
                        library.remove_document(document["id"])
                    except BookError:
                        pass
                    raise
                self.send_json(document_payload(library, document), HTTPStatus.CREATED)
                return
            self.fail(HTTPStatus.NOT_FOUND, "Route not found.")

        def handle_delete(self) -> None:
            path = urlparse(self.path).path
            if (match := re.fullmatch(r"/api/books/(\d+)", path)):
                query = parse_qs(urlparse(self.path).query)
                with_documents = query.get("with_documents", ["false"])[0].casefold() in {"1", "true", "yes"}
                self.send_json(dict(library.remove_book(match.group(1), with_documents)))
                return
            if (match := re.fullmatch(r"/api/documents/(\d+)", path)):
                document, _ = library.document_info(match.group(1))
                stale = library.is_document_stale(int(document["id"]))
                removed = library.remove_document(match.group(1))
                self.send_json(document_payload(library, removed, stale=stale))
                return
            self.fail(HTTPStatus.NOT_FOUND, "Route not found.")

    return BookHandler


def create_server(library: Library, port: int = 8765) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise BookError("Port must be between 0 and 65535.")
    library.initialize()
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(library))


def run_server(library: Library, port: int, open_path: str | None = None) -> int:
    server = create_server(library, port)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}{open_path or '/'}"
    print(f"Serving book library at {url}")
    print("Press Ctrl-C to stop the local reader.")
    if open_path:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped local reader.")
    finally:
        server.server_close()
    return 0
