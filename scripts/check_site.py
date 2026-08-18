#!/usr/bin/env python3
"""Dependency-free checks for the static Badger Co. website."""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_SCHEMES = {"data", "http", "https", "mailto", "tel", "javascript"}
ASSET_TAGS = {
    "img": {"src"},
    "script": {"src"},
    "source": {"src", "srcset"},
    "video": {"poster", "src"},
}
CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")
CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


class PageParser(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.ids: dict[str, int] = {}
        self.assets: list[tuple[str, int]] = []
        self.links: list[tuple[str, int]] = []
        self.errors: list[tuple[int, str]] = []
        self.has_charset = False
        self.has_viewport = False
        self.has_lang = False
        self.title_count = 0
        self.in_head = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line = self.getpos()[0]
        values = {key.lower(): value for key, value in attrs}

        if tag == "head":
            self.in_head = True
        if tag == "html" and values.get("lang"):
            self.has_lang = True
        if tag == "title" and self.in_head:
            self.title_count += 1
        if tag == "meta":
            self.has_charset |= bool(values.get("charset"))
            self.has_viewport |= values.get("name", "").lower() == "viewport"

        element_id = values.get("id")
        if element_id:
            if element_id in self.ids:
                self.errors.append((line, f'duplicate id "{element_id}"; first used on line {self.ids[element_id]}'))
            else:
                self.ids[element_id] = line

        if tag == "img" and values.get("alt") is None:
            self.errors.append((line, "image is missing an alt attribute"))

        for attribute in ASSET_TAGS.get(tag, set()):
            value = values.get(attribute)
            if value:
                if attribute == "srcset":
                    self.assets.extend((item.strip().split()[0], line) for item in value.split(",") if item.strip())
                else:
                    self.assets.append((value, line))

        if tag == "link" and values.get("href"):
            rel = set((values.get("rel") or "").lower().split())
            if rel.intersection({"stylesheet", "icon", "apple-touch-icon", "manifest", "preload"}):
                self.assets.append((values["href"], line))

        if tag == "a" and values.get("href"):
            self.links.append((values["href"], line))

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False


def local_path(source: Path, reference: str) -> Path | None:
    parsed = urlsplit(reference.strip())
    if parsed.scheme.lower() in EXTERNAL_SCHEMES or parsed.netloc:
        return None
    raw_path = unquote(parsed.path)
    if not raw_path:
        return None
    if raw_path.startswith("/"):
        return ROOT / raw_path.lstrip("/")
    return source.parent / raw_path


def annotation(level: str, path: Path, line: int, message: str) -> None:
    relative = path.relative_to(ROOT)
    print(f"::{level} file={relative},line={line}::{message}")


def check_asset(source: Path, reference: str, line: int, errors: list[str]) -> None:
    target = local_path(source, reference)
    if target is None:
        return
    if not target.resolve().is_relative_to(ROOT.resolve()):
        message = f'asset path escapes the repository: "{reference}"'
        annotation("error", source, line, message)
        errors.append(message)
    elif not target.exists():
        message = f'missing local asset: "{reference}"'
        annotation("error", source, line, message)
        errors.append(message)


def main() -> int:
    html_files = sorted(ROOT.glob("*.html"))
    css_files = sorted(ROOT.glob("*.css"))
    errors: list[str] = []
    missing_links: dict[str, list[tuple[Path, int]]] = {}

    if not html_files:
        print("::error::No HTML files found at the repository root")
        return 1
    if not (ROOT / "index.html").exists():
        print("::error::index.html is required for GitHub Pages")
        return 1

    for path in html_files:
        text = path.read_text(encoding="utf-8")
        parser = PageParser(path)
        parser.feed(text)
        parser.close()

        for marker in CONFLICT_MARKERS:
            if marker in text:
                parser.errors.append((1, f'unresolved Git conflict marker: "{marker}"'))

        if not parser.has_lang:
            parser.errors.append((1, "html element is missing a lang attribute"))
        if not parser.has_charset:
            parser.errors.append((1, "page is missing a charset declaration"))
        if not parser.has_viewport:
            parser.errors.append((1, "page is missing a viewport meta tag"))
        if parser.title_count != 1:
            parser.errors.append((1, f"expected exactly one title element; found {parser.title_count}"))

        for line, message in parser.errors:
            annotation("error", path, line, message)
            errors.append(f"{path.name}:{line}: {message}")

        for reference, line in parser.assets:
            check_asset(path, reference, line, errors)

        for reference, line in parser.links:
            target = local_path(path, reference)
            if target is not None and not target.exists():
                missing_links.setdefault(reference, []).append((path, line))

        for match in CSS_URL.finditer(text):
            check_asset(path, match.group(2), text.count("\n", 0, match.start()) + 1, errors)

    for path in css_files:
        text = path.read_text(encoding="utf-8")
        for marker in CONFLICT_MARKERS:
            if marker in text:
                annotation("error", path, 1, f'unresolved Git conflict marker: "{marker}"')
                errors.append(f"{path.name}: unresolved conflict marker")
        if text.count("{") != text.count("}"):
            annotation("error", path, 1, "unbalanced CSS braces")
            errors.append(f"{path.name}: unbalanced CSS braces")
        for match in CSS_URL.finditer(text):
            check_asset(path, match.group(2), text.count("\n", 0, match.start()) + 1, errors)

    for reference, occurrences in sorted(missing_links.items()):
        path, line = occurrences[0]
        annotation(
            "warning",
            path,
            line,
            f'local link target does not exist: "{reference}" ({len(occurrences)} references)',
        )

    print(f"Checked {len(html_files)} HTML files and {len(css_files)} CSS files.")
    print(f"Result: {len(errors)} error(s), {len(missing_links)} link warning(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
