from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from evidensia.connectors import ArxivConnector, OpenAlexConnector
from evidensia.connectors.http import PaperSourceError, get_document
from evidensia.models import (
    DiscoveredPaper,
    DocumentRecord,
    PaperDiscoveryRequest,
    PaperDiscoveryResponse,
    PaperImportResponse,
)
from evidensia.services.knowledge import KnowledgeService


def _normalized_doi(value: str | None) -> str | None:
    return value.lower().removeprefix("https://doi.org/").strip() if value else None


def _title_key(paper: DiscoveredPaper) -> str:
    title = re.sub(r"[^a-z0-9]+", " ", paper.title.lower()).strip()
    author = re.sub(r"[^a-z0-9]+", "", paper.authors[0].lower()) if paper.authors else ""
    return f"{title}|{author}|{paper.published_at.year}"


def _merge(existing: DiscoveredPaper, candidate: DiscoveredPaper) -> DiscoveredPaper:
    topics = list(dict.fromkeys([*existing.topics, *candidate.topics]))
    categories = list(dict.fromkeys([*existing.categories, *candidate.categories]))
    providers = list(dict.fromkeys([*existing.providers, *candidate.providers]))
    return existing.model_copy(update={
        "providers": providers,
        "external_ids": {**existing.external_ids, **candidate.external_ids},
        "abstract": candidate.abstract if len(candidate.abstract) > len(existing.abstract) else existing.abstract,
        "authors": existing.authors or candidate.authors,
        "updated_at": max(filter(None, [existing.updated_at, candidate.updated_at]), default=None),
        "venue": existing.venue or candidate.venue,
        "doi": existing.doi or candidate.doi,
        "categories": categories,
        "topics": topics,
        "landing_url": existing.landing_url or candidate.landing_url,
        "pdf_url": existing.pdf_url or candidate.pdf_url,
        "open_access": existing.open_access or candidate.open_access,
        "license": existing.license or candidate.license,
        "citation_count": max(filter(lambda value: value is not None, [existing.citation_count, candidate.citation_count]), default=None),
    })


