"""iFixit API v2.0 client — search teardowns and download guide images.

Public REST API base: https://www.ifixit.com/api/2.0
No API key required for read-only access.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "retrace-pcb/0.3.0 (PCB reverse engineering research)"
REQUEST_DELAY = 1.0

_API_BASE = "https://www.ifixit.com/api/2.0"


def search_ifixit(query: str) -> list[dict[str, Any]]:
    """Search iFixit for teardown guides matching *query*.

    Parameters
    ----------
    query:
        Product name or keyword (e.g. "Neptune Apex AFS").

    Returns
    -------
    List of dicts with at minimum: ``guideid``, ``title``, ``url``,
    ``image_url``, ``category``, ``subject``.  Empty list on error.
    """
    params = {
        "query": query,
        "limit": 20,
        "offset": 0,
    }
    url = f"{_API_BASE}/search/{urllib.parse.quote(query)}?{urllib.parse.urlencode({'limit': params['limit'], 'offset': params['offset']})}"
    headers = {"User-Agent": USER_AGENT}

    logger.debug("iFixit search: %s", url)
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("iFixit search request failed: %s", exc)
        return []
    except ValueError as exc:
        logger.error("iFixit search: invalid JSON response: %s", exc)
        return []

    results: list[dict[str, Any]] = []
    for hit in data.get("results", []):
        # Only interested in guide-type results
        datatype = hit.get("dataType", "")
        if datatype not in ("guide", "teardown"):
            continue

        thumb = hit.get("image", {}) or {}
        results.append(
            {
                "guideid": hit.get("guideid"),
                "title": hit.get("title", ""),
                "url": hit.get("url", ""),
                "image_url": thumb.get("text", ""),
                "category": hit.get("category", ""),
                "subject": hit.get("subject", ""),
                "type": datatype,
            }
        )

    logger.info("iFixit search for %r → %d guides", query, len(results))
    return results


def download_guide_images(guideid: int | str, dest_dir: str | Path) -> list[Path]:
    """Download all step images from an iFixit guide.

    Parameters
    ----------
    guideid:
        Numeric guide ID (e.g. ``125000``).
    dest_dir:
        Directory where downloaded images will be saved.

    Returns
    -------
    Paths to successfully downloaded image files.  Empty list on failure.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    guide_url = f"{_API_BASE}/guides/{guideid}"
    headers = {"User-Agent": USER_AGENT}

    logger.debug("Fetching iFixit guide: %s", guide_url)
    try:
        resp = requests.get(guide_url, headers=headers, timeout=15)
        resp.raise_for_status()
        guide = resp.json()
    except requests.RequestException as exc:
        logger.error("Failed to fetch iFixit guide %s: %s", guideid, exc)
        return []
    except ValueError as exc:
        logger.error("iFixit guide %s: invalid JSON: %s", guideid, exc)
        return []

    # Collect all image URLs from guide steps
    image_urls: list[str] = []
    for step in guide.get("steps", []):
        for media in step.get("media", {}).get("data", []):
            for size in ("original", "large", "medium"):
                url = media.get(size, "")
                if url and url not in image_urls:
                    image_urls.append(url)
                    break  # prefer highest resolution, skip lower sizes

    # Also grab the guide's primary image
    primary = (guide.get("image") or {}).get("original", "")
    if primary and primary not in image_urls:
        image_urls.insert(0, primary)

    if not image_urls:
        logger.warning("No images found in guide %s", guideid)
        return []

    downloaded: list[Path] = []
    for i, img_url in enumerate(image_urls):
        time.sleep(REQUEST_DELAY)
        try:
            img_resp = requests.get(img_url, headers=headers, timeout=30, stream=True)
            img_resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Failed to download %s: %s", img_url, exc)
            continue

        ext = _ext_from_url(img_url) or ".jpg"
        filename = dest / f"ifixit_{guideid}_{i:03d}{ext}"
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

def _ext_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"} else ""
