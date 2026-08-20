from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from evidensia.models import ChunkRecord, QueryIntent
from evidensia.retrieval.text import hashed_vector, tokenize

if TYPE_CHECKING:
    from evidensia.agents.openai_reasoning import ResearchReasoningProvider


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, text: str) -> dict[int, float]: ...


class RerankerProvider(Protocol):
    name: str

    def score(self, query: str, chunk: ChunkRecord, intent: QueryIntent) -> float: ...


class EntailmentProvider(Protocol):
    name: str

    def check(self, claim: str, passage: str) -> tuple[bool, float]: ...


class HashedEmbeddingProvider:
    name = "hashed-384"

    def embed(self, text: str) -> dict[int, float]:
        return hashed_vector(text)


class LexicalRerankerProvider:
    name = "lexical-transparent-v1"

    def score(self, query: str, chunk: ChunkRecord, intent: QueryIntent) -> float:
        query_terms = tokenize(query)
        document_terms = tokenize(f"{chunk.title} {chunk.section} {chunk.text}")
        query_set = set(query_terms)
        document_set = set(document_terms)
        coverage = len(query_set & document_set) / max(1, len(query_set))
        query_bigrams = set(zip(query_terms, query_terms[1:]))
        document_bigrams = set(zip(document_terms, document_terms[1:]))
        phrase = len(query_bigrams & document_bigrams) / max(1, len(query_bigrams))
        section = 1.0 if chunk.section.lower() in {value.lower() for value in intent.preferred_sections} else 0.0
        title = len(query_set & set(tokenize(chunk.title))) / max(1, len(query_set))
        return min(1.0, 0.62 * coverage + 0.18 * phrase + 0.12 * section + 0.08 * title)


class LexicalEntailmentProvider:
    name = "lexical-overlap-v1"

    def check(self, claim: str, passage: str) -> tuple[bool, float]:
        left = set(tokenize(claim))
        right = set(tokenize(passage))
        score = len(left & right) / max(1, len(left))
        return score >= 0.18, score


class RemoteJsonProvider:
    def __init__(self, url: str, *, api_key: str = "", model: str = "", timeout: float = 20.0) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Provider URL must be an absolute HTTP(S) URL")
        self.url = url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "User-Agent": "Evidensia-AI/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - explicit configured provider URL
            result = json.loads(response.read())
        if not isinstance(result, dict):
            raise ValueError("Provider returned a non-object response")
        return result


class RemoteEmbeddingProvider(RemoteJsonProvider):
    name = "remote-embedding"

    def embed(self, text: str) -> dict[int, float]:
        result = self._post({"model": self.model, "input": text})
        raw = result.get("embedding")
        if raw is None and isinstance(result.get("data"), list) and result["data"]:
            raw = result["data"][0].get("embedding")
        if not isinstance(raw, list):
            raise ValueError("Embedding provider response is missing an embedding array")
        return {index: float(value) for index, value in enumerate(raw) if float(value)}


class RemoteRerankerProvider(RemoteJsonProvider):
    name = "remote-reranker"

    def score(self, query: str, chunk: ChunkRecord, intent: QueryIntent) -> float:
        result = self._post({
            "model": self.model,
            "query": query,
            "document": f"{chunk.title}\n{chunk.section}\n{chunk.text}",
            "intent": intent.intent,
        })
        return max(0.0, min(1.0, float(result.get("score", 0))))


class RemoteEntailmentProvider(RemoteJsonProvider):
    name = "remote-entailment"

    def check(self, claim: str, passage: str) -> tuple[bool, float]:
        result = self._post({"model": self.model, "claim": claim, "passage": passage})
        score = max(0.0, min(1.0, float(result.get("score", 0))))
        return bool(result.get("entails", score >= 0.5)), score


@dataclass(frozen=True)
class ProviderBundle:
    embedding: EmbeddingProvider
    reranker: RerankerProvider
    entailment: EntailmentProvider
    research: ResearchReasoningProvider | None = None

    @property
    def manifest(self) -> dict[str, str]:
        return {
            "embedding": self.embedding.name,
            "reranker": self.reranker.name,
            "entailment": self.entailment.name,
            "research": self.research.name if self.research else "deterministic-fallback",
        }


def providers_from_environment() -> ProviderBundle:
    embedding: EmbeddingProvider = HashedEmbeddingProvider()
    reranker: RerankerProvider = LexicalRerankerProvider()
    entailment: EntailmentProvider = LexicalEntailmentProvider()
    research: ResearchReasoningProvider | None = None
    if url := os.getenv("EVIDENSIA_EMBEDDING_URL", "").strip():
        embedding = RemoteEmbeddingProvider(
            url,
            api_key=os.getenv("EVIDENSIA_EMBEDDING_API_KEY", "").strip(),
            model=os.getenv("EVIDENSIA_EMBEDDING_MODEL", "").strip(),
        )
    if url := os.getenv("EVIDENSIA_RERANK_URL", "").strip():
        reranker = RemoteRerankerProvider(
            url,
            api_key=os.getenv("EVIDENSIA_RERANK_API_KEY", "").strip(),
            model=os.getenv("EVIDENSIA_RERANK_MODEL", "").strip(),
        )
    if url := os.getenv("EVIDENSIA_ENTAILMENT_URL", "").strip():
        entailment = RemoteEntailmentProvider(
            url,
            api_key=os.getenv("EVIDENSIA_ENTAILMENT_API_KEY", "").strip(),
            model=os.getenv("EVIDENSIA_ENTAILMENT_MODEL", "").strip(),
        )
    if api_key := os.getenv("OPENAI_API_KEY", "").strip():
        from evidensia.agents.openai_reasoning import OpenAIResearchProvider

        reasoning_effort = os.getenv("EVIDENSIA_OPENAI_REASONING_EFFORT", "low").strip().lower()
        if reasoning_effort not in {"none", "low", "medium", "high", "xhigh"}:
            raise ValueError("EVIDENSIA_OPENAI_REASONING_EFFORT must be none, low, medium, high, or xhigh")
        research = OpenAIResearchProvider(
            api_key,
            model=os.getenv("EVIDENSIA_OPENAI_MODEL", "gpt-5.4-mini").strip(),
            base_url=os.getenv("EVIDENSIA_OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
            reasoning_effort=reasoning_effort,  # type: ignore[arg-type]
            timeout=float(os.getenv("EVIDENSIA_OPENAI_TIMEOUT", "45")),
            max_output_tokens=int(os.getenv("EVIDENSIA_OPENAI_MAX_OUTPUT_TOKENS", "3000")),
        )
    return ProviderBundle(embedding=embedding, reranker=reranker, entailment=entailment, research=research)
