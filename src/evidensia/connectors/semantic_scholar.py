from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import urlencode

from evidensia.connectors.http import PaperSourceError, get_json
from evidensia.models import CitationGraph, CitationGraphEdge, CitationGraphNode, DiscoveredPaper, PaperDiscoveryRequest


class SemanticScholarConnector:
    name = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key: str | None = None, fetch: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        self._fetch = fetch or self._live_fetch

    def _live_fetch(self, url: str) -> dict[str, Any]:
        return get_json(url, headers={"x-api-key": self.api_key} if self.api_key else None)

    def discover(self, request: PaperDiscoveryRequest) -> list[DiscoveredPaper]:
        fields = "paperId,title,abstract,authors,year,publicationDate,venue,externalIds,openAccessPdf,fieldsOfStudy,citationCount,publicationTypes,url"
        query = urlencode({
            "query": request.query,
            "fields": fields,
            "year": f"{request.date_from.year}-{request.date_to.year}",
            "limit": min(request.limit, 100),
        })
        payload = self._request(f"{self.endpoint}/paper/search/bulk?{query}")
        papers: list[DiscoveredPaper] = []
        for item in payload.get("data") or []:
            if not isinstance(item, dict) or not item.get("paperId") or not item.get("title"):
                continue
            published = self._published(item, request.date_from)
            if published < request.date_from or published > request.date_to:
                continue
            oa = item.get("openAccessPdf") or {}
            external = item.get("externalIds") or {}
            papers.append(DiscoveredPaper(
                paper_id=f"semantic_scholar:{item['paperId']}",
                providers=["semantic_scholar"],
                external_ids={
                    "semantic_scholar": str(item["paperId"]),
                    **{str(key).lower(): str(value) for key, value in external.items() if value},
                },
                title=item["title"],
                abstract=item.get("abstract") or "",
                authors=[author.get("name") for author in item.get("authors") or [] if author.get("name")],
                published_at=published,
                venue=item.get("venue") or None,
                doi=external.get("DOI") or external.get("doi"),
                topics=item.get("fieldsOfStudy") or [],
                landing_url=item.get("url") or f"https://www.semanticscholar.org/paper/{item['paperId']}",
                pdf_url=oa.get("url"),
                open_access=bool(oa.get("url")),
                publication_type=(item.get("publicationTypes") or ["unknown"])[0],
                is_preprint="preprint" in {str(value).lower() for value in item.get("publicationTypes") or []},
                citation_count=item.get("citationCount"),
            ))
        return papers

    def citation_graph(self, semantic_id: str, limit: int = 15) -> CitationGraph:
        fields = "paperId,title,year,citationCount,url"
        root_payload = self._request(f"{self.endpoint}/paper/{semantic_id}?{urlencode({'fields': fields})}")
        root = self._node(root_payload)
        nodes = {root.paper_id: root}
        edges: list[CitationGraphEdge] = []
        for relation, path in (("references", "references"), ("cited_by", "citations")):
            payload = self._request(
                f"{self.endpoint}/paper/{semantic_id}/{path}?{urlencode({'fields': fields, 'limit': limit})}"
            )
            for row in payload.get("data") or []:
                paper = row.get("citedPaper") if relation == "references" else row.get("citingPaper")
                if not isinstance(paper, dict) or not paper.get("paperId") or not paper.get("title"):
                    continue
                node = self._node(paper)
                nodes[node.paper_id] = node
                edges.append(CitationGraphEdge(
                    source=root.paper_id if relation == "references" else node.paper_id,
                    target=node.paper_id if relation == "references" else root.paper_id,
                    relation=relation,
                ))
        return CitationGraph(root_id=root.paper_id, nodes=list(nodes.values()), edges=edges)

    def _request(self, url: str) -> dict[str, Any]:
        try:
            return self._fetch(url)
        except Exception as exc:
            raise PaperSourceError(f"Semantic Scholar request failed: {exc}") from exc

    @staticmethod
    def _published(item: dict[str, Any], fallback: date) -> date:
        try:
            return date.fromisoformat(item.get("publicationDate"))
        except (TypeError, ValueError):
            return date(int(item.get("year") or fallback.year), 1, 1)

    @staticmethod
    def _node(item: dict[str, Any]) -> CitationGraphNode:
        return CitationGraphNode(
            paper_id=f"semantic_scholar:{item['paperId']}",
            title=item["title"],
            year=item.get("year"),
            citation_count=item.get("citationCount"),
            url=item.get("url"),
        )
