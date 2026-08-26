from __future__ import annotations

import hashlib
import html
import mimetypes
import os
import posixpath
import re
import shutil
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit, urlunsplit

from .errors import BookError


TEXTUAL_SUFFIXES = {".css", ".htm", ".html", ".md", ".markdown", ".txt"}
DOCUMENT_TYPES = {
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
}
SKIPPED_HTML_TAGS = {"script", "iframe", "object", "embed", "base"}
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
CSS_URL_PATTERN = re.compile(r"(?P<prefix>url\(\s*[\"']?)(?P<url>[^\"')]+)(?P<suffix>[\"']?\s*\))", re.I)
CSS_IMPORT_PATTERN = re.compile(
    r"(?P<prefix>@import\s+(?:url\(\s*)?[\"']?)(?P<url>[^\"')\s;]+)(?P<suffix>[\"']?\s*\)?\s*;)",
    re.I,
)
MARKDOWN_IMAGE_PATTERN = re.compile(r"(?P<prefix>!\[[^\]]*\]\()(?P<target>[^)]*)(?P<suffix>\))")


@dataclass(frozen=True)
class ArchiveResult:
    entry_path: str
    document_type: str
    content: str
    resources: list[tuple[str, str, str]]


def document_type_for(path: Path) -> str:
    return DOCUMENT_TYPES.get(path.suffix.lower(), "text")


def read_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise BookError(f"Cannot read '{path}': {error.strerror or error}.") from error
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def relative_asset_path(path: Path) -> str:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", path.name).strip(".-") or "resource"
    return (PurePosixPath("assets") / f"{digest}-{filename}").as_posix()


def _is_asset_attribute(tag: str, attr: str, attrs: dict[str, str | None]) -> bool:
    if attr in {"src", "poster", "background"}:
        return True
    if tag == "link" and attr == "href":
        rel = (attrs.get("rel") or "").lower()
        return any(value in rel for value in ("stylesheet", "icon", "preload"))
    return False


def _is_unsafe_url(value: str) -> bool:
    return value.strip().casefold().startswith(("javascript:", "vbscript:"))


def resolve_local_url(value: str, origin: Path) -> Path | None:
    parts = urlsplit(value.strip())
    if not parts.path or parts.scheme or parts.netloc or parts.path.startswith("/"):
        return None
    candidate = (origin.parent / unquote(parts.path)).resolve()
    if candidate.is_file():
        return candidate
    return None


def rewrite_url(value: str, origin: Path, output_path: str, mapping: dict[Path, str]) -> str:
    parts = urlsplit(value.strip())
    local = resolve_local_url(value, origin)
    if local is None or local not in mapping:
        return value
    start = PurePosixPath(output_path).parent.as_posix()
    relative = posixpath.relpath(mapping[local], start=start if start != "." else ".")
    return urlunsplit(("", "", relative, parts.query, parts.fragment))


def _css_urls(value: str) -> list[str]:
    return [match.group("url") for match in CSS_URL_PATTERN.finditer(value)] + [
        match.group("url") for match in CSS_IMPORT_PATTERN.finditer(value)
    ]


def srcset_urls(value: str) -> list[str]:
    urls: list[str] = []
    for candidate in value.split(","):
        target = candidate.strip().split(maxsplit=1)[0]
        if target:
            urls.append(target)
    return urls


def rewrite_srcset(value: str, origin: Path, output_path: str, mapping: dict[Path, str]) -> str:
    rewritten: list[str] = []
    for candidate in value.split(","):
        parts = candidate.strip().split(maxsplit=1)
        if not parts:
            continue
        resolved = rewrite_url(parts[0], origin, output_path, mapping)
        rewritten.append(" ".join([resolved, *parts[1:]]))
    return ", ".join(rewritten)


