from datetime import date
from io import BytesIO

from pypdf import PdfWriter

from evidensia.connectors.arxiv import ArxivConnector
from evidensia.connectors.http import PaperSourceError
from evidensia.connectors.openalex import OpenAlexConnector
from evidensia.connectors.crossref import CrossrefConnector
from evidensia.connectors.semantic_scholar import SemanticScholarConnector
from evidensia.models import DiscoveredPaper, PaperDiscoveryRequest
from evidensia.services.knowledge import KnowledgeService
from evidensia.services.paper_discovery import PaperDiscoveryService


ARXIV_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>https://arxiv.org/abs/2601.01234v2</id>
    <updated>2026-02-03T12:00:00Z</updated>
    <published>2026-01-30T12:00:00Z</published>
    <title>Agentic Retrieval for Enterprise Questions</title>
    <summary>We evaluate a multi-hop retrieval agent on enterprise question answering.</summary>
    <author><name>Ada Researcher</name></author>
    <category term="cs.AI" />
    <category term="cs.LG" />
    <link href="https://arxiv.org/abs/2601.01234v2" rel="alternate" />
    <link href="https://arxiv.org/pdf/2601.01234v2" title="pdf" />
    <arxiv:doi>10.1234/example.2026</arxiv:doi>
    <arxiv:journal_ref>Journal of Evidence 4 (2026)</arxiv:journal_ref>
  </entry>
