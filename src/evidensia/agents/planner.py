from __future__ import annotations

import re

from evidensia.models import ResearchPlan, SubQuestion
from evidensia.retrieval.query import classify_query


class ResearchPlanner:
    def create_plan(self, question: str, depth: str = "standard") -> ResearchPlan:
        intent = classify_query(question)
        subjects = self._subjects(question)
        questions: list[tuple[str, str, str, list[str]]] = []

        if intent.intent == "comparison" and len(subjects) >= 2:
            questions.extend(
                [
                    (f"How is {subjects[0]} defined and implemented?", "Establish the first comparison baseline", "critical", ["definition", "methodology"]),
                    (f"How is {subjects[1]} defined and implemented?", "Establish the second comparison baseline", "critical", ["definition", "methodology"]),
                    (f"Which direct benchmarks compare {subjects[0]} with {subjects[1]}?", "Find measurable comparative outcomes", "critical", ["benchmark", "results"]),
                ]
            )
        else:
            questions.extend(
                [
                    (f"What are the central definitions and assumptions behind: {question}", "Establish scope and terminology", "critical", ["definition"]),
                    (f"What empirical findings directly answer: {question}", "Locate measured outcomes", "critical", ["benchmark", "results"]),
                ]
            )

        questions.append((f"What limitations, costs, or failure conditions affect: {question}", "Identify trade-offs and boundary conditions", "high", ["limitations", "cost", "latency"]))
        if depth != "quick":
            questions.append((f"Which credible findings contradict or qualify the premise of: {question}", "Actively search for counter-evidence", "high", ["contradicting", "negative result"]))
        if depth == "deep":
            questions.append((f"How do methodology and dataset choices change the answer to: {question}", "Test whether findings generalize", "medium", ["methodology", "dataset", "ablation"]))

        sub_questions = [
            SubQuestion(
                id=f"sq_{index:02d}",
                question=text,
                purpose=purpose,
                priority=priority,  # type: ignore[arg-type]
                evidence_types=evidence_types,
            )
            for index, (text, purpose, priority, evidence_types) in enumerate(questions, start=1)
        ]
        hypotheses = [
            "The effect is strongest for complex, multi-step research questions.",
            "Performance gains involve latency, cost, or operational trade-offs.",
            "Reported outcomes depend on evaluation design and source quality.",
        ]
        return ResearchPlan(
            main_question=question,
            interpretation=f"A {intent.intent.replace('_', ' ')} investigation requiring traceable empirical and counter-evidence.",
            hypotheses=hypotheses,
            sub_questions=sub_questions,
            expected_evidence=["direct measurements", "method details", "limitations", "counter-evidence"],
            search_strategy="Hybrid dense and lexical retrieval, RRF fusion, transparent reranking, then corrective search for uncovered dimensions.",
        )

    @staticmethod
    def _subjects(question: str) -> list[str]:
        match = re.search(r"(?:compare|comparison of)\s+(.+?)\s+(?:and|with|versus|vs\.?)\s+(.+?)(?:\?|\s+for\s+|\s+on\s+|$)", question, re.IGNORECASE)
        if not match:
            match = re.search(r"(.+?)\s+(?:versus|vs\.?)\s+(.+?)(?:\?|\s+for\s+|\s+on\s+|$)", question, re.IGNORECASE)
        if not match:
            return []
        return [re.sub(r"^(does|do|is|are)\s+", "", part.strip(), flags=re.IGNORECASE) for part in match.groups()]

