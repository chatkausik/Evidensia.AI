from __future__ import annotations

import hashlib
import math
import re
from collections import Counter


TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "how",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "what",
    "when", "where", "which", "who", "with", "does", "do", "did", "than", "their",
}
CANONICAL = {
    "rag": "retrieval_augmented_generation",
    "retrieval-augmented": "retrieval_augmented_generation",
    "retrieval": "retrieve",
    "retriever": "retrieve",
    "retrieving": "retrieve",
    "benchmarks": "benchmark",
    "benchmarking": "benchmark",
    "improved": "improve",
    "improvement": "improve",
    "outperform": "improve",
    "outperforms": "improve",
    "costs": "cost",
    "latency": "latency",
    "delays": "latency",
    "contradictory": "contradict",
    "contradiction": "contradict",
}


def tokenize(text: str, *, remove_stops: bool = True) -> list[str]:
    terms = [CANONICAL.get(token, token) for token in TOKEN_PATTERN.findall(text.lower())]
    return [term for term in terms if not remove_stops or term not in STOP_WORDS]


def term_frequencies(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def hashed_vector(text: str, dimensions: int = 384) -> dict[int, float]:
    """Deterministic local embedding used until a managed embedding provider is configured."""
    tokens = tokenize(text)
    features = tokens + [f"{left}::{right}" for left, right in zip(tokens, tokens[1:])]
    values: Counter[int] = Counter()
    for feature in features:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        values[int.from_bytes(digest, "big") % dimensions] += 1
    norm = math.sqrt(sum(value * value for value in values.values())) or 1.0
    return {index: value / norm for index, value in values.items()}


def cosine(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())