def rewrite_css(value: str, origin: Path, output_path: str, mapping: dict[Path, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{rewrite_url(match.group('url'), origin, output_path, mapping)}{match.group('suffix')}"

    value = CSS_URL_PATTERN.sub(replace, value)
    return CSS_IMPORT_PATTERN.sub(replace, value)


class AssetReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.urls: list[str] = []
        self.style_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        for name, value in attrs:
            if value and _is_asset_attribute(tag.lower(), name.lower(), attributes):
                self.urls.append(value)
            if value and name.lower() == "srcset":
                self.urls.extend(srcset_urls(value))
            if value and name.lower() == "style":
                self.urls.extend(_css_urls(value))
        if tag.lower() == "style":
            self.style_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style" and self.style_depth:
            self.style_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.style_depth:
            self.urls.extend(_css_urls(data))


class HtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "template", "noscript"}:
            self.ignored_depth += 1
        if normalized == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "template", "noscript"} and self.ignored_depth:
            self.ignored_depth -= 1
        if normalized == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            candidate = " ".join(data.split())
            if candidate:
                self.title = (self.title or "") + candidate
        if not self.ignored_depth:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return "\n".join(part.strip() for part in self.parts if part.strip())


class HtmlRewriter(HTMLParser):
    def __init__(self, origin: Path, output_path: str, mapping: dict[Path, str]) -> None:
        super().__init__(convert_charrefs=False)
        self.origin = origin
        self.output_path = output_path
        self.mapping = mapping
        self.output: list[str] = []
        self.skip_depth = 0
        self.style_depth = 0

    def _write_tag(self, tag: str, attrs: list[tuple[str, str | None]], closing: bool = False) -> None:
        normalized = tag.lower()
        if closing:
            if normalized not in VOID_TAGS:
                self.output.append(f"</{tag}>")
            return
        attributes = dict(attrs)
        rewritten: list[str] = []
        for name, value in attrs:
            lowered = name.lower()
            if lowered.startswith("on"):
                continue
            if value is not None:
                if _is_unsafe_url(value):
                    continue
                if _is_asset_attribute(normalized, lowered, attributes):
                    value = rewrite_url(value, self.origin, self.output_path, self.mapping)
                elif lowered == "srcset":
                    value = rewrite_srcset(value, self.origin, self.output_path, self.mapping)
                elif lowered == "style":
                    value = rewrite_css(value, self.origin, self.output_path, self.mapping)
                rewritten.append(f' {name}="{html.escape(value, quote=True)}"')
            else:
                rewritten.append(f" {name}")
        self.output.append(f"<{tag}{''.join(rewritten)}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth:
            self.skip_depth += 1
            return
        if tag.lower() in SKIPPED_HTML_TAGS:
            self.skip_depth = 1
            return
        self._write_tag(tag, attrs)
        if tag.lower() == "style":
            self.style_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.skip_depth and tag.lower() not in SKIPPED_HTML_TAGS:
            self._write_tag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag.lower() == "style" and self.style_depth:
            self.style_depth -= 1
        self._write_tag(tag, [], closing=True)

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.output.append(
                rewrite_css(data, self.origin, self.output_path, self.mapping) if self.style_depth else data
            )

    def handle_comment(self, data: str) -> None:
        if not self.skip_depth:
            self.output.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        if not self.skip_depth:
            self.output.append(f"<!{decl}>")

    def handle_entityref(self, name: str) -> None:
        if not self.skip_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skip_depth:
            self.output.append(f"&#{name};")


def html_references(text: str) -> list[str]:
    parser = AssetReferenceParser()
    parser.feed(text)
    parser.close()
    return parser.urls


def rewrite_html(text: str, origin: Path, output_path: str, mapping: dict[Path, str]) -> str:
    parser = HtmlRewriter(origin, output_path, mapping)
    parser.feed(text)
    parser.close()
    return "".join(parser.output)


def markdown_image_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in MARKDOWN_IMAGE_PATTERN.finditer(text):
        target = match.group("target").strip()
        if target.startswith("<") and ">" in target:
            urls.append(target[1 : target.index(">")])
        elif target:
            urls.append(target.split(maxsplit=1)[0])
    return urls


def rewrite_markdown_images(text: str, origin: Path, output_path: str, mapping: dict[Path, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        original = match.group("target").strip()
        if original.startswith("<") and ">" in original:
            end = original.index(">")
            url, rest = original[1:end], original[end + 1 :]
            rewritten = f"<{rewrite_url(url, origin, output_path, mapping)}>{rest}"
        elif original:
            parts = original.split(maxsplit=1)
            rewritten = rewrite_url(parts[0], origin, output_path, mapping)
            if len(parts) == 2:
                rewritten += " " + parts[1]
        else:
            rewritten = original
        return f"{match.group('prefix')}{rewritten}{match.group('suffix')}"

    return MARKDOWN_IMAGE_PATTERN.sub(replace, text)


def references_for(path: Path, text: str) -> list[str]:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return html_references(text)
    if suffix == ".css":
        return _css_urls(text)
    if suffix in {".md", ".markdown"}:
        return markdown_image_urls(text)
    return []


def archive_document(source_path: Path, destination: Path) -> ArchiveResult:
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise BookError(f"'{source_path}' is not a readable file.")

    document_type = document_type_for(source_path)
    source_text = read_text(source_path)
    mapping: dict[Path, str] = {}
    pending: list[Path] = []

    def register(value: str, origin: Path) -> None:
        target = resolve_local_url(value, origin)
        if target is not None and target != source_path and target not in mapping:
            mapping[target] = relative_asset_path(target)
            pending.append(target)

    for reference in references_for(source_path, source_text):
        register(reference, source_path)

    while pending:
        resource = pending.pop()
        if resource.suffix.lower() not in TEXTUAL_SUFFIXES:
            continue
        for reference in references_for(resource, read_text(resource)):
            register(reference, resource)

    destination.mkdir(parents=True, exist_ok=False)
    entry_path = f"entry{source_path.suffix.lower() or '.txt'}"
    entry_file = destination / entry_path
    if document_type == "html":
        entry_file.write_text(rewrite_html(source_text, source_path, entry_path, mapping), encoding="utf-8")
        parser = HtmlTextParser()
        parser.feed(source_text)
        parser.close()
        content = parser.text
    elif document_type == "markdown":
        entry_file.write_text(
            rewrite_markdown_images(source_text, source_path, entry_path, mapping), encoding="utf-8"
        )
        content = source_text
    else:
        entry_file.write_text(source_text, encoding="utf-8")
        content = source_text

    resources: list[tuple[str, str, str]] = []
    for resource, resource_path in mapping.items():
        output = destination / resource_path
        output.parent.mkdir(parents=True, exist_ok=True)
        if resource.suffix.lower() in {".css", ".html", ".htm"}:
            resource_text = read_text(resource)
            if resource.suffix.lower() == ".css":
                resource_text = rewrite_css(resource_text, resource, resource_path, mapping)
            else:
                resource_text = rewrite_html(resource_text, resource, resource_path, mapping)
            output.write_text(resource_text, encoding="utf-8")
        else:
            shutil.copy2(resource, output)
        mime_type = mimetypes.guess_type(resource.name)[0] or "application/octet-stream"
        resources.append((str(resource), resource_path, mime_type))

    return ArchiveResult(
        entry_path=entry_path,
        document_type=document_type,
        content=content,
        resources=resources,
    )


def suggested_title(source_path: Path, document_type: str, content: str) -> str:
    if document_type == "markdown":
        for line in content.splitlines():
            match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
            if match:
                return match.group(1).strip()
    if document_type == "html":
        parser = HtmlTextParser()
        parser.feed(content)
        parser.close()
        if parser.title:
            return parser.title.strip()
    return source_path.stem or source_path.name


def replace_archive(source_path: Path, target_dir: Path) -> ArchiveResult:
    temporary = target_dir.parent / f".{target_dir.name}.refresh-{os.getpid()}"
    suffix = 1
    while temporary.exists():
        suffix += 1
        temporary = target_dir.parent / f".{target_dir.name}.refresh-{os.getpid()}-{suffix}"
    try:
        result = archive_document(source_path, temporary)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    backup = target_dir.parent / f".{target_dir.name}.previous-{os.getpid()}"
    try:
        if target_dir.exists():
            target_dir.replace(backup)
        temporary.replace(target_dir)
    except Exception:
        if target_dir.exists() and not backup.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        if backup.exists():
            backup.replace(target_dir)
        raise
    else:
        shutil.rmtree(backup, ignore_errors=True)
    return result
