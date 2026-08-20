from __future__ import annotations

import hashlib
import re

from evidensia.models import Citation, Evidence, RankedEvidence, SubQuestion
from evidensia.retrieval.text import tokenize


_CONTRADICTION_MARKERS = {
    "however", "although", "no improvement", "not significant", "failed", "worse",
    "did not", "does not", "limitation", "contrary", "negligible", "decline",
}


class EvidenceExtractor:
    def extract(self, sub_question: SubQuestion, results: list[RankedEvidence], limit: int = 3) -> list[Evidence]:
        evidence: list[Evidence] = []
        seen: set[str] = set()
        for result in results:
            sentence = self._best_span(sub_question.question, result.chunk.text)
            normalized = re.sub(r"\W+", " ", sentence.lower()).strip()
            if not sentence or normalized in seen:
                continue
            seen.add(normalized)
            lowered = sentence.lower()
            kind = "contradicting" if any(marker in lowered for marker in _CONTRADICTION_MARKERS) else "supporting"
            digest = hashlib.sha256(f"{sub_question.id}|{result.chunk.chunk_id}|{sentence}".encode()).hexdigest()[:16]
            citation = Citation(
                citation_id=f"cit_{digest}",
                document_id=result.chunk.document_id,
                chunk_id=result.chunk.chunk_id,
                title=result.chunk.title,
                page=result.chunk.page_number,
                section=result.chunk.section,
                source_uri=result.chunk.source_uri,
                quoted_text=sentence,
            )
            evidence.append(
                Evidence(
                    evidence_id=f"ev_{digest}",
                    sub_question_id=sub_question.id,
                    claim=sentence,
                    supporting_text=sentence,
                    evidence_type=kind,
                    relevance=max(0.0, min(1.0, result.rerank_score or result.final_score)),
                    source_quality=self._source_quality(result),
                    confidence=max(0.05, min(0.98, 0.65 * result.rerank_score + 0.35 * self._source_quality(result))),
                    citation=citation,
                )
            )
            if len(evidence) >= limit:
                break
        return evidence

    @staticmethod
    def _best_span(query: str, text: str) -> str:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if len(part.strip()) >= 25]
        if not sentences:
            return text.strip()[:600]
        query_terms = set(tokenize(query))
        return max(
            sentences,
            key=lambda sentence: len(query_terms & set(tokenize(sentence))) / max(1, len(query_terms)),
        )[:900]

    @staticmethod
    def _source_quality(result: RankedEvidence) -> float:
        score = 0.55
        score += 0.1 if result.chunk.authors else 0
        score += 0.1 if result.chunk.publication_year else 0
        score += 0.08 if result.chunk.page_number else 0
        score += 0.08 if result.chunk.section.lower() not in {"document", "page 1"} else 0
        return min(0.95, score)

