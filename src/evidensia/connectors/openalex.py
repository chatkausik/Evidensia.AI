from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import urlencode

from evidensia.connectors.http import PaperSourceError, get_json
from evidensia.models import DiscoveredPaper, PaperDiscoveryRequest


def _abstract_from_index(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positions = [(position, word) for word, offsets in index.items() for position in offsets]
    return " ".join(word for _, word in sorted(positions))


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class OpenAlexConnector:
    name = "openalex"
    endpoint = "https://api.openalex.org/works"

    def __init__(
        self,
        api_key: str | None = None,
        fetch: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENALEX_API_KEY", "").strip()
        self._fetch = fetch or get_json

    def discover(self, request: PaperDiscoveryRequest) -> list[DiscoveredPaper]:
        filters = [
            f"from_publication_date:{request.date_from.isoformat()}",
            f"to_publication_date:{request.date_to.isoformat()}",
            "has_abstract:true",
        ]
        if request.open_access_only:
            filters.append("is_oa:true")
        params = {
            "search": request.query,
            "filter": ",".join(filters),
            "sort": "publication_date:desc",
            "per_page": request.limit,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        contact = os.getenv("EVIDENSIA_CONTACT_EMAIL", "").strip()
        if contact:
            params["mailto"] = contact
        url = f"{self.endpoint}?{urlencode(params)}"
        try:
            payload = self._fetch(url)
        except PaperSourceError:
            raise
        except Exception as exc:
            raise PaperSourceError(f"OpenAlex request failed: {exc}") from exc
        return self.parse(payload)

    @staticmethod
    def parse(payload: dict[str, Any]) -> list[DiscoveredPaper]:
        papers: list[DiscoveredPaper] = []
        for work in payload.get("results", []):
            if not isinstance(work, dict):
                continue
            title = work.get("display_name") or work.get("title")
            published = _date(work.get("publication_date"))
            raw_id = str(work.get("id") or "").rstrip("/")
            external_id = raw_id.rsplit("/", 1)[-1]
            abstract = _abstract_from_index(work.get("abstract_inverted_index"))
            if not title or not published or not external_id or not abstract:
                continue

            authors = []
            for authorship in work.get("authorships") or []:
                author = authorship.get("author") or {}
                if author.get("display_name"):
                    authors.append(author["display_name"])
            primary = work.get("primary_location") or {}
            best_oa = work.get("best_oa_location") or {}
            source = primary.get("source") or {}
            open_access = work.get("open_access") or {}
            doi = str(work.get("doi") or "").removeprefix("https://doi.org/") or None
            landing_url = primary.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else raw_id)
            topics = [
                topic["display_name"]
                for topic in work.get("topics") or []
                if isinstance(topic, dict) and topic.get("display_name")
            ]
            publication_type = work.get("type") or "unknown"
            papers.append(DiscoveredPaper(
                paper_id=f"openalex:{external_id}",
                providers=["openalex"],
                external_ids={"openalex": external_id},
                title=title,
                abstract=abstract,
                authors=authors,
                published_at=published,
                venue=source.get("display_name"),
                doi=doi,
                topics=topics,
                landing_url=landing_url,
                pdf_url=best_oa.get("pdf_url") or primary.get("pdf_url"),
                open_access=bool(open_access.get("is_oa")),
                license=best_oa.get("license") or primary.get("license"),
                publication_type=publication_type,
                is_preprint=publication_type == "preprint",
                citation_count=work.get("cited_by_count"),
            ))
        return papers
