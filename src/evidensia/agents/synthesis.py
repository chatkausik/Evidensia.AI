from __future__ import annotations

import hashlib

from evidensia.models import CitationVerification, Evidence, ResearchClaim, ResearchReport
from evidensia.providers import EntailmentProvider, LexicalEntailmentProvider
from evidensia.retrieval.index import LocalKnowledgeIndex
from evidensia.retrieval.text import tokenize


class SynthesisEngine:
    def __init__(self, entailment: EntailmentProvider | None = None) -> None:
        self.entailment = entailment or LexicalEntailmentProvider()

    def build_claims(self, evidence: list[Evidence]) -> list[ResearchClaim]:
        claims: list[ResearchClaim] = []
        support = sorted(
            (item for item in evidence if item.evidence_type != "contradicting"),
            key=lambda item: (-item.confidence, item.evidence_id),
        )
        opposing = [item for item in evidence if item.evidence_type == "contradicting"]
        seen: set[tuple[str, ...]] = set()
        for item in support:
            signature = tuple(tokenize(item.claim)[:10])
            if not signature or signature in seen:
                continue
            seen.add(signature)
            related_opposition = [other.evidence_id for other in opposing if self._overlap(item.claim, other.claim) >= 0.12]
            status = "mixed" if related_opposition else ("supported" if item.confidence >= 0.55 else "weak")
            digest = hashlib.sha256(item.claim.encode()).hexdigest()[:14]
            claims.append(
                ResearchClaim(
                    claim_id=f"claim_{digest}",
                    statement=item.claim,
                    evidence_ids=[item.evidence_id],
                    opposing_evidence_ids=related_opposition,
                    confidence=max(0.05, item.confidence - (0.08 if related_opposition else 0)),
                    status=status,
                )
            )
            if len(claims) >= 6:
                break
        if not claims and opposing:
            item = opposing[0]
            claims.append(
                ResearchClaim(
                    claim_id=f"claim_{hashlib.sha256(item.claim.encode()).hexdigest()[:14]}",
                    statement=f"Available evidence qualifies the premise: {item.claim}",
                    evidence_ids=[],
                    opposing_evidence_ids=[item.evidence_id],
                    confidence=item.confidence,
                    status="mixed",
                )
            )
        return claims

    def verify(
        self,
        claims: list[ResearchClaim],
        evidence: list[Evidence],
        index: LocalKnowledgeIndex,
    ) -> list[CitationVerification]:
        evidence_by_id = {item.evidence_id: item for item in evidence}
        checks: list[CitationVerification] = []
        for claim in claims:
            for evidence_id in [*claim.evidence_ids, *claim.opposing_evidence_ids]:
                item = evidence_by_id.get(evidence_id)
                if not item:
                    continue
                chunk = index.get(item.citation.chunk_id)
                valid = chunk is not None and chunk.document_id == item.citation.document_id
                entails, entailment_score = self.entailment.check(claim.statement, chunk.text) if valid else (False, 0.0)
                if valid and item.supporting_text.lower() in chunk.text.lower():
                    entails = True
                    entailment_score = max(entailment_score, 0.95)
                checks.append(
                    CitationVerification(
                        claim_id=claim.claim_id,
                        citation_id=item.citation.citation_id,
                        valid_source=valid,
                        entails_claim=entails,
                        citation_quality=(item.source_quality * 0.4 + item.relevance * 0.35 + entailment_score * 0.25) if valid and entails else 0,
                        issue=None if valid and entails else ("Source chunk was not found" if not valid else "Source does not sufficiently entail the claim"),
                    )
                )
        return checks

    def report(
        self,
        question: str,
        claims: list[ResearchClaim],
        evidence: list[Evidence],
        verifications: list[CitationVerification],
        unresolved: list[str],
    ) -> ResearchReport:
        valid_citations = {check.citation_id for check in verifications if check.valid_source and check.entails_claim}
        evidence_by_id = {item.evidence_id: item for item in evidence}
        sources = []
        for item in evidence:
            if item.citation.citation_id in valid_citations and item.citation not in sources:
                sources.append(item.citation)
        valid_claims: list[ResearchClaim] = []
        for claim in claims:
            ids = [*claim.evidence_ids, *claim.opposing_evidence_ids]
            cited = [evidence_by_id[item_id].citation.citation_id for item_id in ids if item_id in evidence_by_id]
            if not cited or any(citation_id in valid_citations for citation_id in cited):
                valid_claims.append(claim)
        confidence = sum(claim.confidence for claim in valid_claims) / max(1, len(valid_claims))
        if unresolved:
            confidence *= max(0.55, 1 - 0.08 * len(unresolved))
        findings = [claim.statement for claim in valid_claims[:5]]
        mixed = sum(claim.status == "mixed" for claim in valid_claims)
        conclusion = (
            f"The available corpus supports {len(valid_claims)} evidence-grounded finding(s)"
            + (f", with {mixed} materially qualified by counter-evidence" if mixed else "")
            + "."
        )
        return ResearchReport(
            research_question=question,
            executive_summary=" ".join(findings[:2]) if findings else "The indexed corpus does not yet contain enough evidence for a defensible answer.",
            conclusion=conclusion,
            key_findings=findings,
            claims=valid_claims,
            limitations=["Results reflect only the currently indexed corpus.", "Local deterministic scoring is a development baseline, not a hosted cross-encoder."],
            unresolved_questions=unresolved,
            confidence_score=max(0, min(1, confidence)),
            sources=sources,
        )

    @staticmethod
    def _overlap(left: str, right: str) -> float:
        left_terms = set(tokenize(left))
        right_terms = set(tokenize(right))
        return len(left_terms & right_terms) / max(1, len(left_terms))
