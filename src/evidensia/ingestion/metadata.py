from __future__ import annotations

import re
from datetime import date

from evidensia.ingestion.parser import ParsedDocument
from evidensia.models import DocumentMetadata


_TOPICS = {
    "retrieval augmented generation": "RAG",
    "agentic rag": "Agentic RAG",
    "graph rag": "GraphRAG",
    "multi-hop": "Multi-hop QA",
    "question answering": "Question answering",
    "large language model": "Large language models",
    "vector search": "Vector search",
    "information retrieval": "Information retrieval",
    "evidence": "Evidence intelligence",
}
_METHODS = {
    "bm25": "BM25",
    "reciprocal rank fusion": "RRF",
    "cross-encoder": "Cross-encoder reranking",
    "dense retrieval": "Dense retrieval",
    "sparse retrieval": "Sparse retrieval",
    "langgraph": "LangGraph",
}
_DATASETS = ["HotpotQA", "MuSiQue", "2WikiMultihopQA", "Natural Questions", "FEVER"]


def extract_metadata(document_id: str, parsed: ParsedDocument) -> DocumentMetadata:
    text = parsed.text
    lowered = text.lower()
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text[:4000])
    date_match = re.search(r"^(?:published|publication date)\s*:\s*(\d{4}-\d{2}-\d{2})", text, flags=re.IGNORECASE | re.MULTILINE)
    doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, flags=re.IGNORECASE)
    venue_match = re.search(r"^venue\s*:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    author_match = re.search(r"^(?:by|authors?\s*:)\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    authors: list[str] = []
    if author_match:
        authors = [name.strip() for name in re.split(r",|\band\b|;", author_match.group(1)) if name.strip()]

    topics = [label for needle, label in _TOPICS.items() if needle in lowered]
    methods = [label for needle, label in _METHODS.items() if needle in lowered]
    datasets = [dataset for dataset in _DATASETS if dataset.lower() in lowered]
    confidence = 0.45
    confidence += 0.15 if parsed.title else 0
    confidence += 0.1 if year_match else 0
    confidence += 0.1 if authors else 0
    confidence += 0.1 if topics else 0
    confidence += 0.1 if parsed.sections else 0

    return DocumentMetadata(
        document_id=document_id,
        title=parsed.title,
        authors=authors,
        publication_year=int(year_match.group(1)) if year_match else None,
        publication_date=date.fromisoformat(date_match.group(1)) if date_match else None,
        venue=venue_match.group(1).strip() if venue_match else None,
        doi=doi_match.group(0) if doi_match else None,
        topics=topics,
        methods=methods,
        datasets=datasets,
        document_type=parsed.document_type,
        extraction_confidence=min(confidence, 0.98),
    )
