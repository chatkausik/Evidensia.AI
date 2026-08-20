from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import urlencode

from evidensia.connectors.http import PaperSourceError, get_json
from evidensia.models import DiscoveredPaper, PaperDiscoveryRequest


class CrossrefConnector:
    name = "crossref"
    endpoint = "https://api.crossref.org/works"

    def __init__(self, contact_email: str | None = None, fetch: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.contact_email = contact_email if contact_email is not None else os.getenv("EVIDENSIA_CONTACT_EMAIL", "").strip()
        self._fetch = fetch or get_json

    def discover(self, request: PaperDiscoveryRequest) -> list[DiscoveredPaper]:
        params = {
            "query": request.query,
            "filter": f"from-pub-date:{request.date_from.isoformat()},until-pub-date:{request.date_to.isoformat()}",
            "rows": min(request.limit, 100),
            "select": "DOI,title,abstract,author,published,container-title,URL,license,reference-count,is-referenced-by-count,type,relation,update-to",
        }
        if self.contact_email:
            params["mailto"] = self.contact_email
        try:
            payload = self._fetch(f"{self.endpoint}?{urlencode(params)}")
        except Exception as exc:
            raise PaperSourceError(f"Crossref request failed: {exc}") from exc
        output: list[DiscoveredPaper] = []
        for item in (payload.get("message") or {}).get("items") or []:
            doi = item.get("DOI")
            titles = item.get("title") or []
            published = self._date(item.get("published"))
            if not doi or not titles or not published:
                continue
            abstract = str(item.get("abstract") or "").replace("<jats:p>", "").replace("</jats:p>", "")
            licenses = item.get("license") or []
            output.append(DiscoveredPaper(
                paper_id=f"crossref:{doi.lower()}",
                providers=["crossref"],
                external_ids={"doi": doi},
                title=titles[0],
                abstract=abstract,
                authors=[" ".join(filter(None, [author.get("given"), author.get("family")])) for author in item.get("author") or []],
                published_at=published,
                venue=(item.get("container-title") or [None])[0],
                doi=doi,
                landing_url=item.get("URL") or f"https://doi.org/{doi}",
                open_access=bool(licenses),
                license=licenses[0].get("URL") if licenses else None,
                publication_type=item.get("type") or "unknown",
                citation_count=item.get("is-referenced-by-count"),
            ))
        return output

    @staticmethod
    def _date(payload: dict[str, Any] | None) -> date | None:
        parts = (payload or {}).get("date-parts") or []
        if not parts or not parts[0]:
            return None
        values = [int(value) for value in parts[0]]
        return date(values[0], values[1] if len(values) > 1 else 1, values[2] if len(values) > 2 else 1)
