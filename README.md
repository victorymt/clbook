# book

[中文说明](README.zh-CN.md)

`book` collects scattered learning documents into local books and opens them in a browser-based reader. It archives copies of your documents, so moving or deleting the original source later does not affect reading.

## Install

```bash
python -m pip install -e .
```

The library lives in `$XDG_DATA_HOME/book`, or `~/.local/share/book` when XDG is not configured. Set `BOOK_DATA_DIR` or pass `--data-dir PATH` to keep a library somewhere else.

## Build A Book

```bash
book add "Linear Algebra" --description "Course notes and references"
book doc add "Linear Algebra" ~/notes/vectors.md
book doc add "Linear Algebra" ~/downloads/matrices.html
book doc list "Linear Algebra"
book doc move 2 1
```

Adding a document copies the source file and locally referenced images, stylesheets, fonts, and media into the library. The original file is never changed or deleted. Re-import later changes with:

```bash
book doc refresh 1
```

## Read And Search

```bash
book open "Linear Algebra"
book serve --open
book search determinant --book "Linear Algebra"
```

`book open` starts a local server at `127.0.0.1:8765`, opens the selected book, and keeps running until `Ctrl-C`. The reader has a chapter list, drag-and-drop ordering, previous/next navigation, local full-text search, theme selection, and saved reading positions.

Use another port when needed:

```bash
book open "Linear Algebra" --port 8989
```

HTML documents render with their archived styles in an isolated frame. Script execution, forms, plugins, and automatic remote resource loading are blocked; local archived assets remain available.
