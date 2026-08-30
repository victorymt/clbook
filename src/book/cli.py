from __future__ import annotations

import argparse
import sqlite3
import shutil
import sys
from pathlib import Path
from typing import Callable

from .database import Library
from .errors import BookError
from .importer import archive_document, document_type_for, read_text, replace_archive, suggested_title


def table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return "No entries."
    rendered = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in rendered:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    separator = "  "
    lines = [separator.join(header.ljust(widths[index]) for index, header in enumerate(headers))]
    lines.append(separator.join("-" * width for width in widths))
    lines.extend(separator.join(cell.ljust(widths[index]) for index, cell in enumerate(row)) for row in rendered)
    return "\n".join(lines)


def library_from(args: argparse.Namespace) -> Library:
    return Library(Path(args.data_dir) if args.data_dir else None)


def command_init(args: argparse.Namespace) -> int:
    library = library_from(args)
    library.initialize()
    print(f"Initialized book library at {library.root}")
    return 0


def command_add(args: argparse.Namespace) -> int:
    book = library_from(args).add_book(args.title, args.description)
    print(f"Added book {book['id']}: {book['title']}")
    return 0


def command_list(args: argparse.Namespace) -> int:
    books = library_from(args).list_books()
    print(table(["ID", "Title", "Documents", "Description"], [[book["id"], book["title"], book["document_count"], book["description"]] for book in books]))
    return 0


def command_rename(args: argparse.Namespace) -> int:
    book = library_from(args).rename_book(args.book, args.title)
    print(f"Renamed book {book['id']} to {book['title']}")
    return 0


def command_edit_book(args: argparse.Namespace) -> int:
    book = library_from(args).update_book(args.book, title=args.title, description=args.description)
    print(f"Updated book {book['id']}: {book['title']}")
    return 0


def command_remove_book(args: argparse.Namespace) -> int:
    book = library_from(args).remove_book(args.book, args.with_documents)
    print(f"Removed book {book['id']}: {book['title']}")
    return 0


def _source_paths(values: list[str], recursive: bool) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            paths.extend(candidate for candidate in sorted(iterator) if candidate.is_file())
        else:
            paths.append(path)
    unique: dict[str, Path] = {str(path): path for path in paths}
    return list(unique.values())


def _add_document(
    library: Library,
    book: str,
    source: Path,
    title_override: str | None = None,
    allowed_root: Path | None = None,
) -> sqlite3.Row:
    if not source.is_file():
        raise BookError(f"'{source}' is not a readable file.")
    document_type = document_type_for(source)
    source_content = read_text(source)
    title = title_override.strip() if title_override else suggested_title(source, document_type, source_content)
    if not title:
        raise BookError("Document title cannot be empty.")
    document, archive_dir = library.insert_document(book, title, source, document_type, "")
    try:
        result = archive_document(source, archive_dir, allowed_root)
        return library.finish_document_import(document["id"], result.entry_path, result.resources, result.content)
    except Exception:
        shutil.rmtree(archive_dir, ignore_errors=True)
        try:
            library.remove_document(document["id"])
        except BookError:
            pass
        raise


def command_doc_add(args: argparse.Namespace) -> int:
    library = library_from(args)
    sources = _source_paths(args.path, args.recursive)
    if not sources:
        raise BookError("No files found to import.")
    if args.title and len(sources) != 1:
        raise BookError("--title can only be used when importing one file.")
    for source in sources:
        document = _add_document(
            library,
            args.book,
            source,
            args.title if len(sources) == 1 else None,
            Path(args.resource_root).expanduser().resolve() if args.resource_root else None,
        )
        print(f"Added document {document['id']} to {document['book_title']}: {document['title']}")
    return 0


def command_doc_list(args: argparse.Namespace) -> int:
    book, documents = library_from(args).list_documents(args.book)
    print(f"{book['title']} ({len(documents)} documents)")
    print(
        table(
            ["Pos", "ID", "Title", "Type", "Progress"],
            [
                [
                    document["position"],
                    document["id"],
                    document["title"],
                    document["document_type"],
                    f"{round(document['scroll_ratio'] * 100)}%",
                ]
                for document in documents
            ],
        )
    )
    return 0


def command_doc_info(args: argparse.Namespace) -> int:
    library = library_from(args)
    document, resources = library.document_info(args.document)
    print(f"ID: {document['id']}")
    print(f"Book: {document['book_title']}")
    print(f"Title: {document['title']}")
    print(f"Position: {document['position']}")
    print(f"Type: {document['document_type']}")
    print(f"Source: {document['source_path']}")
    stale = library.is_document_stale(document["id"])
    print(f"Source status: {'stale' if stale else 'current'}")
    print(f"Archive: {library.document_dir(document['id']) / document['entry_path']}")
    print(f"Resources: {len(resources)}")
    return 0


def command_doc_refresh(args: argparse.Namespace) -> int:
    library = library_from(args)
    document, _ = library.document_info(args.document)
    source = Path(document["source_path"])
    if not source.is_file():
        raise BookError(f"Original source '{source}' is unavailable; the archived copy was not changed.")
    result = replace_archive(
        source,
        library.document_dir(document["id"]),
        Path(args.resource_root).expanduser().resolve() if args.resource_root else None,
    )
    document = library.update_document_import(
        document["id"], result.entry_path, result.document_type, result.content, result.resources
    )
    print(f"Refreshed document {document['id']}: {document['title']}")
    return 0


def command_doc_remove(args: argparse.Namespace) -> int:
    document = library_from(args).remove_document(args.document)
    print(f"Removed document {document['id']}: {document['title']}")
    return 0


def command_doc_rename(args: argparse.Namespace) -> int:
    document = library_from(args).rename_document(args.document, args.title)
    print(f"Renamed document {document['id']} to {document['title']}")
    return 0


