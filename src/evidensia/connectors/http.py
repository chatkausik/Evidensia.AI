from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PaperSourceError(RuntimeError):
    """A recoverable upstream paper-source failure."""


def user_agent() -> str:
    contact = os.getenv("EVIDENSIA_CONTACT_EMAIL", "").strip()
    suffix = f"; mailto:{contact}" if contact else ""
    return f"Evidensia/0.1 (research paper discovery{suffix})"


def get_bytes(url: str, *, timeout: float = 20) -> bytes:
    request = Request(url, headers={"Accept": "application/json, application/atom+xml", "User-Agent": user_agent()})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise PaperSourceError(f"upstream returned HTTP {exc.code}") from exc
    except (TimeoutError, URLError) as exc:
        raise PaperSourceError(f"upstream could not be reached: {exc.reason if isinstance(exc, URLError) else exc}") from exc


def get_json(url: str, *, timeout: float = 20) -> dict[str, Any]:
    try:
        return json.loads(get_bytes(url, timeout=timeout))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PaperSourceError("upstream returned an invalid JSON response") from exc


def get_document(url: str, *, timeout: float = 45, max_bytes: int = 25 * 1024 * 1024) -> tuple[bytes, str]:
    request = Request(url, headers={"Accept": "application/pdf", "User-Agent": user_agent()})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise PaperSourceError("paper exceeds the 25 MB ingestion limit")
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise PaperSourceError("paper exceeds the 25 MB ingestion limit")
            content_type = response.headers.get_content_type()
    except PaperSourceError:
        raise
    except HTTPError as exc:
        raise PaperSourceError(f"paper download returned HTTP {exc.code}") from exc
    except (TimeoutError, URLError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        raise PaperSourceError(f"paper download failed: {reason}") from exc
    if content_type != "application/pdf" and not content.startswith(b"%PDF"):
        raise PaperSourceError("paper source did not return a PDF")
    return content, "application/pdf"
