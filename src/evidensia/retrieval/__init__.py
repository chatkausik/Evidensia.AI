"""Retrieval package.

Re-exports are resolved lazily (PEP 562). `providers` needs the leaf helpers in
`retrieval.text`, but importing any submodule first executes this `__init__`;
when that eagerly imported `hybrid` and `index` — which import `providers` — the
cycle closed and `import evidensia.providers` failed outright. It only appeared
to work because every existing entry point happened to import `evidensia.retrieval`
first.

Deferring the re-exports keeps `from evidensia.retrieval import HybridSearcher`
working exactly as before while making the dependency graph acyclic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evidensia.retrieval.hybrid import HybridSearcher
    from evidensia.retrieval.index import LocalKnowledgeIndex

__all__ = ["HybridSearcher", "LocalKnowledgeIndex"]

_EXPORTS = {
    "HybridSearcher": ("evidensia.retrieval.hybrid", "HybridSearcher"),
    "LocalKnowledgeIndex": ("evidensia.retrieval.index", "LocalKnowledgeIndex"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(target[0]), target[1])


def __dir__() -> list[str]:
    return sorted(__all__)
