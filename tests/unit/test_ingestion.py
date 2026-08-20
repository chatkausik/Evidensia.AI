from evidensia.ingestion import DocumentParser, HierarchicalChunker, extract_metadata
from evidensia.services.knowledge import KnowledgeService


def test_markdown_parser_and_chunker_preserve_sections() -> None:
    text = b"""# Evidence Study
Authors: Ada Test
2025

## Results
Hybrid retrieval improved Recall@10 by eleven points. It retained exact benchmark names.

## Limitations
The experiment used one corpus. However, the result was not significant for single-hop questions.
"""
    parser = DocumentParser()
    parsed = parser.parse("study.md", text, "text/markdown")
    metadata = extract_metadata("doc_test", parsed)
    chunks = HierarchicalChunker().chunk(parsed, metadata)

    assert parsed.title == "Evidence Study"
    assert {section.heading for section in parsed.sections} >= {"Results", "Limitations"}
    assert metadata.publication_year == 2025
    retrieval = [chunk for chunk in chunks if chunk.chunk_type == "retrieval"]
    assert retrieval
    assert all(chunk.parent_chunk_id for chunk in retrieval)
    assert all(chunk.section in {section.heading for section in parsed.sections} for chunk in retrieval)


def test_html_parser_extracts_headings_without_markup() -> None:
    parser = DocumentParser()
    parsed = parser.parse(
        "report.html",
        b"<h1>System Report</h1><h2>Results</h2><p>RRF improved ranking quality.</p>",
        "text/html",
    )
    assert parsed.title == "System Report"
    assert any(section.heading == "Results" for section in parsed.sections)
    assert "<p>" not in parsed.text


def test_local_knowledge_library_survives_restart(tmp_path) -> None:
    first = KnowledgeService(storage_dir=tmp_path)
    record = first.ingest(
        "persistent-paper.md",
        b"# Persistent AI Paper\nAuthors: Ada Test\n2026\n\n## Abstract\nA durable evidence record.",
        "text/markdown",
        "https://example.org/persistent-paper",
    )

    restored = KnowledgeService(storage_dir=tmp_path)

    assert record.document_id in restored.documents
    assert restored.documents[record.document_id].metadata is not None
    assert restored.documents[record.document_id].metadata.title == "Persistent AI Paper"
    assert restored.index.all()
