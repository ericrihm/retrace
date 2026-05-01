"""FCC filing scraper — searches fcc.report for FCC IDs and downloads internal photos.

Uses only stdlib html.parser; no BeautifulSoup dependency required.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "retrace-pcb/0.3.0 (PCB reverse engineering research)"
REQUEST_DELAY = 1.0

_BASE = "https://fcc.report"
_SEARCH_URL = f"{_BASE}/search"


# ---------------------------------------------------------------------------
# HTML parsers
# ---------------------------------------------------------------------------

class _SearchResultParser(HTMLParser):
    """Extracts FCC ID search results from fcc.report search pages.

    Each result lives inside an <a href="/FCC-ID/<id>"> link that also
    contains product name / applicant text.
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result_link = False
        self._current: dict[str, str] = {}
        self._text_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attr_map = dict(attrs)
            href = attr_map.get("href", "") or ""
            if href.startswith("/FCC-ID/"):
                fcc_id = href.split("/FCC-ID/", 1)[1].strip("/")
                self._current = {"fcc_id": fcc_id, "url": f"{_BASE}{href}"}
                self._in_result_link = True
                self._text_buf = []

    def handle_data(self, data: str) -> None:
        if self._in_result_link:
            self._text_buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_result_link:
            text = " ".join(self._text_buf).strip()
            self._current["description"] = text
            self.results.append(self._current)
            self._current = {}
            self._in_result_link = False
            self._text_buf = []


class _PhotoLinkParser(HTMLParser):
    """Extracts internal photo download links from an FCC filing page.

    Looks for <a> tags whose text or href indicates internal/board photos
    (e.g. "Internal Photos", "Internal Photo", filenames containing
    "internal" or "board").
    """

    def __init__(self) -> None:
        super().__init__()
        self.photo_links: list[str] = []
        self._current_href: str = ""
        self._text_buf: list[str] = []
        self._in_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attr_map = dict(attrs)
            href = attr_map.get("href", "") or ""
            self._current_href = href
            self._in_link = True
            self._text_buf = []

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._text_buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            text = " ".join(self._text_buf).strip().lower()
            href = self._current_href.lower()
            if any(kw in text or kw in href for kw in ("internal", "board photo", "pcb")):
                full = (
                    self._current_href
                    if self._current_href.startswith("http")
                    else f"{_BASE}{self._current_href}"
                )
                if full not in self.photo_links:
                    self.photo_links.append(full)
            self._in_link = False
            self._text_buf = []
            self._current_href = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_fcc(query: str) -> list[dict[str, Any]]:
    """Search for FCC IDs matching *query*.

    Tries fcc.report first, then falls back to the local device registry
    when the online search is unavailable.

    Parameters
    ----------
    query:
        Product name or keyword (e.g. "xbox one").

    Returns
    -------
    list of dicts with keys: ``fcc_id``, ``url``, ``description``.
    An empty list is returned when no results are found.
    """
    params = {"q": query}
    url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": USER_AGENT}

    logger.debug("FCC search: %s", url)
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        parser = _SearchResultParser()
        parser.feed(resp.text)
        if parser.results:
            logger.info("FCC search for %r → %d results (online)", query, len(parser.results))
            return parser.results
    except requests.RequestException as exc:
        logger.debug("FCC online search unavailable: %s", exc)

    from retrace.sources.device_registry import search_registry

    registry_hits = search_registry(query)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for family, revisions in registry_hits:
        for rev in revisions:
            if rev.fcc_id in seen:
                continue
            seen.add(rev.fcc_id)
            results.append({
                "fcc_id": rev.fcc_id,
                "url": f"{_BASE}/FCC-ID/{rev.fcc_id}",
                "description": f"{rev.name} ({rev.year or '?'}) — {family.manufacturer} — Model {rev.model_number}",
                "model_number": rev.model_number,
                "year": rev.year,
            })
    logger.info("FCC search for %r → %d results (local registry)", query, len(results))
    return results


def download_fcc_photos(fcc_id: str, dest_dir: str | Path) -> list[Path]:
    """Download internal board photos for *fcc_id* from fcc.report.

    Parameters
    ----------
    fcc_id:
        FCC ID string (e.g. ``"2ABCD-MYDEVICE"``).
    dest_dir:
        Directory where downloaded images will be saved.

    Returns
    -------
    Paths to successfully downloaded files.  Empty list on failure.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    filing_url = f"{_BASE}/FCC-ID/{urllib.parse.quote(fcc_id, safe='')}"
    headers = {"User-Agent": USER_AGENT}

    logger.debug("Fetching FCC filing page: %s", filing_url)
    try:
        resp = requests.get(filing_url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to fetch FCC filing page for %s: %s", fcc_id, exc)
        return []

    parser = _PhotoLinkParser()
    parser.feed(resp.text)

    if not parser.photo_links:
        logger.warning("No internal photo links found for FCC ID: %s", fcc_id)
        return []

    downloaded: list[Path] = []
    for i, link in enumerate(parser.photo_links):
        time.sleep(REQUEST_DELAY)
        try:
            img_resp = requests.get(link, headers=headers, timeout=30, stream=True)
            img_resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Failed to download %s: %s", link, exc)
            continue

        # Infer extension from Content-Type or URL
        content_type = img_resp.headers.get("Content-Type", "")
        ext = _ext_from_content_type(content_type) or _ext_from_url(link) or ".jpg"

        filename = dest / f"{fcc_id}_internal_{i:03d}{ext}"
        try:
            with filename.open("wb") as fh:
                for chunk in img_resp.iter_content(chunk_size=65536):
                    fh.write(chunk)
            logger.info("Downloaded: %s", filename)
            downloaded.append(filename)
        except OSError as exc:
            logger.error("Could not write %s: %s", filename, exc)

    return downloaded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ext_from_content_type(ct: str) -> str:
    _map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "application/pdf": ".pdf",
    }
    for mime, ext in _map.items():
        if mime in ct:
            return ext
    return ""


def _ext_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".pdf"} else ""
