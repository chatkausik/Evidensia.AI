from __future__ import annotations

from evidensia.models import Evidence, EvidenceAssessment, SubQuestion


class SufficiencyEvaluator:
    def assess(self, sub_questions: list[SubQuestion], evidence: list[Evidence], depth: str) -> EvidenceAssessment:
        by_question = {item.sub_question_id for item in evidence}
        coverage = len(by_question) / max(1, len(sub_questions))
        sources = {item.citation.document_id for item in evidence}
        diversity_target = 1 if depth == "quick" else 3
        diversity = min(1.0, len(sources) / diversity_target)
        contradictions = [item for item in evidence if item.evidence_type == "contradicting"]
        contradiction_coverage = 1.0 if depth == "quick" else min(1.0, len(contradictions) / 2)
        threshold = {"quick": 0.5, "standard": 0.7, "deep": 0.8}[depth]
        sufficient = coverage >= threshold and diversity >= (0.35 if depth == "quick" else 0.65)
        if depth != "quick":
            sufficient = sufficient and contradiction_coverage >= 0.5

        missing_questions = [item for item in sub_questions if item.id not in by_question]
        missing = [item.purpose for item in missing_questions]
        if depth != "quick" and not contradictions:
            missing.append("No credible counter-evidence or qualifying result found")
        if len(sources) < diversity_target:
            missing.append(f"Evidence comes from only {len(sources)} distinct source(s)")
        suggestions = [item.question for item in missing_questions]
        if depth != "quick" and not contradictions:
            suggestions.append("negative results limitations no significant improvement counter evidence")
        return EvidenceAssessment(
            sufficient=sufficient,
            coverage_score=coverage,
            diversity_score=diversity,
            contradiction_coverage=contradiction_coverage,
            unsupported_claims=[],
            missing_information=missing,
            suggested_queries=suggestions[:5],
        )

