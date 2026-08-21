from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Protocol
from urllib.parse import urlparse

from evidensia.models import MemorySnippet, ResearchState


logger = logging.getLogger(__name__)


class Mem0Client(Protocol):
    def search(self, query: str, **kwargs: Any) -> Any: ...

    def add(self, messages: list[dict[str, str]], **kwargs: Any) -> Any: ...


class LongTermMemory(Protocol):
    name: str
    enabled: bool

    def recall(self, query: str, user_id: str) -> list[MemorySnippet]: ...

    def remember_research(self, state: ResearchState, user_id: str) -> bool: ...


class DisabledLongTermMemory:
    name = "disabled"
    enabled = False

    def recall(self, query: str, user_id: str) -> list[MemorySnippet]:
        return []

    def remember_research(self, state: ResearchState, user_id: str) -> bool:
        return False


class Mem0LongTermMemory:
    """Bounded, fail-open adapter for Mem0's hosted long-term memory API."""

    name = "mem0:platform"
    enabled = True

    def __init__(
        self,
        client: Mem0Client | None = None,
        *,
        client_factory: Callable[[], Mem0Client] | None = None,
        top_k: int = 5,
        threshold: float = 0.2,
        timeout: float = 5.0,
    ) -> None:
        if client is None and client_factory is None:
            raise ValueError("A Mem0 client or client factory is required")
        if not 1 <= top_k <= 20:
            raise ValueError("Mem0 top_k must be between 1 and 20")
        if not 0 <= threshold <= 1:
            raise ValueError("Mem0 threshold must be between 0 and 1")
        if not 0 < timeout <= 60:
            raise ValueError("Mem0 timeout must be between 0 and 60 seconds")
        self._client = client
        self._client_factory = client_factory
        self._client_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="evidensia-mem0")
        self.top_k = top_k
        self.threshold = threshold
        self.timeout = timeout

    def recall(self, query: str, user_id: str) -> list[MemorySnippet]:
        result = self._call(
            "search",
            lambda: self._get_client().search(
                query=query,
                filters={"user_id": user_id},
                top_k=self.top_k,
                threshold=self.threshold,
                rerank=False,
            ),
        )
        if result is None:
            return []
        raw_items = result.get("results", []) if isinstance(result, dict) else result
        if not isinstance(raw_items, list):
            logger.warning("Mem0 search returned an unexpected response shape")
            return []
        snippets: list[MemorySnippet] = []
        for item in raw_items[: self.top_k]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("memory") or item.get("text") or "").strip()
            if not text:
                continue
            raw_score = item.get("score")
            try:
                score = max(0.0, min(1.0, float(raw_score))) if raw_score is not None else None
            except (TypeError, ValueError):
                score = None
            snippets.append(
                MemorySnippet(
                    memory_id=str(item.get("id") or item.get("memory_id") or ""),
                    text=text[:2000],
                    score=score,
                )
            )
        return snippets

    def remember_research(self, state: ResearchState, user_id: str) -> bool:
        report = state.final_report
        if state.status != "completed" or report is None:
            return False
        findings = "\n".join(f"- {item}" for item in report.key_findings[:5])
        assistant_content = (
            f"Verified research summary: {report.executive_summary}\n"
            f"Conclusion: {report.conclusion}\n"
            f"Key findings:\n{findings}"
        )[:6000]
        result = self._call(
            "add",
            lambda: self._get_client().add(
                messages=[
                    {"role": "user", "content": state.question},
                    {"role": "assistant", "content": assistant_content},
                ],
                user_id=user_id,
                agent_id="evidensia-research",
                run_id=state.run_id,
                metadata={
                    "source": "evidensia",
                    "category": "verified_research",
                    "depth": state.depth,
                    "namespace": state.namespace,
                },
            ),
        )
        return result is not None

    def _get_client(self) -> Mem0Client:
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is None:
                assert self._client_factory is not None
                self._client = self._client_factory()
        return self._client

    def _call(self, operation: str, action: Callable[[], Any]) -> Any | None:
        future = self._executor.submit(action)
        try:
            return future.result(timeout=self.timeout)
        except FutureTimeoutError:
            future.cancel()
            logger.warning("Mem0 %s timed out after %.1f seconds; continuing without memory", operation, self.timeout)
        except Exception as exc:
            logger.warning("Mem0 %s failed; continuing without memory: %s", operation, type(exc).__name__)
        return None


def memory_from_environment() -> LongTermMemory:
    api_key = os.getenv("MEM0_API_KEY", "").strip()
    if not api_key:
        return DisabledLongTermMemory()

    host = os.getenv("EVIDENSIA_MEM0_HOST", "").strip()
    if host:
        parsed = urlparse(host)
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (parsed.scheme != "https" and not local_http) or not parsed.hostname:
            raise ValueError("EVIDENSIA_MEM0_HOST must use HTTPS, except for a localhost endpoint")

    def create_client() -> Mem0Client:
        from mem0 import MemoryClient

        kwargs: dict[str, str] = {"api_key": api_key}
        if host:
            kwargs["host"] = host
        return MemoryClient(**kwargs)

    return Mem0LongTermMemory(
        client_factory=create_client,
        top_k=int(os.getenv("EVIDENSIA_MEM0_TOP_K", "5")),
        threshold=float(os.getenv("EVIDENSIA_MEM0_THRESHOLD", "0.2")),
        timeout=float(os.getenv("EVIDENSIA_MEM0_TIMEOUT", "5")),
    )


__all__ = [
    "DisabledLongTermMemory",
    "LongTermMemory",
    "Mem0LongTermMemory",
    "memory_from_environment",
]
