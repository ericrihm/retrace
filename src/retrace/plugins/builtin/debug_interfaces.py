"""Built-in plugin: detects debug interface headers (JTAG, SWD, UART, SPI) from component patterns."""

from __future__ import annotations

from typing import Any

from retrace.core.pipeline import AnalysisResult

# ---------------------------------------------------------------------------
# Signature database — each entry maps interface name → keyword sets
# ---------------------------------------------------------------------------

_INTERFACE_PATTERNS: dict[str, dict[str, Any]] = {
    "JTAG": {
        "keywords": {"jtag", "tdi", "tdo", "tck", "tms", "trst", "jtag20", "jtag10", "arm20"},
        "pin_counts": {20, 14, 10},
        "severity": "high",
        "description": "JTAG debug interface — full CPU debug/program access",
        "cve_reference": "CWE-1191",
        "cvss_base": 7.6,
        "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
        "mitre_attack": ["T1200", "T0839"],
    },
    "SWD": {
        "keywords": {"swd", "swdio", "swdclk", "swclk", "swd20", "cortex-debug"},
        "pin_counts": {10, 4, 2},
        "severity": "high",
        "description": "ARM Serial Wire Debug — CoreSight access, firmware extraction risk",
        "cve_reference": "CWE-1191",
        "cvss_base": 7.6,
        "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
        "mitre_attack": ["T1200", "T0839"],
    },
    "UART": {
        "keywords": {"uart", "tx", "rx", "console", "serial", "debug", "ttyUSB", "tx1", "rx1"},
        "pin_counts": {4, 3, 2, 6},
        "severity": "medium",
        "description": "UART/serial console — may expose bootloader or root shell",
        "cve_reference": "CWE-1299",
        "cvss_base": 6.8,
        "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        "mitre_attack": ["T1200"],
    },
    "SPI": {
        "keywords": {"spi", "mosi", "miso", "sclk", "cs", "ss", "nss", "flash", "isp"},
        "pin_counts": {6, 4, 8},
        "severity": "medium",
        "description": "SPI interface — potential flash memory read/write access",
        "cve_reference": None,
        "cvss_base": 5.3,
        "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:L/A:N",
        "mitre_attack": ["T1200", "T0845"],
    },
    "I2C": {
        "keywords": {"i2c", "scl", "sda", "iic", "twi"},
        "pin_counts": {4, 2},
        "severity": "low",
        "description": "I2C bus — peripheral enumeration possible",
        "cve_reference": None,
        "cvss_base": 3.5,
        "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N",
        "mitre_attack": ["T1200"],
    },
}


def _marking_matches(marking: str, keywords: set[str]) -> bool:
    m = marking.lower()
    return any(kw in m for kw in keywords)


def _label_matches(label: str, keywords: set[str]) -> bool:
    return any(kw in label.lower() for kw in keywords)


def detect_debug_interfaces(board: AnalysisResult) -> list[dict[str, Any]]:
    """Detect known debug interfaces from component labels and markings.

    Args:
        board: AnalysisResult containing detected components.

    Returns:
        List of finding dicts with keys: interface, severity, description,
        component_id, cve_reference.
    """
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()

    for comp in board.components:
        for iface, sig in _INTERFACE_PATTERNS.items():
            keywords: set[str] = sig["keywords"]
            hit = _marking_matches(comp.marking, keywords) or _label_matches(comp.label, keywords)

            if hit and iface not in seen:
                seen.add(iface)
                findings.append(
                    {
                        "type": "debug_interface",
                        "interface": iface,
                        "severity": sig["severity"],
                        "description": sig["description"],
                        "component_id": comp.id,
                        "component_label": comp.label,
                        "component_marking": comp.marking,
                        "cve_reference": sig.get("cve_reference"),
                        "cvss_base": sig.get("cvss_base"),
                        "cvss_vector": sig.get("cvss_vector"),
                        "mitre_attack": sig.get("mitre_attack", []),
                    }
                )

    return findings


class DebugInterfaceAnalyzer:
    """Retrace analyzer plugin that detects exposed debug interfaces.

    Satisfies the :class:`retrace.plugins.base.AnalyzerPlugin` protocol.
    """

    name = "debug_interfaces"

    def analyze(self, board: AnalysisResult) -> dict[str, Any]:
        """Run debug interface detection against the board.

        Args:
            board: AnalysisResult to inspect.

        Returns:
            Dict with ``"findings"`` list and ``"summary"`` string.
        """
        findings = detect_debug_interfaces(board)
        high = sum(1 for f in findings if f["severity"] == "high")
        medium = sum(1 for f in findings if f["severity"] == "medium")

        return {
            "plugin": self.name,
            "findings": findings,
            "summary": (
                f"Detected {len(findings)} debug interface(s): "
                f"{high} high-severity, {medium} medium-severity"
            ),
        }
