"""Learning engine — tracks detection frequency, cross-board knowledge, and sourcing suggestions."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_KNOWLEDGE_PATH = Path.home() / ".local" / "share" / "retrace" / "knowledge.json"


def _load_knowledge(path: Path = _KNOWLEDGE_PATH) -> dict[str, Any]:
    """Load the persistent knowledge store from disk, creating it if absent."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "version": "1.0",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "component_frequency": {},
        "board_sightings": {},
        "sourcing_queue": [],
        "sessions": 0,
    }


def _save_knowledge(data: dict[str, Any], path: Path = _KNOWLEDGE_PATH) -> None:
    """Persist the knowledge store to disk atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def record_detection(
    part_number: str,
    board_image: str = "",
    path: Path = _KNOWLEDGE_PATH,
) -> None:
    """Record a component detection event.

    Args:
        part_number: Identified part number (e.g. "STM32F103C8T6").
        board_image: Path to the source board image (optional, for cross-board tracking).
        path: Override knowledge store path (useful in tests).
    """
    data = _load_knowledge(path)
    freq = data.setdefault("component_frequency", {})
    freq[part_number] = freq.get(part_number, 0) + 1

    if board_image:
        sightings = data.setdefault("board_sightings", {})
        boards_for_part = sightings.setdefault(part_number, [])
        if board_image not in boards_for_part:
            boards_for_part.append(board_image)

    data["sessions"] = data.get("sessions", 0) + 1
    data["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save_knowledge(data, path)


def queue_for_sourcing(
    part_number: str,
    reason: str = "",
    path: Path = _KNOWLEDGE_PATH,
) -> None:
    """Add a part to the sourcing suggestion queue.

    Args:
        part_number: Part to source.
        reason: Human-readable rationale.
        path: Override knowledge store path.
    """
    data = _load_knowledge(path)
    queue = data.setdefault("sourcing_queue", [])
    existing = {item["part"] for item in queue}
    if part_number not in existing:
        queue.append(
            {
                "part": part_number,
                "reason": reason,
                "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
    _save_knowledge(data, path)


def top_components(n: int = 10, path: Path = _KNOWLEDGE_PATH) -> list[tuple[str, int]]:
    """Return the top-N most frequently detected components.

    Args:
        n: Number of results to return.
        path: Override knowledge store path.

    Returns:
        List of (part_number, count) tuples, descending by count.
    """
    data = _load_knowledge(path)
    freq = data.get("component_frequency", {})
    return sorted(freq.items(), key=lambda x: x[1], reverse=True)[:n]


def generate_report(path: Path = _KNOWLEDGE_PATH) -> str:
    """Produce a human-readable text report of current learning engine state.

    Args:
        path: Override knowledge store path (useful in tests).

    Returns:
        Multi-line string suitable for terminal or log output.
    """
    data = _load_knowledge(path)
    freq = data.get("component_frequency", {})
    sightings = data.get("board_sightings", {})
    queue = data.get("sourcing_queue", [])

    lines: list[str] = [
        "=" * 60,
        "  re:trace Learning Engine Report",
        "=" * 60,
        f"  Sessions recorded : {data.get('sessions', 0)}",
        f"  Unique parts seen : {len(freq)}",
        f"  Boards indexed    : {len({b for boards in sightings.values() for b in boards})}",
        f"  Sourcing queue    : {len(queue)} items",
        "",
    ]

    if freq:
        lines.append("  Top components by detection frequency:")
        for part, count in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]:
            board_count = len(sightings.get(part, []))
            lines.append(f"    {part:<30} {count:>4}x  ({board_count} board(s))")
        lines.append("")

    if queue:
        lines.append("  Sourcing suggestions:")
        for item in queue[:10]:
            lines.append(f"    {item['part']:<30} — {item.get('reason', '')}")
        lines.append("")

    if not freq and not queue:
        lines.append("  No data yet. Run 'retrace scan <image>' to start learning.")

    lines.append("=" * 60)
    return "\n".join(lines)
