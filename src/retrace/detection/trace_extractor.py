"""OpenCV copper trace extractor.

Uses color segmentation in HSV and LAB color space to isolate copper-colored
regions, then skeletonizes the mask and runs a BFS to extract individual
conductive paths as :class:`~retrace.core.pipeline.Trace` objects.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from retrace.core.pipeline import Trace

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Copper color ranges
# ---------------------------------------------------------------------------
# HSV ranges for bare copper (orange/brown tones) and gold-plated (yellow)
_HSV_COPPER_RANGES: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = [
    ((5, 60, 60), (25, 255, 255)),   # orange-copper
    ((20, 50, 100), (40, 255, 255)),  # golden/HASL
]

# LAB range for copper tones (provides better illumination invariance)
_LAB_COPPER_L = (30, 200)  # lightness
_LAB_COPPER_A = (120, 145)  # slightly red-shifted
_LAB_COPPER_B = (130, 175)  # yellow-shifted


def extract_traces(image_path: str | Path) -> dict[str, Any]:
    """Extract copper traces from an image file.

    Parameters
    ----------
    image_path:
        Path to the PCB image.

    Returns
    -------
    Dict with keys ``"traces"`` (list of dicts) and ``"count"`` (int).
    """
    try:
        import cv2  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "OpenCV is required for trace extraction.\n"
            "Install it with:  pip install opencv-python\n"
            f"Original error: {exc}"
        ) from exc

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not decode image: {path}")

    traces = extract_traces_from_image(img)
    return {
        "count": len(traces),
        "traces": [
            {
                "id": t.id,
                "points": t.points,
                "width_px": t.width_px,
                "from_component": t.from_component,
                "to_component": t.to_component,
            }
            for t in traces
        ],
    }


def extract_traces_from_image(img: np.ndarray) -> list[Trace]:
    """Extract copper traces from a BGR numpy image array.

    Pipeline:
    1. Color segment in both HSV and LAB to build a copper mask.
    2. Morphological clean-up (open + close).
    3. Skeletonize to 1-pixel-wide paths.
    4. BFS on the skeleton to enumerate connected paths.

    Parameters
    ----------
    img:
        BGR image as returned by ``cv2.imread``.

    Returns
    -------
    List of :class:`~retrace.core.pipeline.Trace` objects.
    """
    try:
        import cv2  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "OpenCV is required for trace extraction.\n"
            "Install it with:  pip install opencv-python\n"
            f"Original error: {exc}"
        ) from exc

    if img is None or img.size == 0:
        logger.warning("extract_traces_from_image: empty image")
        return []

    # Step 1: Build copper mask from HSV + LAB
    mask = _copper_mask(img)

    # Step 2: Morphological clean-up
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    if cv2.countNonZero(mask) == 0:
        logger.debug("No copper regions found after masking")
        return []

    # Step 3: Skeletonize
    skeleton = _skeletonize(mask)

    # Step 4: BFS to collect paths
    traces = _bfs_paths(skeleton, img)
    logger.debug("Extracted %d trace path(s)", len(traces))
    return traces


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _copper_mask(img: np.ndarray) -> np.ndarray:
    """Return a binary mask of copper-colored pixels."""
    import cv2  # type: ignore[import]

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)

    mask = np.zeros(img.shape[:2], dtype=np.uint8)

    # HSV-based ranges
    for lo, hi in _HSV_COPPER_RANGES:
        lo_arr = np.array(lo, dtype=np.uint8)
        hi_arr = np.array(hi, dtype=np.uint8)
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lo_arr, hi_arr))

    # LAB-based range (combined channel thresholds)
    l_ch, a_ch, b_ch = cv2.split(lab)
    lab_mask = (
        (l_ch >= _LAB_COPPER_L[0]) & (l_ch <= _LAB_COPPER_L[1])
        & (a_ch >= _LAB_COPPER_A[0]) & (a_ch <= _LAB_COPPER_A[1])
        & (b_ch >= _LAB_COPPER_B[0]) & (b_ch <= _LAB_COPPER_B[1])
    ).astype(np.uint8) * 255

    mask = cv2.bitwise_or(mask, lab_mask)
    return mask


def _skeletonize(mask: np.ndarray) -> np.ndarray:
    """Reduce binary mask to a 1-pixel-wide skeleton.

    Uses iterative thinning (Zhang-Suen-style) via repeated erosion if
    ``skimage`` is available, otherwise falls back to a manual morphological
    thinning loop.
    """
    try:
        from skimage.morphology import skeletonize as sk_skeletonize  # type: ignore[import]
        binary = mask > 0
        skel = sk_skeletonize(binary).astype(np.uint8) * 255
        return skel
    except ImportError:
        pass

    # Fallback: morphological thinning
    import cv2  # type: ignore[import]

    skel = np.zeros_like(mask)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    temp = mask.copy()
    for _ in range(100):  # max iterations
        eroded = cv2.erode(temp, element)
        dilated = cv2.dilate(eroded, element)
        diff = cv2.subtract(temp, dilated)
        skel = cv2.bitwise_or(skel, diff)
        temp = eroded.copy()
        if cv2.countNonZero(temp) == 0:
            break
    return skel


def _bfs_paths(skeleton: np.ndarray, img: np.ndarray) -> list[Trace]:
    """BFS over skeleton pixels to extract connected trace paths.

    Each connected component of the skeleton becomes one Trace.  The points
    list records every pixel in BFS order.  Trace width is estimated from
    the distance transform of the original mask.
    """
    import cv2  # type: ignore[import]

    # Distance transform for width estimation (approximate)
    _, mask_bin = cv2.threshold(skeleton, 0, 255, cv2.THRESH_BINARY)
    dist = cv2.distanceTransform(mask_bin, cv2.DIST_L2, 3)

    h, w = skeleton.shape
    visited = np.zeros((h, w), dtype=bool)
    traces: list[Trace] = []

    # 8-connectivity neighbours
    _neighbours = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    for start_y in range(h):
        for start_x in range(w):
            if skeleton[start_y, start_x] == 0 or visited[start_y, start_x]:
                continue

            # BFS from this seed pixel
            points: list[tuple[int, int]] = []
            widths: list[float] = []
            queue: deque[tuple[int, int]] = deque()
            queue.append((start_y, start_x))
            visited[start_y, start_x] = True

            while queue:
                cy, cx = queue.popleft()
                points.append((cx, cy))  # store as (x, y)
                widths.append(float(dist[cy, cx]) * 2.0)  # radius → diameter

                for dy, dx in _neighbours:
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w:
                        if skeleton[ny, nx] > 0 and not visited[ny, nx]:
                            visited[ny, nx] = True
                            queue.append((ny, nx))

            # Only keep traces with at least 5 pixels (filter noise)
            if len(points) < 5:
                continue

            avg_width = float(np.mean(widths)) if widths else 0.0
            traces.append(
                Trace(
                    id=f"T{uuid.uuid4().hex[:8]}",
                    points=points,
                    width_px=round(avg_width, 2),
                )
            )

    return traces
