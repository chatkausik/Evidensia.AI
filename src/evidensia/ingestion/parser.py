from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


@dataclass(slots=True)
class ParsedSection:
    heading: str
    text: str
    level: int = 1
    page_number: int | None = None


@dataclass(slots=True)
class ParsedDocument:
    title: str
    document_type: str
    text: str
    sections: list[ParsedSection] = field(default_factory=list)
    source_uri: str | None = None


class _ReadableHTML(HTMLParser):
    block_tags = {"p", "li", "blockquote", "pre", "table", "tr"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self.headings: list[tuple[int, str, int]] = []
        self._buffer: list[str] = []
        self._heading_level: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self._heading_level = int(tag[1])
        elif tag in self.block_tags:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.block_tags or tag.startswith("h"):
            self._flush()

    def handle_data(self, data: str) -> None:
        normalized = re.sub(r"\s+", " ", data).strip()
        if normalized:
            self._buffer.append(normalized)

    def _flush(self) -> None:
        text = " ".join(self._buffer).strip()
        if text:
            self.blocks.append(text)
            if self._heading_level is not None:
                self.headings.append((len(self.blocks) - 1, text, self._heading_level))
        self._buffer = []
        self._heading_level = None


class DocumentParser:
    """Parse supported research artifacts into heading-aware sections."""

    _heading = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    _paper_sections = {
        "abstract",
        "introduction",
        "related work",
        "background",
        "methodology",
        "methods",
        "experiments",
        "results",
        "discussion",
        "limitations",
        "conclusion",
        "references",
    }

    def parse(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        source_uri: str | None = None,
    ) -> ParsedDocument:
        suffix = Path(filename).suffix.lower()
        mime = (content_type or "").lower()
        if suffix == ".pdf" or "pdf" in mime:
            return self._parse_pdf(filename, content, source_uri)
        decoded = content.decode("utf-8", errors="replace").replace("\x00", "")
        if suffix in {".html", ".htm"} or "html" in mime:
            return self._parse_html(filename, decoded, source_uri)
        if suffix in {".md", ".markdown"} or "markdown" in mime:
            return self._parse_markdown(filename, decoded, source_uri)
        return self._parse_text(filename, decoded, source_uri)

    def _parse_pdf(self, filename: str, content: bytes, source_uri: str | None) -> ParsedDocument:
        reader = PdfReader(BytesIO(content))
        sections: list[ParsedSection] = []
        pages: list[str] = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            pages.append(text)
            page_sections = self._sections_from_lines(text, page_number=number)
            if page_sections:
                sections.extend(page_sections)
            else:
                sections.append(ParsedSection(heading=f"Page {number}", text=text, page_number=number))
        metadata_title = getattr(reader.metadata, "title", None) if reader.metadata else None
        title = (metadata_title or self._first_title(pages[0] if pages else "") or Path(filename).stem).strip()
        return ParsedDocument(
            title=title,
            document_type=self._classify_document("\n".join(pages)),
            text="\n\n".join(pages),
            sections=sections or [ParsedSection(heading="Document", text="No extractable text")],
            source_uri=source_uri,
        )

    def _parse_html(self, filename: str, text: str, source_uri: str | None) -> ParsedDocument:
        parser = _ReadableHTML()
        parser.feed(text)
        parser._flush()
        blocks = parser.blocks
        sections: list[ParsedSection] = []
        headings = {index: (heading, level) for index, heading, level in parser.headings}
        current_heading = "Document"
        current_level = 1
        body: list[str] = []
        for index, block in enumerate(blocks):
            if index in headings:
                if body:
                    sections.append(ParsedSection(current_heading, "\n\n".join(body), current_level))
                current_heading, current_level = headings[index]
                body = []
            else:
                body.append(block)
        if body:
            sections.append(ParsedSection(current_heading, "\n\n".join(body), current_level))
        plain = "\n\n".join(blocks)
        title = parser.headings[0][1] if parser.headings else self._first_title(plain) or Path(filename).stem
        return ParsedDocument(title, self._classify_document(plain), plain, sections or [ParsedSection("Document", plain)], source_uri)

    def _parse_markdown(self, filename: str, text: str, source_uri: str | None) -> ParsedDocument:
        sections = self._sections_from_lines(text)
        title = next((section.heading for section in sections if section.level == 1), None)
        return ParsedDocument(
            title=title or self._first_title(text) or Path(filename).stem,
            document_type=self._classify_document(text),
            text=text.strip(),
            sections=sections or [ParsedSection("Document", text.strip())],
            source_uri=source_uri,
        )

    def _parse_text(self, filename: str, text: str, source_uri: str | None) -> ParsedDocument:
        clean = re.sub(r"\r\n?", "\n", text).strip()
        sections = self._sections_from_lines(clean)
        return ParsedDocument(
            title=self._first_title(clean) or Path(filename).stem,
            document_type=self._classify_document(clean),
            text=clean,
            sections=sections or [ParsedSection("Document", clean)],
            source_uri=source_uri,
        )

    def _sections_from_lines(self, text: str, page_number: int | None = None) -> list[ParsedSection]:
        sections: list[ParsedSection] = []
        heading = "Document"
        level = 1
        body: list[str] = []

        def flush() -> None:
            payload = "\n".join(body).strip()
            if payload:
                sections.append(ParsedSection(heading, payload, level, page_number))

        for raw in text.splitlines():
            line = raw.strip()
            match = self._heading.match(line)
            plain_heading = (
                2 <= len(line) <= 90
                and line.lower().rstrip(":") in self._paper_sections
            )
            if match or plain_heading:
                flush()
                if match:
                    heading = match.group(2).strip()
                    level = len(match.group(1))
                else:
                    heading = line.rstrip(":")
                    level = 1
                body = []
            else:
                body.append(raw)
        flush()
        return sections

    @staticmethod
    def _first_title(text: str) -> str | None:
        for raw in text.splitlines():
            candidate = re.sub(r"^#+\s*", "", raw).strip()
            if 4 <= len(candidate) <= 180:
                return candidate
        return None

    def _classify_document(self, text: str) -> str:
        lowered = text.lower()
        paper_hits = sum(section in lowered for section in self._paper_sections)
        if paper_hits >= 4 or "doi:" in lowered or ("authors:" in lowered and "abstract" in lowered):
            return "research_paper"
        if "api" in lowered and ("installation" in lowered or "configuration" in lowered):
            return "technical_document"
        if "executive summary" in lowered or "market report" in lowered:
            return "report"
        return "document"
