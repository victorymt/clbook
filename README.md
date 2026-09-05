# book

[中文说明](README.zh-CN.md)

`book` collects scattered learning documents into local books and opens them in a browser-based reader. It archives copies of your documents, so moving or deleting the original source later does not affect reading.

## Requirements

Python 3.10 or newer. The runtime uses only the Python standard library. The
recommended installation method uses [uv](https://docs.astral.sh/uv/).

## Install

Install `book` as an isolated command-line tool from the repository:

```bash
uv tool install .
```

After installation, verify that the command is available with `book --help`.
To reinstall it after updating the repository, run `uv tool install --force .`.

Alternatively, install it into the active Python environment with pip:

```bash
python -m pip install .
```

The library lives in `$XDG_DATA_HOME/book`, or `~/.local/share/book` when XDG is not configured. Set `BOOK_DATA_DIR` or pass `--data-dir PATH` to keep a library somewhere else.

Initialize the library explicitly when setting up a new data directory:

```bash
book init
```

## Build A Book

```bash
book add "Linear Algebra" --description "Course notes and references"
book doc add "Linear Algebra" ~/notes/vectors.md
book doc add "Linear Algebra" ~/downloads/matrices.html
book doc list "Linear Algebra"
book doc move 2 1
book doc add "Linear Algebra" ~/notes --recursive
book edit "Linear Algebra" --description "Updated references"
```

`book doc add` accepts several files and directories in one command. Directories are scanned one level deep by default; add `--recursive` to include nested files. `--title` is available when importing one file. Use `--resource-root` when a document intentionally references assets in a shared parent directory:

```bash
book doc add "Linear Algebra" ~/course/chapters/intro.html \
  --resource-root ~/course
```

Multi-file imports are atomic by default: if one source fails, earlier imports from the same command are rolled back. Add `--continue-on-error` when partial success is desired; the command returns a failure status and prints the sources that could not be imported.

The importer recognizes HTML (`.html`/`.htm`), Markdown (`.md`/`.markdown`), and plain text (`.txt`). When referenced by a document, CSS, Web App Manifests, images, fonts, and media are copied and rewritten as local assets. Other document extensions are imported as text.

Adding a document copies the source file and locally referenced images, stylesheets, fonts, and media into the library. The original file is never changed or deleted. Re-import later changes with:

```bash
book doc refresh 1
book doc rename 1 "Vectors and matrices"
book doc info 1
```

`book doc info` shows the source path, archive location, and whether the source file has changed since the last import. Refreshing re-archives the source and its local resources without deleting the original file; a previously configured `--resource-root` is reused automatically.

Successful CLI imports print the resolved source file path. The web reader shows the same path above the current chapter; the local web API includes it in document metadata.

## Read And Search

```bash
book open "Linear Algebra"
book serve --open
book search determinant --book "Linear Algebra"
```

`book open` starts a local server at `127.0.0.1:8765`, opens the selected book, and keeps running until `Ctrl-C`. The reader has a chapter list, drag-and-drop ordering, previous/next navigation, local full-text search, theme selection, saved reading positions, and average book progress. From the reader you can also create, edit, or delete books; rename, refresh, or delete chapters; select several chapters and run refresh or delete from the batch-action menu; and return to the shelf with browser history. Batch results report the requested count, successful document metadata, and failed IDs with error details, and deleting a chapter only removes its archived copy.

Theme selection applies to generated Markdown/text pages and is injected into archived HTML pages as well.

The language menu switches the interface between English (`en`) and Chinese (`zh-CN`). English is the default. The selected locale is stored in the browser under `localStorage` key `book.locale` and is restored when the reader is reloaded; theme options and other interface labels follow the selected locale.

Common Markdown tables, nested lists, task lists, strikethrough, and reference links are rendered locally. Search uses case-insensitive substring matching across book titles, chapter titles, and extracted content. Reader search results load in batches and clearly indicate when more matches are available. Links between documents in the same book are routed to the corresponding chapter content.

The local server exposes JSON endpoints under `/api` for bookshelf integrations. The API supports listing and searching books, creating/updating/deleting books, importing or removing documents, refreshing a document, reordering chapters, and saving reader state and progress. Batch chapter management is available at `POST /api/books/{book_id}/documents/batch` with a JSON body such as `{"action":"refresh","document_ids":[1,2]}`; set `action` to `delete` to remove the selected archived copies. The response contains `action`, `requested`, `succeeded`, and `failed` so clients can inspect partial results. It accepts local file paths for document imports and should only be exposed on a trusted machine.

`book serve` starts the bookshelf; add `--open` to launch it in the default browser. `book open BOOK` opens one book directly. Both commands bind to loopback only.

Use another port when needed:

```bash
book open "Linear Algebra" --port 8989
book serve --port 8989
```

HTML documents render with their archived styles in an isolated frame. Script execution, forms, plugins, and automatic remote resource loading are blocked; local archived assets remain available.

Create a portable ZIP backup with `book export PATH` and restore it with `book restore PATH`. Export refuses to overwrite an existing destination. Restore refuses to use a non-empty data directory unless `--replace` is supplied; replacement is staged and committed atomically, and the archive is validated for unsafe paths before extraction.

## Security And Archiving

Only resources inside the source file's directory tree are archived. References outside that tree are left unchanged and are not copied. Removing a book or document removes only its archived copies, never the original source files.

## Development

The repository uses `uv` for development dependencies and test execution:

```bash
uv sync
uv run pytest -q
uv build
```

The test suite covers importing and refreshing documents, resource sanitization, Markdown rendering, search, reader state, the management API, and backup/restore behavior.