def command_doc_move(args: argparse.Namespace) -> int:
    document = library_from(args).move_document(args.document, args.position)
    print(f"Moved document {document['id']} to position {document['position']}")
    return 0


def command_search(args: argparse.Namespace) -> int:
    results = library_from(args).search(args.query, args.book, limit=args.limit, offset=args.offset)
    if not results:
        print("No matching documents.")
        return 0
    print(
        table(
            ["Book", "Doc", "Title", "Match"],
            [[result["book_title"], result["id"], result["title"], result["snippet"]] for result in results],
        )
    )
    return 0


def command_serve(args: argparse.Namespace) -> int:
    from .web import run_server

    library = library_from(args)
    library.initialize()
    return run_server(library, args.port, "/" if args.open else None)


def command_open(args: argparse.Namespace) -> int:
    from .web import run_server

    library = library_from(args)
    with library.connection() as connection:
        book = library.get_book(connection, args.book)
    return run_server(library, args.port, f"/books/{book['id']}")


def command_export(args: argparse.Namespace) -> int:
    destination = library_from(args).export_archive(Path(args.path))
    print(f"Exported book library to {destination}")
    return 0


def command_restore(args: argparse.Namespace) -> int:
    library_from(args).restore_archive(Path(args.path), replace=args.replace)
    print(f"Restored book library at {library_from(args).root}")
    return 0


def add_document_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    doc = subparsers.add_parser("doc", help="Manage documents in a book")
    doc_subparsers = doc.add_subparsers(dest="doc_command", required=True)

    add = doc_subparsers.add_parser("add", help="Archive a document in a book")
    add.add_argument("book", help="Book ID or exact title")
    add.add_argument("path", nargs="+", help="File(s) or directory to import")
    add.add_argument("--recursive", action="store_true", help="Recursively import files from directories")
    add.add_argument("--resource-root", help="Allow local assets under this directory")
    add.add_argument("--title", help="Override the title inferred from the document")
    add.set_defaults(handler=command_doc_add)

    listing = doc_subparsers.add_parser("list", help="List a book's documents")
    listing.add_argument("book", help="Book ID or exact title")
    listing.set_defaults(handler=command_doc_list)

    info = doc_subparsers.add_parser("info", help="Show document metadata")
    info.add_argument("document", help="Document ID")
    info.set_defaults(handler=command_doc_info)

    rename = doc_subparsers.add_parser("rename", help="Rename a document")
    rename.add_argument("document", help="Document ID")
    rename.add_argument("title")
    rename.set_defaults(handler=command_doc_rename)

    refresh = doc_subparsers.add_parser("refresh", help="Refresh the archive from its original file")
    refresh.add_argument("document", help="Document ID")
    refresh.add_argument("--resource-root", help="Allow local assets under this directory")
    refresh.set_defaults(handler=command_doc_refresh)

    remove = doc_subparsers.add_parser("remove", help="Remove a document and its archived copy")
    remove.add_argument("document", help="Document ID")
    remove.set_defaults(handler=command_doc_remove)

    move = doc_subparsers.add_parser("move", help="Move a document to a 1-based chapter position")
    move.add_argument("document", help="Document ID")
    move.add_argument("position", type=int, help="Target 1-based position")
    move.set_defaults(handler=command_doc_move)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="book",
        description="Collect learning documents into local, web-readable books.",
    )
    parser.add_argument("--data-dir", help="Override the library data directory for this command")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create the local library")
    init.set_defaults(handler=command_init)

    add = subparsers.add_parser("add", help="Add a book")
    add.add_argument("title")
    add.add_argument("--description", default="")
    add.set_defaults(handler=command_add)

    listing = subparsers.add_parser("list", help="List books")
    listing.set_defaults(handler=command_list)

    rename = subparsers.add_parser("rename", help="Rename a book")
    rename.add_argument("book", help="Book ID or exact title")
    rename.add_argument("title")
    rename.set_defaults(handler=command_rename)

    edit = subparsers.add_parser("edit", help="Edit a book's metadata")
    edit.add_argument("book", help="Book ID or exact title")
    edit.add_argument("--title")
    edit.add_argument("--description")
    edit.set_defaults(handler=command_edit_book)

    remove = subparsers.add_parser("remove", help="Remove a book")
    remove.add_argument("book", help="Book ID or exact title")
    remove.add_argument("--with-documents", action="store_true", help="Also remove archived document copies")
    remove.set_defaults(handler=command_remove_book)

    add_document_commands(subparsers)

    search = subparsers.add_parser("search", help="Search document titles and content")
    search.add_argument("query")
    search.add_argument("--book", help="Restrict search to a book ID or exact title")
    search.add_argument("--limit", type=int, default=50, help="Maximum results to show")
    search.add_argument("--offset", type=int, default=0, help="Skip this many results")
    search.set_defaults(handler=command_search)

    serve = subparsers.add_parser("serve", help="Serve the local web bookshelf")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true", help="Open the bookshelf in the default browser")
    serve.set_defaults(handler=command_serve)

    open_book = subparsers.add_parser("open", help="Open a book in the local web reader")
    open_book.add_argument("book", help="Book ID or exact title")
    open_book.add_argument("--port", type=int, default=8765)
    open_book.set_defaults(handler=command_open)

    export = subparsers.add_parser("export", help="Export the library to a ZIP backup")
    export.add_argument("path", help="Destination ZIP path")
    export.set_defaults(handler=command_export)

    restore = subparsers.add_parser("restore", help="Restore the library from a ZIP backup")
    restore.add_argument("path", help="Source ZIP path")
    restore.add_argument("--replace", action="store_true", help="Replace an existing data directory")
    restore.set_defaults(handler=command_restore)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except BookError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
