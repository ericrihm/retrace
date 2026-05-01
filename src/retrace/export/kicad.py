"""KiCad netlist exporter — AnalysisResult → KiCad .net (XML) format."""

from __future__ import annotations

import time
from collections import defaultdict
from xml.sax.saxutils import escape

from retrace import __version__
from retrace.core.pipeline import AnalysisResult, Component, Trace

_LABEL_TO_LIB: dict[str, str] = {
    "ic": "Device:IC",
    "capacitor": "Device:C",
    "resistor": "Device:R",
    "inductor": "Device:L",
    "connector": "Connector:Conn_01x02",
    "crystal": "Device:Crystal",
    "header": "Connector:Conn_01x02",
    "test_point": "TestPoint:TestPoint",
}

_PASSIVE_LABELS = frozenset({"capacitor", "resistor", "inductor", "crystal"})

_PACKAGE_TO_FOOTPRINT: dict[str, str] = {
    "0201": "Resistor_SMD:R_0201_0603Metric",
    "0402": "Resistor_SMD:R_0402_1005Metric",
    "0603": "Resistor_SMD:R_0603_1608Metric",
    "0805": "Resistor_SMD:R_0805_2012Metric",
    "1206": "Resistor_SMD:R_1206_3216Metric",
    "SOT-23": "Package_TO_SOT_SMD:SOT-23",
    "SOT-223": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    "SOIC-8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "SOIC-16": "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
    "TQFP-32": "Package_QFP:TQFP-32_7x7mm_P0.8mm",
    "TQFP-48": "Package_QFP:TQFP-48_7x7mm_P0.5mm",
    "LQFP-48": "Package_QFP:LQFP-48_7x7mm_P0.5mm",
    "LQFP-64": "Package_QFP:LQFP-64_10x10mm_P0.5mm",
    "LQFP-100": "Package_QFP:LQFP-100_14x14mm_P0.5mm",
    "LQFP-144": "Package_QFP:LQFP-144_20x20mm_P0.5mm",
    "QFN-16": "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm",
    "QFN-32": "Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm",
    "QFN-48": "Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm",
    "BGA-256": "Package_BGA:BGA-256_17.0x17.0mm_Layout16x16_P1.0mm",
    "SSOP-8": "Package_SO:SSOP-8_3.9x5.05mm_P1.27mm",
    "DIP-8": "Package_DIP:DIP-8_W7.62mm",
    "DIP-14": "Package_DIP:DIP-14_W7.62mm",
    "DIP-16": "Package_DIP:DIP-16_W7.62mm",
}


def _footprint_for(comp: Component) -> str:
    """Best-effort map from component package to KiCad footprint library string."""
    pkg = comp.package.strip().upper()
    for key, fp in _PACKAGE_TO_FOOTPRINT.items():
        if key.upper() == pkg:
            return fp
    if comp.label == "capacitor" and not comp.package:
        return "Capacitor_SMD:C_0402_1005Metric"
    if comp.label == "resistor" and not comp.package:
        return "Resistor_SMD:R_0402_1005Metric"
    return ""


def _pin_count(comp: Component) -> int:
    """Assign a synthetic pin count based on component type."""
    if comp.label in _PASSIVE_LABELS:
        return 2
    if comp.label in ("test_point",):
        return 1
    if comp.label in ("connector", "header"):
        return 2
    return 4


def generate_kicad_netlist(
    result: AnalysisResult,
    title: str = "",
) -> str:
    """Generate a KiCad .net (XML) netlist from an AnalysisResult.

    The output is compatible with KiCad's ``File → Import → Netlist``
    workflow (KiCad 5/6/7/8 format).  Pin assignments are synthetic —
    two-terminal passives get pins 1/2, ICs get incrementing pin numbers
    based on observed trace endpoints.
    """
    ts = result.timestamp or time.strftime("%Y-%m-%d %H:%M:%S")
    source = escape(result.image_path)
    escape(title or result.image_path)

    nets = _build_nets(result.components, result.traces)

    lines: list[str] = []
    _w = lines.append

    _w('(export (version "E")')
    _w("  (design")
    _w(f'    (source "{source}")')
    _w(f'    (date "{ts}")')
    _w(f'    (tool "retrace {__version__}")')
    _w("  )")

    _w("  (components")
    for comp in result.components:
        _w(_render_component(comp))
    _w("  )")

    _w("  (nets")
    for net_code, (net_name, endpoints) in enumerate(nets.items(), start=1):
        _w(f'    (net (code "{net_code}") (name "{escape(net_name)}")')
        for ref, pin in endpoints:
            _w(f'      (node (ref "{escape(ref)}") (pin "{pin}"))')
        _w("    )")
    _w("  )")

    _w(")")
    return "\n".join(lines) + "\n"


def save_kicad_netlist(
    result: AnalysisResult,
    output_path: str,
    **kwargs: object,
) -> None:
    """Generate and write a KiCad .net netlist to disk."""
    from pathlib import Path

    content = generate_kicad_netlist(result, **kwargs)  # type: ignore[arg-type]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")


