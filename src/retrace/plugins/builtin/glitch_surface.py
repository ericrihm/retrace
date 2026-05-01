"""Built-in plugin: detects fault-injection surfaces (voltage glitch, clock glitch, EMFI)."""

from __future__ import annotations

import math
from typing import Any

from retrace.core.pipeline import AnalysisResult

_SECURITY_IC_KEYWORDS = frozenset({
    "tpm", "slb96", "atecc", "se050", "stsafe", "optiga",
    "stm32", "esp32", "nrf52", "pic", "mcu",
    "sam", "samd", "saml", "efm32", "lpc",
    "zynq", "fpga", "spartan", "artix", "ice40", "ecp5",
    "w25q", "mx25", "at25", "is25", "flash",
    "secure", "crypto", "hsm",
})

_VR_KEYWORDS = frozenset({
    "ldo", "vreg", "regulator", "tps7", "lm317", "ams1117",
    "ap2112", "mcp1700", "xc6206", "rt9013", "ht7333",
    "me6211", "sot-23", "sot-223",
    "buck", "boost", "dcdc", "mp1584", "lm2596", "tps54",
    "rt6150", "sy8089",
})

_CLOCK_KEYWORDS = frozenset({
    "crystal", "xtal", "osc", "oscillator", "mhz", "clock",
    "tcxo", "vcxo", "mems",
})

_SECURITY_IC_LABELS = frozenset({"ic"})
_VR_LABELS = frozenset({"ic", "capacitor", "inductor"})
_CLOCK_LABELS = frozenset({"crystal", "ic"})

_SMALL_PACKAGES = frozenset({
    "qfn", "bga", "wlcsp", "sot-23", "dfn", "dip-8",
    "tssop", "msop", "sop-8",
})


def _text(comp: Any) -> str:
    marking = getattr(comp, "marking", "") or ""
    part = getattr(comp, "part_number", "") or ""
    label = getattr(comp, "label", "") or ""
    value = getattr(comp, "value", "") or ""
    return f"{marking} {part} {label} {value}".lower()


def _center(comp: Any) -> tuple[float, float]:
    x, y, w, h = comp.bbox
    return (x + w / 2.0, y + h / 2.0)


def _distance(a: Any, b: Any) -> float:
    ax, ay = _center(a)
    bx, by = _center(b)
    return math.hypot(ax - bx, ay - by)


def _is_security_ic(comp: Any) -> bool:
    t = _text(comp)
    label = getattr(comp, "label", "") or ""
    return label.lower() in _SECURITY_IC_LABELS and any(kw in t for kw in _SECURITY_IC_KEYWORDS)


def _is_voltage_regulator(comp: Any) -> bool:
    t = _text(comp)
    return any(kw in t for kw in _VR_KEYWORDS)


def _is_clock_source(comp: Any) -> bool:
    t = _text(comp)
    label = getattr(comp, "label", "") or ""
    return label.lower() in _CLOCK_LABELS and any(kw in t for kw in _CLOCK_KEYWORDS)


_PROXIMITY_PX = 300


def detect_glitch_surfaces(board: AnalysisResult) -> list[dict[str, Any]]:
    """Detect voltage glitch, clock glitch, and EMFI fault injection surfaces."""
    findings: list[dict[str, Any]] = []
    comps = board.components

    security_ics = [c for c in comps if _is_security_ic(c)]
    voltage_regs = [c for c in comps if _is_voltage_regulator(c)]
    clock_sources = [c for c in comps if _is_clock_source(c)]

    for sec in security_ics:
        sec_text = _text(sec)

        for vr in voltage_regs:
            dist = _distance(sec, vr)
            if dist <= _PROXIMITY_PX:
                findings.append({
                    "type": "glitch_surface",
                    "subtype": "voltage_glitch",
                    "severity": "high",
                    "description": (
                        f"Voltage regulator {getattr(vr, 'marking', '') or vr.id} "
                        f"within {dist:.0f}px of security IC {getattr(sec, 'marking', '') or sec.id} — "
                        f"candidate for voltage fault injection (VFI)"
                    ),
                    "component_id": vr.id,
                    "target_component_id": sec.id,
                    "distance_px": round(dist),
                    "cve_reference": "CWE-1247",
                    "cvss_base": 6.8,
                    "cvss_vector": "CVSS:3.1/AV:P/AC:H/PR:N/UI:N/S:C/C:H/I:H/A:N",
                    "mitre_attack": ["T1200"],
                    "remediation": (
                        "Add voltage glitch detection circuitry, use brownout "
                        "detector with reset, or add external voltage supervisor"
                    ),
                })

        for clk in clock_sources:
            dist = _distance(sec, clk)
            if dist <= _PROXIMITY_PX:
                findings.append({
                    "type": "glitch_surface",
                    "subtype": "clock_glitch",
                    "severity": "medium",
                    "description": (
                        f"External clock source {getattr(clk, 'marking', '') or clk.id} "
                        f"within {dist:.0f}px of security IC {getattr(sec, 'marking', '') or sec.id} — "
                        f"candidate for clock fault injection"
                    ),
                    "component_id": clk.id,
                    "target_component_id": sec.id,
                    "distance_px": round(dist),
                    "cve_reference": "CWE-1247",
                    "cvss_base": 5.3,
                    "cvss_vector": "CVSS:3.1/AV:P/AC:H/PR:N/UI:N/S:U/C:H/I:L/A:N",
                    "mitre_attack": ["T1200"],
                    "remediation": (
                        "Use internal oscillator for security-critical operations, "
                        "or add clock integrity monitoring"
                    ),
                })

        pkg = (getattr(sec, "package", "") or "").lower()
        if pkg and any(p in pkg for p in _SMALL_PACKAGES):
            findings.append({
                "type": "glitch_surface",
                "subtype": "emfi",
                "severity": "medium",
                "description": (
                    f"Security IC {getattr(sec, 'marking', '') or sec.id} in "
                    f"{pkg.upper()} package — thin die accessible for "
                    f"electromagnetic fault injection (EMFI)"
                ),
                "component_id": sec.id,
                "target_component_id": sec.id,
                "distance_px": 0,
                "cve_reference": "CWE-1247",
                "cvss_base": 5.9,
                "cvss_vector": "CVSS:3.1/AV:P/AC:H/PR:N/UI:N/S:C/C:H/I:L/A:N",
                "mitre_attack": ["T1200"],
                "remediation": (
                    "Use metal-lidded package, add active shield mesh, "
                    "or implement hardware fault counters"
                ),
            })

    return findings


class GlitchSurfaceAnalyzer:
    """Retrace analyzer plugin that detects fault injection attack surfaces."""

    name = "glitch_surface"

    def analyze(self, board: AnalysisResult) -> dict[str, Any]:
        findings = detect_glitch_surfaces(board)
        voltage = sum(1 for f in findings if f["subtype"] == "voltage_glitch")
        clock = sum(1 for f in findings if f["subtype"] == "clock_glitch")
        emfi = sum(1 for f in findings if f["subtype"] == "emfi")

        return {
            "plugin": self.name,
            "findings": findings,
            "summary": (
                f"Detected {len(findings)} glitch surface(s): "
                f"{voltage} voltage, {clock} clock, {emfi} EMFI"
            ),
        }
