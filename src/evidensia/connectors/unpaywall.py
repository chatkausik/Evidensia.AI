from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode

from evidensia.connectors.http import PaperSourceError, get_json


class UnpaywallClient:
    endpoint = "https://api.unpaywall.org/v2"

    def __init__(self, contact_email: str | None = None, fetch: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.contact_email = contact_email if contact_email is not None else os.getenv("EVIDENSIA_CONTACT_EMAIL", "").strip()
        self._fetch = fetch or get_json

    def find_pdf(self, doi: str) -> str | None:
        if not self.contact_email:
            return None
        url = f"{self.endpoint}/{quote(doi, safe='')}?{urlencode({'email': self.contact_email})}"
        try:
            payload = self._fetch(url)
        except Exception as exc:
            raise PaperSourceError(f"Unpaywall request failed: {exc}") from exc
        location = payload.get("best_oa_location") or {}
        return location.get("url_for_pdf")