def _render_component(comp: Component) -> str:
    ref = escape(comp.id)
    value = escape(comp.value or comp.part_number or comp.marking or comp.label)
    footprint = escape(_footprint_for(comp))
    lib = escape(_LABEL_TO_LIB.get(comp.label, "Device:IC"))
    datasheet = escape(comp.datasheet_url) if comp.datasheet_url else "~"
    desc = escape(comp.marking) if comp.marking else "~"

    lines = [
        f'    (comp (ref "{ref}")',
        f'      (value "{value}")',
        f'      (footprint "{footprint}")',
        f'      (libsource (lib "{lib.split(":")[0]}") (part "{lib.split(":")[-1]}"))',
        f'      (datasheet "{datasheet}")',
        f'      (description "{desc}")',
    ]
    if comp.part_number:
        lines.append(f'      (property (name "MPN") (value "{escape(comp.part_number)}"))')
    if comp.package:
        lines.append(f'      (property (name "Package") (value "{escape(comp.package)}"))')
    lines.append("    )")
    return "\n".join(lines)


def _build_nets(
    components: list[Component],
    traces: list[Trace],
) -> dict[str, list[tuple[str, str]]]:
    """Build net name → [(ref, pin)] mapping from traces.

    For passives, pin 1 is always the 'from' side and pin 2 the 'to' side.
    For ICs, pins are assigned incrementally per component.
    """
    comp_map = {c.id: c for c in components}
    pin_counters: dict[str, int] = defaultdict(lambda: 1)
    nets: dict[str, list[tuple[str, str]]] = {}

    for trace in traces:
        if not trace.from_component or not trace.to_component:
            continue

        net_name = trace.id or f"Net-({trace.from_component}-{trace.to_component})"

        from_comp = comp_map.get(trace.from_component)
        to_comp = comp_map.get(trace.to_component)

        from_pin = str(pin_counters[trace.from_component])
        pin_counters[trace.from_component] += 1
        to_pin = str(pin_counters[trace.to_component])
        pin_counters[trace.to_component] += 1

        if from_comp and from_comp.label in _PASSIVE_LABELS:
            from_pin = str(min(int(from_pin), 2))
        if to_comp and to_comp.label in _PASSIVE_LABELS:
            to_pin = str(min(int(to_pin), 2))

        nets[net_name] = nets.get(net_name, [])
        nets[net_name].append((trace.from_component, from_pin))
        nets[net_name].append((trace.to_component, to_pin))

    return nets


# ---------------------------------------------------------------------------
# KiCad PCB positional export (.kicad_pcb)
# ---------------------------------------------------------------------------

_MM_PER_PX = 0.1


def _px_to_mm(px: float, scale: float = _MM_PER_PX) -> float:
    return px * scale


def generate_kicad_pcb(
    result: AnalysisResult,
    title: str = "",
    scale: float = _MM_PER_PX,
) -> str:
    """Generate a KiCad PCB file with approximate component placement.

    Converts pixel-space bounding boxes from photo analysis into millimeter
    positions. The board outline is derived from the image dimensions. Each
    component is placed as a reference-only footprint at its detected position.
    """
    bw = _px_to_mm(result.board_dimensions[0] or 1600, scale)
    bh = _px_to_mm(result.board_dimensions[1] or 1000, scale)

    lines: list[str] = []
    _w = lines.append

    _w("(kicad_pcb (version 20221018) (generator retrace)")
    _w("  (general")
    _w("    (thickness 1.6)")
    _w("  )")
    _w(f'  (paper "User" {bw:.2f} {bh:.2f})')
    _w("  (layers")
    _w('    (0 "F.Cu" signal)')
    _w('    (31 "B.Cu" signal)')
    _w('    (36 "B.SilkS" user "B.Silkscreen")')
    _w('    (37 "F.SilkS" user "F.Silkscreen")')
    _w('    (44 "Edge.Cuts" user)')
    _w("  )")

    _w(f"  (gr_rect (start 0 0) (end {bw:.2f} {bh:.2f}) (layer \"Edge.Cuts\") (width 0.1))")

    for comp in result.components:
        x, y, w, h = comp.bbox
        cx = _px_to_mm(x + w / 2, scale)
        cy = _px_to_mm(y + h / 2, scale)
        ref = escape(comp.id)
        value = escape(comp.value or comp.part_number or comp.marking or comp.label)
        fp = _footprint_for(comp)

        _w(f"  (footprint \"{escape(fp or 'retrace:Unknown')}\"")
        _w("    (layer \"F.Cu\")")
        _w(f"    (at {cx:.2f} {cy:.2f})")
        _w(f"    (property \"Reference\" \"{ref}\"")
        _w("      (at 0 -2) (layer \"F.SilkS\")")
        _w("      (effects (font (size 1 1) (thickness 0.15)))")
        _w("    )")
        _w(f"    (property \"Value\" \"{value}\"")
        _w("      (at 0 2) (layer \"F.SilkS\")")
        _w("      (effects (font (size 1 1) (thickness 0.15)))")
        _w("    )")
        _w("  )")

    _w(")")
    return "\n".join(lines) + "\n"


def save_kicad_pcb(
    result: AnalysisResult,
    output_path: str,
    **kwargs: object,
) -> None:
    """Generate and write a KiCad PCB file to disk."""
    from pathlib import Path

    content = generate_kicad_pcb(result, **kwargs)  # type: ignore[arg-type]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")