</feed>"""


OPENALEX_RESPONSE = {
    "results": [{
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1234/example.2026",
        "display_name": "Agentic Retrieval for Enterprise Questions",
        "publication_date": "2026-01-30",
        "type": "article",
        "authorships": [{"author": {"display_name": "Ada Researcher"}}],
        "abstract_inverted_index": {
            "We": [0], "evaluate": [1], "agentic": [2], "retrieval": [3], "carefully.": [4]
        },
        "primary_location": {
            "landing_page_url": "https://doi.org/10.1234/example.2026",
            "source": {"display_name": "Journal of Evidence"},
        },
        "best_oa_location": {"pdf_url": "https://example.org/paper.pdf", "license": "cc-by"},
        "open_access": {"is_oa": True},
        "topics": [{"display_name": "Retrieval Augmented Generation"}],
        "cited_by_count": 12,
    }]
}


def _request() -> PaperDiscoveryRequest:
    return PaperDiscoveryRequest(
        query="agentic retrieval",
        date_from=date(2025, 1, 1),
        date_to=date(2026, 8, 20),
        providers=["arxiv", "openalex"],
    )


def test_arxiv_builds_bounded_query_and_normalizes_atom_feed() -> None:
    connector = ArxivConnector(fetch=lambda _: ARXIV_FEED)
    papers = connector.discover(_request())

    assert len(papers) == 1
    assert papers[0].paper_id == "arxiv:2601.01234"
    assert papers[0].version == "v2"
    assert papers[0].categories == ["cs.AI", "cs.LG"]
    assert papers[0].doi == "10.1234/example.2026"


def test_openalex_reconstructs_abstract_and_source_metadata() -> None:
    connector = OpenAlexConnector(api_key="", fetch=lambda _: OPENALEX_RESPONSE)
    papers = connector.discover(_request())

    assert len(papers) == 1
    assert papers[0].abstract == "We evaluate agentic retrieval carefully."
    assert papers[0].venue == "Journal of Evidence"
    assert papers[0].open_access is True
    assert papers[0].citation_count == 12


def test_discovery_deduplicates_sources_and_imports_abstract_once() -> None:
    arxiv = ArxivConnector(fetch=lambda _: ARXIV_FEED)
    openalex = OpenAlexConnector(api_key="test", fetch=lambda _: OPENALEX_RESPONSE)
    knowledge = KnowledgeService()
    service = PaperDiscoveryService(knowledge, arxiv=arxiv, openalex=openalex)

    discovery = service.discover(_request())
    assert len(discovery.papers) == 1
    assert discovery.papers[0].providers == ["arxiv", "openalex"]

    first_import = service.import_papers([discovery.papers[0].paper_id], full_text=False)
    second_import = service.import_papers([discovery.papers[0].paper_id], full_text=False)

    assert len(first_import.imported) == 1
    assert first_import.imported[0].metadata is not None
    assert first_import.imported[0].metadata.publication_date == date(2026, 1, 30)
    assert first_import.imported[0].metadata.venue == "Journal of Evidence 4 (2026)"
    assert second_import.skipped == [discovery.papers[0].paper_id]
    assert len(knowledge.documents) == 1


def test_import_reports_unknown_discovery_ids() -> None:
    service = PaperDiscoveryService(KnowledgeService())
    result = service.import_papers(["arxiv:missing"])
    assert result.missing == ["arxiv:missing"]
    assert result.imported == []


def test_arxiv_full_text_import_extracts_pdf_and_preserves_discovery_metadata() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_metadata({"/Title": "PDF title that should be overridden"})
    buffer = BytesIO()
    writer.write(buffer)

    arxiv = ArxivConnector(fetch=lambda _: ARXIV_FEED)
    knowledge = KnowledgeService()
    service = PaperDiscoveryService(
        knowledge,
        arxiv=arxiv,
        fetch_document=lambda _: (buffer.getvalue(), "application/pdf"),
    )
    discovery = service.discover(_request().model_copy(update={"providers": ["arxiv"]}))
    result = service.import_papers([discovery.papers[0].paper_id], full_text=True)

    assert len(result.imported) == 1
    document = result.imported[0]
    assert document.filename.endswith(".pdf")
    assert document.metadata is not None
    assert document.metadata.title == "Agentic Retrieval for Enterprise Questions"
    assert document.metadata.authors == ["Ada Researcher"]
    assert document.metadata.topics == ["cs.AI", "cs.LG"]
    assert result.abstract_fallbacks == []


def test_arxiv_download_failure_imports_abstract_fallback() -> None:
    def fail_download(_: str) -> tuple[bytes, str]:
        raise PaperSourceError("download unavailable")

    service = PaperDiscoveryService(
        KnowledgeService(),
        arxiv=ArxivConnector(fetch=lambda _: ARXIV_FEED),
        fetch_document=fail_download,
    )
    discovery = service.discover(_request().model_copy(update={"providers": ["arxiv"]}))
    result = service.import_papers([discovery.papers[0].paper_id], full_text=True)

    assert len(result.imported) == 1
    assert result.imported[0].filename.endswith(".md")
    assert result.abstract_fallbacks == [discovery.papers[0].paper_id]


def test_semantic_scholar_discovery_and_citation_graph() -> None:
    def fetch(url: str):
        if "/references?" in url:
            return {"data": [{"citedPaper": {"paperId": "P2", "title": "Referenced work", "year": 2024, "citationCount": 8, "url": "https://example.org/p2"}}]}
        if "/citations?" in url:
            return {"data": [{"citingPaper": {"paperId": "P3", "title": "Citing work", "year": 2026, "citationCount": 2, "url": "https://example.org/p3"}}]}
        if "/paper/P1?" in url:
            return {"paperId": "P1", "title": "Agentic Retrieval Graph", "year": 2025, "citationCount": 5, "url": "https://example.org/p1"}
        return {"data": [{
            "paperId": "P1",
            "title": "Agentic Retrieval Graph",
            "abstract": "A citation-aware agentic retrieval system.",
            "authors": [{"name": "Ada Researcher"}],
            "year": 2025,
            "publicationDate": "2025-06-01",
            "venue": "EvidenceConf",
            "externalIds": {"DOI": "10.1000/p1"},
            "openAccessPdf": {"url": "https://example.org/p1.pdf"},
            "fieldsOfStudy": ["Computer Science"],
            "citationCount": 5,
            "publicationTypes": ["JournalArticle"],
            "url": "https://example.org/p1",
        }]}

    connector = SemanticScholarConnector(api_key="test", fetch=fetch)
    request = _request().model_copy(update={"providers": ["semantic_scholar"]})
    paper = connector.discover(request)[0]
    graph = connector.citation_graph("P1")

    assert paper.external_ids["semantic_scholar"] == "P1"
    assert paper.doi == "10.1000/p1"
    assert len(graph.nodes) == 3
    assert {edge.relation for edge in graph.edges} == {"references", "cited_by"}


def test_crossref_normalizes_doi_metadata() -> None:
    payload = {"message": {"items": [{
        "DOI": "10.1000/crossref",
        "title": ["Crossref Evidence Paper"],
        "abstract": "<jats:p>Evidence abstract.</jats:p>",
        "author": [{"given": "Ada", "family": "Researcher"}],
        "published": {"date-parts": [[2025, 7, 2]]},
        "container-title": ["Evidence Journal"],
        "URL": "https://doi.org/10.1000/crossref",
        "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
        "is-referenced-by-count": 11,
        "type": "journal-article",
    }]}}
    connector = CrossrefConnector(contact_email="test@example.com", fetch=lambda _: payload)
    paper = connector.discover(_request().model_copy(update={"providers": ["crossref"]}))[0]

    assert paper.doi == "10.1000/crossref"
    assert paper.abstract == "Evidence abstract."
    assert paper.open_access is True


def test_discovery_enforces_open_access_across_connectors() -> None:
    payload = {"message": {"items": [{
        "DOI": "10.1000/closed",
        "title": ["Closed Evidence Paper"],
        "abstract": "Evidence abstract.",
        "author": [{"given": "Ada", "family": "Researcher"}],
        "published": {"date-parts": [[2025, 7, 2]]},
        "URL": "https://doi.org/10.1000/closed",
        "is-referenced-by-count": 1,
        "type": "journal-article",
    }]}}
    service = PaperDiscoveryService(
        KnowledgeService(),
        crossref=CrossrefConnector(contact_email="test@example.com", fetch=lambda _: payload),
    )
    request = _request().model_copy(update={"providers": ["crossref"], "open_access_only": True})

    assert service.discover(request).papers == []