class PaperDiscoveryService:
    """Discover paper metadata, deduplicate it, and import selected abstracts."""

    def __init__(
        self,
        knowledge: KnowledgeService,
        arxiv: ArxivConnector | None = None,
        openalex: OpenAlexConnector | None = None,
        fetch_document: Callable[[str], tuple[bytes, str]] | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.connectors = {
            "arxiv": arxiv or ArxivConnector(),
            "openalex": openalex or OpenAlexConnector(),
        }
        self.discovered: dict[str, DiscoveredPaper] = {}
        self.imported: dict[str, str] = {}
        self._fetch_document = fetch_document or get_document

    def discover(self, request: PaperDiscoveryRequest) -> PaperDiscoveryResponse:
        warnings: list[str] = []
        collected: list[DiscoveredPaper] = []
        for provider in request.providers:
            try:
                collected.extend(self.connectors[provider].discover(request))
            except PaperSourceError as exc:
                warnings.append(f"{provider}: {exc}")

        papers = self._deduplicate(collected)[: request.limit]
        self.discovered.update({paper.paper_id: paper for paper in papers})
        return PaperDiscoveryResponse(
            query=request.query,
            providers=request.providers,
            papers=papers,
            warnings=warnings,
        )

    def import_papers(self, paper_ids: list[str], *, full_text: bool = True) -> PaperImportResponse:
        imported: list[DocumentRecord] = []
        skipped: list[str] = []
        missing: list[str] = []
        abstract_fallbacks: list[str] = []
        for paper_id in dict.fromkeys(paper_ids):
            paper = self.discovered.get(paper_id)
            if not paper:
                missing.append(paper_id)
                continue
            existing_document_id = self.imported.get(paper_id) or self._existing_document_id(paper)
            if existing_document_id:
                self.imported[paper_id] = existing_document_id
                skipped.append(paper_id)
                continue
            filename = self._filename(paper, ".md")
            content = self._as_markdown(paper).encode("utf-8")
            content_type = "text/markdown"
            if full_text and (pdf_url := self._trusted_arxiv_pdf_url(paper)):
                try:
                    content, content_type = self._fetch_document(pdf_url)
                    filename = self._filename(paper, ".pdf")
                except PaperSourceError:
                    abstract_fallbacks.append(paper_id)
            elif full_text:
                abstract_fallbacks.append(paper_id)
            document = self.knowledge.ingest(
                filename,
                content,
                content_type,
                paper.landing_url,
                self._metadata_overrides(paper),
            )
            if document.status != "indexed" and content_type == "application/pdf":
                if paper_id not in abstract_fallbacks:
                    abstract_fallbacks.append(paper_id)
                document = self.knowledge.ingest(
                    self._filename(paper, ".md"),
                    self._as_markdown(paper).encode("utf-8"),
                    "text/markdown",
                    paper.landing_url,
                    self._metadata_overrides(paper),
                    document_id=document.document_id,
                )
            if document.status == "indexed":
                self.imported[paper_id] = document.document_id
                imported.append(document)
            else:
                skipped.append(paper_id)
        return PaperImportResponse(
            imported=imported,
            skipped=skipped,
            missing=missing,
            abstract_fallbacks=abstract_fallbacks,
        )

    def _existing_document_id(self, paper: DiscoveredPaper) -> str | None:
        paper_doi = _normalized_doi(paper.doi)
        for document in self.knowledge.documents.values():
            if document.source_uri == paper.landing_url:
                return document.document_id
            if paper_doi and document.metadata and _normalized_doi(document.metadata.doi) == paper_doi:
                return document.document_id
        return None

    @staticmethod
    def _deduplicate(papers: list[DiscoveredPaper]) -> list[DiscoveredPaper]:
        output: list[DiscoveredPaper] = []
        positions: dict[str, int] = {}
        for paper in papers:
            keys = [_title_key(paper)]
            if doi := _normalized_doi(paper.doi):
                keys.insert(0, f"doi:{doi}")
            position = next((positions[key] for key in keys if key in positions), None)
            if position is None:
                position = len(output)
                output.append(paper)
            else:
                output[position] = _merge(output[position], paper)
            for key in keys:
                positions[key] = position
        return sorted(output, key=lambda paper: paper.published_at, reverse=True)

    @staticmethod
    def _filename(paper: DiscoveredPaper, suffix: str) -> str:
        stem = re.sub(r"[^a-zA-Z0-9]+", "-", paper.title).strip("-").lower()[:90]
        return f"{paper.published_at.year}-{stem}{suffix}"

    @staticmethod
    def _trusted_arxiv_pdf_url(paper: DiscoveredPaper) -> str | None:
        if "arxiv" not in paper.providers or not paper.pdf_url:
            return None
        parsed = urlsplit(paper.pdf_url)
        if parsed.hostname not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
            return None
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))

    @staticmethod
    def _metadata_overrides(paper: DiscoveredPaper) -> dict[str, object]:
        values: dict[str, object] = {
            "title": paper.title,
            "authors": paper.authors,
            "publication_year": paper.published_at.year,
            "publication_date": paper.published_at,
            "topics": list(dict.fromkeys([*paper.topics, *paper.categories])),
            "document_type": "research_paper",
            "extraction_confidence": 0.98,
        }
        if paper.venue:
            values["venue"] = paper.venue
        if paper.doi:
            values["doi"] = paper.doi
        return values

    @staticmethod
    def _as_markdown(paper: DiscoveredPaper) -> str:
        fields = [
            f"# {paper.title}",
            f"Authors: {', '.join(paper.authors)}" if paper.authors else "Authors: Unknown",
            f"Published: {paper.published_at.isoformat()}",
            f"Providers: {', '.join(paper.providers)}",
        ]
        if paper.venue:
            fields.append(f"Venue: {paper.venue}")
        if paper.doi:
            fields.append(f"DOI: {paper.doi}")
        if paper.categories:
            fields.append(f"Categories: {', '.join(paper.categories)}")
        if paper.topics:
            fields.append(f"Topics: {', '.join(paper.topics)}")
        fields.extend([
            f"Open access: {'yes' if paper.open_access else 'unknown or restricted'}",
            f"License: {paper.license or 'not supplied by source'}",
            f"Source: {paper.landing_url}",
            "",
            "## Abstract",
            paper.abstract,
            "",
            "## Provenance note",
            f"Metadata retrieved by Evidensia on {datetime.now(timezone.utc).date().isoformat()}. This abstract fallback preserves provenance; follow the source link for the repository or publisher version.",
        ])
        return "\n".join(fields)
