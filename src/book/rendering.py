from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from .errors import BookError
from .importer import read_text


DOCUMENT_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0;
  color: #20252d;
  background: #f7f7f4;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 18px;
  line-height: 1.8;
}
main { width: min(100% - 40px, 780px); margin: 0 auto; padding: 56px 0 96px; }
h1, h2, h3, h4, h5, h6 { color: #141920; font-family: Arial, sans-serif; line-height: 1.3; margin: 2.1em 0 .65em; }
h1 { font-size: 2em; margin-top: 0; }
h2 { font-size: 1.55em; }
h3 { font-size: 1.22em; }
p, ul, ol, blockquote, pre { margin: 0 0 1.2em; }
ul, ol { padding-left: 1.5em; }
li + li { margin-top: .35em; }
a { color: #006b6a; }
blockquote { border-left: 3px solid #9aadb2; color: #46505c; padding-left: 1em; }
pre, code { font-family: 'SFMono-Regular', Consolas, monospace; }
pre { overflow-x: auto; background: #eceeed; border: 1px solid #d7dcd9; padding: 1em; line-height: 1.55; }
code { background: #eceeed; padding: .1em .25em; }
pre code { background: transparent; padding: 0; }
img, video, audio { display: block; max-width: 100%; height: auto; margin: 1.2em 0; }
hr { border: 0; border-top: 1px solid #ccd2ce; margin: 2em 0; }
body[data-theme='dark'] { color: #e7e8e5; background: #171b20; }
body[data-theme='dark'] h1, body[data-theme='dark'] h2, body[data-theme='dark'] h3, body[data-theme='dark'] h4, body[data-theme='dark'] h5, body[data-theme='dark'] h6 { color: #f5f5f2; }
body[data-theme='dark'] a { color: #60c5bb; }
body[data-theme='dark'] blockquote { color: #bdc6c3; border-color: #71817d; }
body[data-theme='dark'] pre, body[data-theme='dark'] code { background: #252b31; border-color: #3d474e; }
@media (max-width: 640px) { body { font-size: 17px; } main { width: min(100% - 28px, 780px); padding-top: 32px; } }
"""


def _safe_url(value: str) -> str:
    value = value.strip()
    if value.casefold().startswith(("javascript:", "vbscript:")):
        return "#"
    return value


def render_inline(value: str) -> str:
    tokens: list[str] = []

    def stash(fragment: str) -> str:
        marker = f"\x00BOOKTOKEN{len(tokens)}\x00"
        tokens.append(fragment)
        return marker

    escaped = html.escape(value, quote=False)

    def code(match: re.Match[str]) -> str:
        return stash(f"<code>{html.escape(html.unescape(match.group(1)))}</code>")

    escaped = re.sub(r"`([^`]+)`", code, escaped)

    def image(match: re.Match[str]) -> str:
        alt = html.escape(html.unescape(match.group(1)), quote=True)
        source = _safe_url(html.unescape(match.group(2).strip()))
        return stash(f'<img src="{html.escape(source, quote=True)}" alt="{alt}">')

    escaped = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+[^)]*)?\)", image, escaped)

    def link(match: re.Match[str]) -> str:
        label = html.unescape(match.group(1))
        destination = _safe_url(html.unescape(match.group(2).strip()))
        return stash(
            f'<a href="{html.escape(destination, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(label)}</a>'
        )

    escaped = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+[^)]*)?\)", link, escaped)
    escaped = re.sub(
        r"\*\*(.+?)\*\*|__(.+?)__",
        lambda match: f"<strong>{match.group(1) or match.group(2)}</strong>",
        escaped,
    )
    escaped = re.sub(
        r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)|(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)",
        lambda match: f"<em>{match.group(1) or match.group(2)}</em>",
        escaped,
    )
    for index, token in enumerate(tokens):
        escaped = escaped.replace(f"\x00BOOKTOKEN{index}\x00", token)
    return escaped


def markdown_to_html(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            joined = " ".join(piece.strip() for piece in paragraph)
            output.append(f"<p>{render_inline(joined)}</p>")
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush_paragraph()
            fence = stripped[:3]
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            continue
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            output.append(f"<h{level}>{render_inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        if re.match(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$", line):
            flush_paragraph()
            output.append("<hr>")
            index += 1
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            quote: list[str] = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            output.append(f"<blockquote>{markdown_to_html(chr(10).join(quote))}</blockquote>")
            continue
        unordered = re.match(r"^\s*[-+*]\s+(.+)$", line)
        ordered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            tag = "ul" if unordered else "ol"
            items: list[str] = []
            pattern = r"^\s*[-+*]\s+(.+)$" if unordered else r"^\s*\d+[.)]\s+(.+)$"
            while index < len(lines):
                match = re.match(pattern, lines[index])
                if not match:
                    break
                items.append(f"<li>{render_inline(match.group(1))}</li>")
                index += 1
            output.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        paragraph.append(line)
        index += 1

    flush_paragraph()
    return "\n".join(output)


def document_shell(title: str, body: str, theme: str) -> str:
    safe_title = html.escape(title)
    resolved_theme = theme if theme in {"light", "dark"} else "light"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>{DOCUMENT_STYLE}</style>
</head>
<body data-theme="{resolved_theme}"><main>{body}</main></body>
</html>"""


def render_document(document: Any, bundle_dir: Path, theme: str) -> str:
    entry = bundle_dir / document["entry_path"]
    if not entry.is_file():
        raise BookError("The archived document file is missing. Run 'book doc refresh' to restore it.")
    source = read_text(entry)
    if document["document_type"] == "html":
        return source
    if document["document_type"] == "markdown":
        return document_shell(document["title"], markdown_to_html(source), theme)
    return document_shell(document["title"], f"<pre>{html.escape(source)}</pre>", theme)
