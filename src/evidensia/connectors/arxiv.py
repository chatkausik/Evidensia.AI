from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from urllib.parse import urlencode
from xml.etree import ElementTree

from evidensia.connectors.http import PaperSourceError, get_bytes
from evidensia.models import DiscoveredPaper, PaperDiscoveryRequest


_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV = "http://arxiv.org/schemas/atom"
_DEFAULT_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.RO", "stat.ML"]
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


def _text(element: ElementTree.Element, path: str) -> str | None:
    node = element.find(path)
    if node is None or not node.text:
        return None
    return re.sub(r"\s+", " ", node.text).strip()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


class ArxivConnector:
    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, fetch: Callable[[str], bytes] | None = None) -> None:
        self._fetch = fetch or get_bytes
        self._is_live = fetch is None
        self._cache: dict[str, tuple[date, bytes]] = {}

    def discover(self, request: PaperDiscoveryRequest) -> list[DiscoveredPaper]:
        categories = request.categories or _DEFAULT_CATEGORIES
        query = self.build_query(request.query, categories, request.date_from, request.date_to)
        url = f"{self.endpoint}?{urlencode({
            'search_query': query,
            'start': 0,
            'max_results': request.limit,
            'sortBy': 'submittedDate',
            'sortOrder': 'descending',
        })}"
        try:
            payload = self._fetch_payload(url)
        except PaperSourceError:
            raise
        except Exception as exc:
            raise PaperSourceError(f"arXiv request failed: {exc}") from exc
        return self.parse(payload)

    def _fetch_payload(self, url: str) -> bytes:
        today = datetime.now(timezone.utc).date()
        cached = self._cache.get(url)
        if cached and cached[0] == today:
            return cached[1]
        if not self._is_live:
            return self._fetch(url)

        global _LAST_REQUEST_AT
        with _REQUEST_LOCK:
            wait_seconds = max(0.0, 3.0 - (time.monotonic() - _LAST_REQUEST_AT))
            if wait_seconds:
                time.sleep(wait_seconds)
            _LAST_REQUEST_AT = time.monotonic()
            payload = self._fetch(url)
        self._cache[url] = (today, payload)
        return payload

    @staticmethod
    def build_query(query: str, categories: list[str], date_from: date, date_to: date) -> str:
        clean_query = re.sub(r'["\r\n]+', " ", query).strip()
        category_query = " OR ".join(f"cat:{category}" for category in categories)
        start = date_from.strftime("%Y%m%d0000")
        end = date_to.strftime("%Y%m%d2359")
        return f'all:"{clean_query}" AND ({category_query}) AND submittedDate:[{start} TO {end}]'

    @staticmethod
    def parse(payload: bytes) -> list[DiscoveredPaper]:
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise PaperSourceError("arXiv returned an invalid Atom feed") from exc

        papers: list[DiscoveredPaper] = []
        for entry in root.findall(f"{{{_ATOM}}}entry"):
            title = _text(entry, f"{{{_ATOM}}}title")
            abstract = _text(entry, f"{{{_ATOM}}}summary")
            raw_id = _text(entry, f"{{{_ATOM}}}id")
            published = _parse_date(_text(entry, f"{{{_ATOM}}}published"))
            if not title or not abstract or not raw_id or not published:
                continue

            versioned_id = raw_id.rstrip("/").rsplit("/", 1)[-1]
            arxiv_id = re.sub(r"v\d+$", "", versioned_id)
            version_match = re.search(r"(v\d+)$", versioned_id)
            authors = [
                name
                for author in entry.findall(f"{{{_ATOM}}}author")
                if (name := _text(author, f"{{{_ATOM}}}name"))
            ]
            categories = list(dict.fromkeys(
                category.attrib["term"]
                for category in entry.findall(f"{{{_ATOM}}}category")
                if category.attrib.get("term")
            ))
            links = entry.findall(f"{{{_ATOM}}}link")
            landing_url = next(
                (link.attrib.get("href") for link in links if link.attrib.get("rel") == "alternate"),
                f"https://arxiv.org/abs/{arxiv_id}",
            )
            pdf_url = next(
                (link.attrib.get("href") for link in links if link.attrib.get("title") == "pdf"),
                None,
            )
            license_url = next(
                (link.attrib.get("href") for link in links if link.attrib.get("rel") == "license"),
                None,
            )
            doi = _text(entry, f"{{{_ARXIV}}}doi")
            venue = _text(entry, f"{{{_ARXIV}}}journal_ref")
            papers.append(DiscoveredPaper(
                paper_id=f"arxiv:{arxiv_id}",
                providers=["arxiv"],
                external_ids={"arxiv": arxiv_id},
                title=title,
                abstract=abstract,
                authors=authors,
                published_at=published,
                updated_at=_parse_date(_text(entry, f"{{{_ATOM}}}updated")),
                venue=venue,
                doi=doi,
                categories=categories,
                landing_url=landing_url,
                pdf_url=pdf_url,
                open_access=True,
                license=license_url,
                publication_type="preprint" if not venue else "preprint_with_journal_reference",
                is_preprint=True,
                version=version_match.group(1) if version_match else None,
            ))
        return papers
