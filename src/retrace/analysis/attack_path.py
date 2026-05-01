"""Attack path ranking — chip-to-chip exploitability scoring.

Builds a directed graph from component connections, enriches edges with
security intel (unencrypted buses, exposed debug interfaces, writable
flash), and ranks paths by composite exploitability score.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class AttackEdge:
    """A single hop in an attack path."""

    from_id: str
    to_id: str
    bus: str
    score: float
    rationale: str


@dataclass
class AttackPath:
    """A ranked end-to-end attack path through the board."""

    edges: list[AttackEdge] = field(default_factory=list)
    total_score: float = 0.0
    entry_point: str = ""
    target: str = ""
    description: str = ""


_BUS_SCORES: dict[str, float] = {
    "JTAG": 1.0,
    "SWD": 0.95,
    "UART": 0.8,
    "SPI": 0.7,
    "I2C": 0.5,
    "USB": 0.4,
    "SDIO": 0.35,
    "PCIe": 0.3,
    "DDR": 0.1,
}

_BUS_PATTERNS: dict[str, frozenset[str]] = {
    "SPI": frozenset({"mosi", "miso", "sclk", "cs", "spi", "flash", "w25q", "mx25", "at25"}),
    "I2C": frozenset({"sda", "scl", "i2c", "eeprom", "at24", "rtc", "sensor"}),
    "UART": frozenset({"uart", "tx", "rx", "serial", "console"}),
    "JTAG": frozenset({"jtag", "tdi", "tdo", "tms", "tck"}),
    "SWD": frozenset({"swd", "swdio", "swclk"}),
    "USB": frozenset({"usb", "dp", "dm", "hub", "xhci", "ehci"}),
    "SDIO": frozenset({"sdio", "emmc", "sd", "mmc", "nand"}),
    "PCIe": frozenset({"pcie", "pci", "lane", "nvme"}),
    "DDR": frozenset({"ddr", "dram", "sdram", "dimm"}),
}

_TARGET_SCORES: dict[str, float] = {
    "flash": 0.9,
    "fpga": 0.85,
    "crypto": 0.95,
    "tpm": 0.95,
    "mcu": 0.8,
    "soc": 0.8,
    "eeprom": 0.7,
    "memory": 0.3,
}

_ENTRY_LABELS = frozenset({"connector", "header", "test_point"})
_ENTRY_MARKINGS = frozenset({"jtag", "uart", "swd", "console", "debug", "serial"})

_TARGET_MARKINGS: dict[str, str] = {
    "flash": "flash",
    "w25q": "flash",
    "mx25": "flash",
    "at25": "flash",
    "fpga": "fpga",
    "spartan": "fpga",
    "artix": "fpga",
    "ice40": "fpga",
    "stm32": "mcu",
    "esp32": "mcu",
    "nrf52": "mcu",
    "pic": "mcu",
    "atecc": "crypto",
    "se050": "crypto",
    "stsafe": "crypto",
    "slb96": "tpm",
    "tpm": "tpm",
    "eeprom": "eeprom",
    "at24": "eeprom",
    "ddr": "memory",
    "sdram": "memory",
}


def _infer_bus(from_text: str, to_text: str) -> str:
    combined = f"{from_text} {to_text}"
    for bus, keywords in _BUS_PATTERNS.items():
        if any(kw in combined for kw in keywords):
            return bus
    return ""


def _classify_target(text: str) -> str:
    for keyword, category in _TARGET_MARKINGS.items():
        if keyword in text:
            return category
    return ""


def _is_entry_point(label: str, marking: str) -> bool:
    if label in _ENTRY_LABELS:
        return True
    return any(m in marking for m in _ENTRY_MARKINGS)


def _comp_text(comp: object) -> str:
    marking = getattr(comp, "marking", "") or ""
    part = getattr(comp, "part_number", "") or ""
    label = getattr(comp, "label", "") or ""
    return f"{marking} {part} {label}".lower()


def rank_attack_paths(result: object, top_k: int = 10) -> list[AttackPath]:
    """Rank chip-to-chip attack paths by exploitability."""
    comps = getattr(result, "components", None) or []
    traces = getattr(result, "traces", None) or []

    if not comps or not traces:
        return []

    comp_map: dict[str, object] = {}
    for c in comps:
        comp_map[c.id] = c

    adj: dict[str, list[tuple[str, str, float, str]]] = defaultdict(list)
    for t in traces:
        fc = t.from_component
        tc = t.to_component
        if not fc or not tc or fc not in comp_map or tc not in comp_map:
            continue
        ft = _comp_text(comp_map[fc])
        tt = _comp_text(comp_map[tc])
        bus = _infer_bus(ft, tt)
        if not bus:
            bus = "signal"
        score = _BUS_SCORES.get(bus, 0.2)
        rationale = f"{bus} bus"
        adj[fc].append((tc, bus, score, rationale))
        adj[tc].append((fc, bus, score, rationale))

    entry_points: list[str] = []
    high_value_targets: dict[str, str] = {}

    for c in comps:
        ct = _comp_text(c)
        label = getattr(c, "label", "") or ""
        marking = ct
        if _is_entry_point(label, marking):
            entry_points.append(c.id)
        cat = _classify_target(ct)
        if cat:
            high_value_targets[c.id] = cat

    if not entry_points or not high_value_targets:
        return []

    paths: list[AttackPath] = []
    max_depth = 4

    for entry in entry_points:
        queue: list[tuple[str, list[AttackEdge], set[str]]] = [
            (entry, [], {entry})
        ]
        while queue:
            current, edges, visited = queue.pop(0)
            if current in high_value_targets and edges:
                target_cat = high_value_targets[current]
                target_score = _TARGET_SCORES.get(target_cat, 0.3)
                hop_product = 1.0
                for e in edges:
                    hop_product *= e.score
                total = hop_product * target_score

                target_comp = comp_map.get(current)
                target_name = getattr(target_comp, "marking", current) or current

                chain = " → ".join(
                    f"{getattr(comp_map.get(e.from_id), 'marking', e.from_id) or e.from_id}"
                    for e in edges
                )
                chain += f" → {target_name}"
                desc = f"{chain} via {edges[-1].bus}"

                paths.append(AttackPath(
                    edges=list(edges),
                    total_score=total,
                    entry_point=entry,
                    target=current,
                    description=desc,
                ))

            if len(edges) >= max_depth:
                continue

            for neighbor, bus, score, rationale in adj.get(current, []):
                if neighbor not in visited:
                    new_edge = AttackEdge(
                        from_id=current,
                        to_id=neighbor,
                        bus=bus,
                        score=score,
                        rationale=rationale,
                    )
                    queue.append((
                        neighbor,
                        edges + [new_edge],
                        visited | {neighbor},
                    ))

    paths.sort(key=lambda p: p.total_score, reverse=True)
    return paths[:top_k]


def format_attack_paths(paths: list[AttackPath]) -> str:
    """Render attack paths as a human-readable report."""
    if not paths:
        return "No exploitable attack paths found."

    lines = [f"Attack Path Analysis — {len(paths)} path(s) ranked by exploitability", ""]
    for i, p in enumerate(paths, 1):
        lines.append(
            f"  #{i}  Score: {p.total_score:.3f}  "
            f"[{p.entry_point} → {p.target}]"
        )
        lines.append(f"       {p.description}")
        for edge in p.edges:
            lines.append(
                f"         {edge.from_id} → {edge.to_id}  "
                f"({edge.bus}, {edge.score:.2f})  {edge.rationale}"
            )
        lines.append("")
    return "\n".join(lines)
