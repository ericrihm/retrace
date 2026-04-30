"""Unified image acquisition — searches all sources and downloads board photos.

Orchestrates FCC and iFixit adapters into a single call.  Results are written
to per-source subdirectories under a shared destination root.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from retrace.sources.fcc import download_fcc_photos, search_fcc
from retrace.sources.ifixit import download_guide_images, search_ifixit

logger = logging.getLogger(__name__)

_DEFAULT_DEST = Path.home() / ".local" / "share" / "retrace" / "images"


def download_all(
    query: str,
    fcc_results: list[dict[str, Any]] | None = None,
    ifixit_results: list[dict[str, Any]] | None = None,
    dest_root: str | Path = _DEFAULT_DEST,
    max_fcc: int = 3,
    max_ifixit: int = 5,
) -> int:
    """Search all sources for *query* and download board images.

    Parameters
    ----------
    query:
        Product name / keyword passed to every enabled source.
    fcc_results:
        Pre-fetched FCC search results.  If ``None``, ``search_fcc(query)``
        is called automatically.
    ifixit_results:
        Pre-fetched iFixit search results.  If ``None``,
        ``search_ifixit(query)`` is called automatically.
    dest_root:
        Parent directory.  Source-specific subdirectories are created inside
        it: ``fcc/`` and ``ifixit/``.
    max_fcc:
        Maximum number of FCC filings to download photos from.
    max_ifixit:
        Maximum number of iFixit guides to download images from.

    Returns
    -------
    Total number of image files successfully downloaded across all sources.
    """
    dest_root = Path(dest_root)
    total = 0

    # --- FCC -----------------------------------------------------------
    if fcc_results is None:
        logger.info("Searching FCC for: %r", query)
        fcc_results = search_fcc(query)

    fcc_dest = dest_root / "fcc"
    for filing in fcc_results[:max_fcc]:
        fcc_id = filing.get("fcc_id", "")
        if not fcc_id:
            continue
        logger.info("Downloading FCC internal photos for: %s", fcc_id)
        paths = download_fcc_photos(fcc_id, fcc_dest / fcc_id)
        total += len(paths)
        logger.info("  → %d file(s) from FCC ID %s", len(paths), fcc_id)

    # --- iFixit --------------------------------------------------------
    if ifixit_results is None:
        logger.info("Searching iFixit for: %r", query)
        ifixit_results = search_ifixit(query)

    ifixit_dest = dest_root / "ifixit"
    for guide in ifixit_results[:max_ifixit]:
        guideid = guide.get("guideid")
        if guideid is None:
            continue
        logger.info("Downloading iFixit guide images for guide %s: %s", guideid, guide.get("title", ""))
        paths = download_guide_images(guideid, ifixit_dest / str(guideid))
        total += len(paths)
        logger.info("  → %d file(s) from guide %s", len(paths), guideid)

    logger.info("download_all complete: %d total images downloaded to %s", total, dest_root)
    return total
