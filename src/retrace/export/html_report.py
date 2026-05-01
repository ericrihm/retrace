"""Self-contained HTML assessment report — professional hardware security deliverable."""

from __future__ import annotations

import html
import time
from collections import Counter
from urllib.parse import urlparse

from retrace import __version__
from retrace.core.pipeline import AnalysisResult, Component, Trace

# ── Security keyword mapping (shared with svg.py) ──────────────────────
# (description, severity, CWE, CVSS base score, CVSS vector, MITRE ATT&CK)
_SECURITY_KEYWORDS: dict[str, tuple[str, str, str, float, str, list[str]]] = {
    "JTAG": ("JTAG debug — full CPU access", "HIGH", "CWE-1191", 7.6,
             "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", ["T1200", "T0839"]),
    "SWD": ("SWD debug — ARM CoreSight", "HIGH", "CWE-1191", 7.6,
            "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", ["T1200", "T0839"]),
    "UART": ("UART/serial console", "MEDIUM", "CWE-1299", 6.8,
             "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", ["T1200"]),
    "CONSOLE": ("Serial console — bootloader/shell", "MEDIUM", "CWE-1299", 6.8,
                "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", ["T1200"]),
    "SPI": ("SPI bus — firmware extraction", "MEDIUM", "CWE-1191", 5.3,
            "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:L/A:N", ["T1200", "T0845"]),
}

_LABEL_COLORS: dict[str, str] = {
    "ic": "#ef4444",
    "capacitor": "#3b82f6",
    "resistor": "#22c55e",
    "connector": "#f59e0b",
    "inductor": "#a855f7",
    "crystal": "#14b8a6",
    "header": "#f97316",
    "test_point": "#ec4899",
    "unknown": "#6b7280",
}

_NET_COLORS: dict[str, str] = {
    "power": "#ef4444",
    "ground": "#6b7280",
    "data": "#3b82f6",
    "clock": "#f59e0b",
    "signal": "#06b6d4",
    "debug": "#d946ef",
    "unknown": "#6b7280",
}

_SEVERITY_COLORS: dict[str, str] = {
    "HIGH": "#ef4444",
    "MEDIUM": "#f59e0b",
    "LOW": "#3b82f6",
}

_SEVERITY_ORDER: dict[str, int] = {
    "HIGH": 0,
    "MEDIUM": 1,
    "LOW": 2,
}


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text))


def _safe_url(url: str) -> str:
    """Return *url* only if it uses http or https; empty string otherwise."""
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        return url
    return ""


def _pretty_type(label: str) -> str:
    return label.replace("_", " ").title()


def _classify_net(trace: Trace, comp_map: dict[str, Component]) -> str:
    """Classify a trace's net type based on connected components."""
    from_c = comp_map.get(trace.from_component)
    to_c = comp_map.get(trace.to_component)

    from_marking = (from_c.marking if from_c else "").upper()
    to_marking = (to_c.marking if to_c else "").upper()
    from_label = from_c.label if from_c else ""
    to_label = to_c.label if to_c else ""
    all_text = f"{from_marking} {to_marking} {from_label} {to_label}"

    if any(kw in all_text for kw in ("JTAG", "SWD", "UART", "TDI", "TDO", "TCK", "TMS")):
        return "debug"
    if any(kw in all_text for kw in ("VRM", "TPS", "IR35", "VCC", "VDD", "PWR", "POWER")):
        return "power"
    if trace.width_px >= 5:
        return "power"
    if any(kw in all_text for kw in ("CLK", "XTAL", "OSC")):
        return "clock"
    if any(kw in all_text for kw in ("GND", "GROUND", "VSS")):
        return "ground"
    if any(kw in all_text for kw in ("DATA", "SDA", "SCL", "MOSI", "MISO", "TX", "RX")):
        return "data"
    return "signal"


def _detect_security_findings(
    result: AnalysisResult,
) -> list[dict[str, str]]:
    """Scan components for exposed debug/security-relevant interfaces."""
    findings: list[dict[str, str]] = []
    seen: set[str] = set()

    for comp in result.components:
        text = f"{comp.marking} {comp.label} {comp.part_number}".upper()
        for keyword, entry in _SECURITY_KEYWORDS.items():
            desc, severity, cwe = entry[0], entry[1], entry[2]
            cvss_base = entry[3] if len(entry) > 3 else None
            cvss_vector = entry[4] if len(entry) > 4 else None
            mitre = entry[5] if len(entry) > 5 else []
            if keyword in text:
                key = f"{keyword}:{comp.id}"
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "severity": severity,
                        "interface": keyword,
                        "component": comp.id,
                        "cwe": cwe,
                        "description": desc,
                        "cvss_base": cvss_base,
                        "cvss_vector": cvss_vector,
                        "mitre_attack": mitre,
                    })

    findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 99), f["interface"]))
    return findings


def _build_executive_summary(
    result: AnalysisResult,
    findings: list[dict[str, str]],
    title: str,
) -> str:
    """Generate 2-3 sentence executive summary."""
    board_name = title or result.image_path or "Unknown board"
    identified = sum(1 for c in result.components if c.part_number)
    total = len(result.components)

    lines: list[str] = []
    lines.append(
        f"Analysis of <strong>{_esc(board_name)}</strong> identified "
        f"{total} component{'s' if total != 1 else ''} "
        f"({identified} with part number matches) "
        f"and {len(result.traces)} trace{'s' if len(result.traces) != 1 else ''}."
    )

    if findings:
        by_sev: dict[str, int] = Counter(f["severity"] for f in findings)
        parts = []
        for sev in ("HIGH", "MEDIUM", "LOW"):
            count = by_sev.get(sev, 0)
            if count:
                parts.append(f"{count} {sev}")
        max_cvss = max((f.get("cvss_base") or 0 for f in findings), default=0)
        cvss_note = f" (max CVSS {max_cvss})" if max_cvss else ""
        lines.append(f"Security scan detected {', '.join(parts)} severity finding{'s' if len(findings) != 1 else ''}{cvss_note}.")
        debug_count = sum(1 for f in findings if f["severity"] == "HIGH")
        if debug_count:
            lines.append(
                f"{debug_count} exposed debug interface{'s' if debug_count != 1 else ''} "
                f"requiring physical access controls."
            )
        attack_ids = sorted({tid for f in findings for tid in (f.get("mitre_attack") or [])})
        if attack_ids:
            lines.append(f"Mapped to MITRE ATT&amp;CK technique{'s' if len(attack_ids) != 1 else ''}: {', '.join(attack_ids)}.")
    else:
        lines.append("No exposed debug interfaces detected.")

    return " ".join(lines)


# ── CSS ─────────────────────────────────────────────────────────────────

_CSS = """\
:root {
    --bg: #0a0e1a;
    --panel-bg: #111827;
    --panel-border: #1e293b;
    --text-hi: #e2e8f0;
    --text-mid: #94a3b8;
    --text-lo: #64748b;
    --accent: #22d3ee;
    --row-even: #0f1629;
    --row-odd: #111d35;
    --severity-high: #ef4444;
    --severity-med: #f59e0b;
    --severity-low: #3b82f6;
    --conf-green: #22c55e;
    --conf-yellow: #f59e0b;
    --conf-red: #ef4444;
    --conf-bg: #1e293b;
}

*, *::before, *::after { box-sizing: border-box; }
html { scroll-behavior: smooth; }

body {
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--text-hi);
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 14px;
    line-height: 1.6;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px 24px 24px 220px;
}

/* ── Sidebar navigation ─────────────────────────────────── */
.sidebar {
    position: fixed;
    top: 0; left: 0;
    width: 200px;
    height: 100vh;
    background: var(--panel-bg);
    border-right: 1px solid var(--panel-border);
    padding: 16px 0;
    overflow-y: auto;
    z-index: 100;
    font-size: 12px;
}
.sidebar .sidebar-title {
    color: var(--accent);
    font-weight: 700;
    font-size: 13px;
    padding: 0 16px 12px;
    border-bottom: 1px solid var(--panel-border);
    margin-bottom: 8px;
}
.sidebar a {
    display: block;
    padding: 6px 16px;
    color: var(--text-mid);
    text-decoration: none;
    border-left: 3px solid transparent;
    transition: color 0.15s, border-color 0.15s;
}
.sidebar a:hover, .sidebar a.active {
    color: var(--accent);
    border-left-color: var(--accent);
    background: rgba(34,211,238,0.05);
}

/* ── Back-to-top button ─────────────────────────────────── */
.back-to-top {
    position: fixed;
    bottom: 24px; right: 24px;
    width: 40px; height: 40px;
    border-radius: 50%;
    background: var(--accent);
    color: var(--bg);
    border: none;
    cursor: pointer;
    font-size: 18px;
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 200;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4);
}
.back-to-top.visible { display: flex; }

/* ── Report classification banner ────────────────────────── */
.report-meta {
    background: rgba(239,68,68,0.08);
    border: 1px solid rgba(239,68,68,0.25);
    border-radius: 6px;
    padding: 10px 16px;
    margin-bottom: 16px;
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 11px;
    color: var(--text-mid);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.report-meta .classification {
    color: var(--severity-high);
    font-weight: 700;
    letter-spacing: 1px;
}

/* ── Header ──────────────────────────────────────────────── */
.report-header {
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    padding: 32px;
    margin-bottom: 24px;
}
.report-header h1 {
    margin: 0 0 4px 0;
    font-size: 24px;
    color: var(--accent);
    font-weight: 700;
}
.report-header .subtitle {
    color: var(--text-mid);
    font-size: 14px;
    margin: 0 0 20px 0;
}
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
}
.stat-box {
    background: var(--bg);
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 12px 16px;
    text-align: center;
}
.stat-box .stat-value {
    font-size: 28px;
    font-weight: 700;
    color: var(--accent);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
.stat-box .stat-label {
    font-size: 11px;
    color: var(--text-lo);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* ── Sections ────────────────────────────────────────────── */
.section {
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    padding: 24px;
    margin-bottom: 24px;
}
.section h2 {
    margin: 0 0 16px 0;
    font-size: 18px;
    color: var(--text-hi);
    border-bottom: 1px solid var(--panel-border);
    padding-bottom: 8px;
}

/* ── Executive Summary ───────────────────────────────────── */
.exec-summary {
    font-size: 15px;
    line-height: 1.7;
    color: var(--text-mid);
}

/* ── Tables ──────────────────────────────────────────────── */
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
th {
    text-align: left;
    padding: 8px 12px;
    background: var(--bg);
    color: var(--text-lo);
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.5px;
    border-bottom: 2px solid var(--accent);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}
th:hover { color: var(--accent); }
th .sort-arrow { font-size: 10px; margin-left: 4px; }
td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--panel-border);
    color: var(--text-hi);
    vertical-align: middle;
}
tr:nth-child(even) td { background: var(--row-even); }
tr:nth-child(odd) td { background: var(--row-odd); }
.table-footer {
    text-align: right;
    font-size: 12px;
    color: var(--text-lo);
    padding-top: 8px;
}

/* ── Badges ──────────────────────────────────────────────── */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}
.badge-high { background: rgba(239,68,68,0.15); color: var(--severity-high); border: 1px solid rgba(239,68,68,0.3); }
.badge-medium { background: rgba(245,158,11,0.15); color: var(--severity-med); border: 1px solid rgba(245,158,11,0.3); }
.badge-low { background: rgba(59,130,246,0.15); color: var(--severity-low); border: 1px solid rgba(59,130,246,0.3); }

.type-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
}

/* ── Confidence bar ──────────────────────────────────────── */
.conf-bar {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 120px;
}
.conf-bar-track {
    width: 80px;
    height: 8px;
    background: var(--conf-bg);
    border-radius: 4px;
    overflow: hidden;
}
.conf-bar-fill {
    height: 100%;
    border-radius: 4px;
}
.conf-bar-text {
    font-size: 11px;
    color: var(--text-lo);
    min-width: 32px;
}

/* ── Links ───────────────────────────────────────────────── */
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Zone cards ──────────────────────────────────────────── */
.zone-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
}
.zone-card {
    background: var(--bg);
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 16px;
}
.zone-card h3 {
    margin: 0 0 4px 0;
    font-size: 14px;
    color: var(--text-hi);
}
.zone-card .zone-type {
    font-size: 11px;
    color: var(--text-lo);
    text-transform: uppercase;
    margin-bottom: 8px;
}
.zone-card .zone-components {
    font-size: 12px;
    color: var(--text-mid);
    line-height: 1.5;
}
details summary {
    cursor: pointer;
    color: var(--accent);
    font-size: 12px;
}

/* ── Net breakdown ───────────────────────────────────────── */
.net-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: 8px;
}
.net-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    background: var(--bg);
    border: 1px solid var(--panel-border);
    border-radius: 4px;
    font-size: 12px;
}
.net-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}
.net-count {
    font-weight: 700;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    color: var(--text-hi);
}
.net-label {
    color: var(--text-mid);
    text-transform: capitalize;
}

/* ── Component Intel cards ───────────────────────────────── */
.intel-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 12px;
}
.intel-card {
    background: var(--bg);
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 16px;
}
.intel-card h3 {
    margin: 0 0 8px 0;
    font-size: 14px;
    color: var(--text-hi);
    display: flex;
    align-items: center;
    gap: 8px;
}
.intel-card h3 .intel-cat {
    font-size: 10px;
    color: var(--accent);
    text-transform: uppercase;
    font-weight: 700;
    background: rgba(0, 168, 255, 0.12);
    padding: 2px 6px;
    border-radius: 3px;
}
.intel-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
}
.intel-table td {
    padding: 3px 6px;
    border: none;
    border-bottom: 1px solid var(--panel-border);
}
.intel-table td:first-child {
    color: var(--text-lo);
    font-weight: 600;
    white-space: nowrap;
    width: 40%;
}
.intel-table td:last-child {
    color: var(--text-hi);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 11px;
}
.intel-table .intel-highlight {
    color: #ff6b6b;
    font-weight: 700;
}

/* ── CVSS gauge ─────────────────────────────────────────── */
.cvss-gauge { display: inline-block; vertical-align: middle; margin-right: 6px; }

/* ── Risk matrix bar ────────────────────────────────────── */
.risk-bar { display: flex; height: 28px; border-radius: 4px; overflow: hidden; margin: 12px 0; }
.risk-bar div { display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 700; color: #fff; min-width: 32px; }

/* ── Attack chain ───────────────────────────────────────── */
.attack-chain-svg { max-width: 100%; margin: 16px 0; }

/* ── Footer ──────────────────────────────────────────────── */
.report-footer {
    text-align: center;
    padding: 24px;
    color: var(--text-lo);
    font-size: 12px;
    border-top: 1px solid var(--panel-border);
}
.report-footer a { color: var(--text-lo); }
.report-footer a:hover { color: var(--accent); }

/* ── Print ───────────────────────────────────────────────── */
@media print {
    :root {
        --bg: #ffffff;
        --panel-bg: #ffffff;
        --panel-border: #d1d5db;
        --text-hi: #111827;
        --text-mid: #374151;
        --text-lo: #6b7280;
        --accent: #0891b2;
        --row-even: #f9fafb;
        --row-odd: #ffffff;
    }
    html { scroll-behavior: auto; }
    body { background: white; color: black; }
    .sidebar, .back-to-top { display: none !important; }
    .container { padding: 0; margin: 0; max-width: 100%; }
    .report-header { page-break-after: always; }
    .section { break-inside: avoid; page-break-before: auto; margin-bottom: 0; }
    table { font-size: 10px; }
    @page { size: A4; margin: 20mm 15mm 20mm 15mm;
        @top-center { content: "CONFIDENTIAL — re:trace Hardware Security Assessment"; font-size: 8pt; color: #999; }
        @bottom-right { content: "Page " counter(page); font-size: 8pt; color: #999; }
    }
}

/* ── Responsive ──────────────────────────────────────────── */
@media (max-width: 768px) {
    .sidebar { display: none; }
    .container { padding: 12px; }
    .report-header { padding: 16px; }
    .section { padding: 16px; }
    table { font-size: 11px; }
    th, td { padding: 4px 6px; }
}
"""

# ── JavaScript ─────────────────────────────────────────────────────────
_JS = """\
(function() {
    /* ── Table sorting ──────────────────────────────────── */
    document.querySelectorAll('th[data-sortable]').forEach(function(th) {
        th.addEventListener('click', function() {
            var table = th.closest('table');
            var tbody = table.querySelector('tbody');
            var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
            var colIdx = Array.prototype.indexOf.call(th.parentNode.children, th);
            var dir = th.getAttribute('data-sort-dir') === 'asc' ? 'desc' : 'asc';
            th.parentNode.querySelectorAll('th').forEach(function(h) {
                h.removeAttribute('data-sort-dir');
                var arrow = h.querySelector('.sort-arrow');
                if (arrow) arrow.textContent = '';
            });
            th.setAttribute('data-sort-dir', dir);
            var arrow = th.querySelector('.sort-arrow');
            if (arrow) arrow.textContent = dir === 'asc' ? '\\u25B2' : '\\u25BC';
            rows.sort(function(a, b) {
                var aText = a.children[colIdx].getAttribute('data-sort-value')
                         || a.children[colIdx].textContent.trim();
                var bText = b.children[colIdx].getAttribute('data-sort-value')
                         || b.children[colIdx].textContent.trim();
                var aNum = parseFloat(aText);
                var bNum = parseFloat(bText);
                var cmp;
                if (!isNaN(aNum) && !isNaN(bNum)) { cmp = aNum - bNum; }
                else { cmp = aText.localeCompare(bText); }
                return dir === 'asc' ? cmp : -cmp;
            });
            rows.forEach(function(row) { tbody.appendChild(row); });
        });
    });

    /* ── Scroll-spy for sidebar ─────────────────────────── */
    var links = document.querySelectorAll('.sidebar a[href^=\"#\"]');
    if (links.length && 'IntersectionObserver' in window) {
        var ids = [];
        links.forEach(function(a) { ids.push(a.getAttribute('href').slice(1)); });
        var observer = new IntersectionObserver(function(entries) {
            entries.forEach(function(e) {
                var a = document.querySelector('.sidebar a[href=\"#' + e.target.id + '\"]');
                if (a) { if (e.isIntersecting) a.classList.add('active'); else a.classList.remove('active'); }
            });
        }, { rootMargin: '-20% 0px -70% 0px' });
        ids.forEach(function(id) { var el = document.getElementById(id); if (el) observer.observe(el); });
    }

    /* ── Back-to-top button ─────────────────────────────── */
    var btn = document.querySelector('.back-to-top');
    if (btn) {
        window.addEventListener('scroll', function() {
            btn.classList.toggle('visible', window.scrollY > 400);
        });
        btn.addEventListener('click', function() { window.scrollTo({top:0,behavior:'smooth'}); });
    }
})();
"""


def _cvss_gauge_svg(score: float, size: int = 36) -> str:
    """Render a small circular CVSS gauge as inline SVG."""
    if not score:
        return ""
    r = (size - 4) / 2
    cx = cy = size / 2
    circum = 2 * 3.14159 * r
    frac = min(score / 10.0, 1.0)
    dash = frac * circum
    if score >= 7.0:
        color = "#ef4444"
    elif score >= 4.0:
        color = "#f59e0b"
    else:
        color = "#3b82f6"
    _mono = "'JetBrains Mono','Fira Code','SF Mono',monospace"
    cx_s = f"{cx:.1f}".rstrip("0").rstrip(".")
    cy_s = f"{cy:.1f}".rstrip("0").rstrip(".")
    r_s = f"{r:.1f}".rstrip("0").rstrip(".")
    return (
        f'<svg class="cvss-gauge" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<circle cx="{cx_s}" cy="{cy_s}" r="{r_s}" fill="none" stroke="#1e293b" stroke-width="3"/>'
        f'<circle cx="{cx_s}" cy="{cy_s}" r="{r_s}" fill="none" stroke="{color}" stroke-width="3" '
        f'stroke-dasharray="{dash:.1f} {circum:.1f}" stroke-linecap="round" '
        f'transform="rotate(-90 {cx_s} {cy_s})"/>'
        f'<text x="{cx_s}" y="{cy_s}" text-anchor="middle" dominant-baseline="central" '
        f'fill="{color}" font-size="{size*0.32:.0f}" font-weight="700" '
        f'font-family="{_mono}">{score}</text></svg>'
    )


def _risk_matrix_svg(findings: list[dict[str, str]]) -> str:
    """Render an inline stacked bar showing severity distribution."""
    by_sev: dict[str, int] = Counter(f["severity"] for f in findings)
    total = len(findings) or 1
    parts: list[str] = []
    for sev, color in [("HIGH", "#ef4444"), ("MEDIUM", "#f59e0b"), ("LOW", "#3b82f6")]:
        count = by_sev.get(sev, 0)
        if count:
            pct = max(count / total * 100, 12)
            parts.append(
                f'<div style="width:{pct:.0f}%;background:{color};">'
                f'{count} {sev}</div>'
            )
    if not parts:
        return ""
    return '<div class="risk-bar">' + "".join(parts) + "</div>"


def _attack_chain_svg(attack_paths: list[tuple[str, str, str]]) -> str:
    """Render attack paths as an inline SVG flowchart."""
    if not attack_paths:
        return ""
    h_per = 60
    total_h = len(attack_paths) * h_per + 20
    lines: list[str] = [
        f'<svg class="attack-chain-svg" width="700" height="{total_h}" '
        f'viewBox="0 0 700 {total_h}" xmlns="http://www.w3.org/2000/svg">'
    ]
    _mono = "'JetBrains Mono','Fira Code','SF Mono',monospace"
    for i, (src, tgt, desc) in enumerate(attack_paths):
        y = 20 + i * h_per
        # Source box
        lines.append(f'<rect x="10" y="{y}" width="160" height="36" rx="6" '
                      f'fill="#1e293b" stroke="#22d3ee" stroke-width="1"/>')
        lines.append(f'<text x="90" y="{y+22}" text-anchor="middle" fill="#e2e8f0" '
                      f'font-size="11" font-family="{_mono}">{_esc(src[:20])}</text>')
        # Arrow with label
        lines.append(f'<line x1="170" y1="{y+18}" x2="370" y2="{y+18}" '
                      f'stroke="#64748b" stroke-width="1.5" marker-end="url(#ah)"/>')
        lines.append(f'<text x="270" y="{y+12}" text-anchor="middle" fill="#94a3b8" '
                      f'font-size="9" font-family="{_mono}">{_esc(desc[:30])}</text>')
        # Target box
        lines.append(f'<rect x="370" y="{y}" width="160" height="36" rx="6" '
                      f'fill="#1e293b" stroke="#ef4444" stroke-width="1"/>')
        lines.append(f'<text x="450" y="{y+22}" text-anchor="middle" fill="#e2e8f0" '
                      f'font-size="11" font-family="{_mono}">{_esc(tgt[:20])}</text>')
    # Arrowhead marker
    lines.insert(1, '<defs><marker id="ah" viewBox="0 0 10 10" refX="10" refY="5" '
                     'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
                     '<path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/></marker></defs>')
    lines.append("</svg>")
    return "\n".join(lines)


def _intel_components_present(result: AnalysisResult) -> bool:
    """Check if any components have security intel data."""
    try:
        from retrace.identification.matcher import _LOOKUP
        return any(
            _LOOKUP.get((c.part_number or "").upper(), {}).get("security_intel")
            for c in result.components if c.part_number
        )
    except Exception:
        return False


# ── Section numbering ──────────────────────────────────────────────────
_SECTIONS = [
    ("sec-summary", "Executive Summary"),
    ("sec-methodology", "Methodology"),
    ("sec-findings", "Security Findings"),
    ("sec-intel", "Component Intelligence"),
    ("sec-bom", "Component Inventory"),
    ("sec-zones", "Functional Zones"),
    ("sec-traces", "Trace Analysis"),
]


# ── HTML builder ────────────────────────────────────────────────────────


def generate_html_report(
    result: AnalysisResult,
    title: str = "",
    zones: list[tuple[str, str, list[str]]] | None = None,
    attack_paths: list[tuple[str, str, str]] | None = None,
) -> str:
    """Generate a self-contained HTML hardware security assessment report.

    Args:
        result: Completed AnalysisResult from Pipeline.run().
        title: Board name / report title.
        zones: Optional list of (zone_name, zone_type, [component_ids]).
        attack_paths: Optional list of (source, target, description) -- reserved
                      for future use.

    Returns:
        Complete HTML document as a string.
    """
    board_name = title or result.image_path or "Board Analysis"
    timestamp = result.timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    findings = _detect_security_findings(result)
    summary = result.summary()

    parts: list[str] = []
    _a = parts.append

    # ── Document head ───────────────────────────────────────────────
    _a("<!DOCTYPE html>")
    _a('<html lang="en">')
    _a("<head>")
    _a('<meta charset="utf-8">')
    _a('<meta name="viewport" content="width=device-width, initial-scale=1">')
    _a(f"<title>re:trace — {_esc(board_name)}</title>")
    _a(f"<style>{_CSS}</style>")
    _a("</head>")
    _a("<body>")

    # ── Sidebar navigation ─────────────────────────────────────────
    _a('<nav class="sidebar">')
    _a('<div class="sidebar-title">re:trace</div>')
    sec_num = 1
    for sec_id, sec_label in _SECTIONS:
        if sec_id == "sec-intel" and not _intel_components_present(result):
            continue
        if sec_id == "sec-zones" and not zones:
            continue
        _a(f'<a href="#{sec_id}">{sec_num}. {sec_label}</a>')
        sec_num += 1
    _a("</nav>")

    _a('<div class="container">')

    # ── Report metadata banner ─────────────────────────────────────
    _a('<div class="report-meta">')
    _a('<span class="classification">CONFIDENTIAL</span>')
    _a(f"<span>Assessment date: {_esc(timestamp[:10])}</span>")
    _a(f"<span>re:trace v{_esc(__version__)}</span>")
    _a(f"<span>Pipeline v{_esc(result.pipeline_version)}</span>")
    _a("</div>")

    # ── 1. Header ───────────────────────────────────────────────────
    _a('<header class="report-header">')
    _a("<h1>re:trace — Hardware Security Assessment</h1>")
    _a(f'<p class="subtitle">{_esc(board_name)} &middot; {_esc(timestamp)} &middot; Pipeline v{_esc(result.pipeline_version)}</p>')
    _a('<div class="stats-grid">')
    for val, label in [
        (str(summary["components"]), "Components"),
        (str(summary["identified"]), "Identified"),
        (str(summary["traces"]), "Traces"),
        (str(len(findings)), "Findings"),
    ]:
        _a(f'<div class="stat-box"><div class="stat-value">{_esc(val)}</div><div class="stat-label">{_esc(label)}</div></div>')
    _a("</div>")
    _a("</header>")

    # ── Section counter for numbering ─────────────────────────────
    _sec = [0]
    def _sec_heading(sec_id: str, label: str) -> str:
        _sec[0] += 1
        return f'<section id="{sec_id}" class="section"><h2>{_sec[0]}. {label}</h2>'

    # ── 2. Executive Summary ────────────────────────────────────────
    _a(_sec_heading("sec-summary", "Executive Summary"))
    exec_text = _build_executive_summary(result, findings, title)
    _a(f'<div class="exec-summary">{exec_text}</div>')
    # Risk matrix bar
    if findings:
        _a(_risk_matrix_svg(findings))
    _a("</section>")

    # ── 3. Methodology ────────────────────────────────────────────
    _a(_sec_heading("sec-methodology", "Methodology"))
    _a('<div style="color:var(--text-mid);font-size:13px;line-height:1.7;">')
    _a("<p>This assessment was performed using automated PCB reverse engineering techniques:</p>")
    _a("<ol>")
    _a("<li><strong>Component Detection</strong> &mdash; YOLO v8 object detection with OpenCV contour fallback for air-gapped environments.</li>")
    _a("<li><strong>OCR &amp; Identification</strong> &mdash; EasyOCR marking extraction with fuzzy matching against a 128-part component database.</li>")
    _a("<li><strong>Trace Extraction</strong> &mdash; Dual-space (HSV+LAB) color segmentation with Zhang-Suen skeletonization for copper trace mapping.</li>")
    _a("<li><strong>Constraint Inference</strong> &mdash; AC-3 arc consistency propagation to infer connections not directly visible.</li>")
    _a("<li><strong>Security Analysis</strong> &mdash; Pattern-matched debug interface detection with CVSS 3.1 scoring and MITRE ATT&amp;CK mapping.</li>")
    _a("</ol>")
    _a("<p>Findings are classified per CVSS v3.1 (physical access vector). CWE references follow MITRE CWE v4.x. ATT&amp;CK technique IDs reference both Enterprise (T1200) and ICS (T0839, T0845) matrices.</p>")
    _a("</div>")
    _a("</section>")

    # ── 4. Security Findings ────────────────────────────────────────
    _a(_sec_heading("sec-findings", "Security Findings"))
    if findings:
        _a("<table>")
        _a("<thead><tr>")
        for col in ("Severity", "CVSS", "Interface", "Component", "CWE", "ATT&amp;CK", "Description"):
            _a(f"<th>{col}</th>")
        _a("</tr></thead>")
        _a("<tbody>")
        for f in findings:
            sev = f["severity"]
            badge_cls = f"badge-{sev.lower()}"
            cwe = f["cwe"]
            cwe_num = cwe.replace("CWE-", "")
            cwe_url = f"https://cwe.mitre.org/data/definitions/{_esc(cwe_num)}.html"
            cvss = f.get("cvss_base", "")
            cvss_str = f"{cvss}" if cvss else "—"
            gauge = _cvss_gauge_svg(cvss) if cvss else ""
            attack_ids = f.get("mitre_attack", [])
            attack_links = []
            for tid in attack_ids:
                url = f"https://attack.mitre.org/techniques/{_esc(tid)}/"
                attack_links.append(f'<a href="{url}" target="_blank" rel="noopener">{_esc(tid)}</a>')
            attack_str = ", ".join(attack_links) if attack_links else "—"
            _a("<tr>")
            _a(f'<td><span class="badge {badge_cls}">{_esc(sev)}</span></td>')
            _a(f"<td>{gauge}{_esc(cvss_str)}</td>")
            _a(f"<td>{_esc(f['interface'])}</td>")
            _a(f"<td>{_esc(f['component'])}</td>")
            _a(f'<td><a href="{cwe_url}" target="_blank" rel="noopener">{_esc(cwe)}</a></td>')
            _a(f"<td>{attack_str}</td>")
            _a(f"<td>{_esc(f['description'])}</td>")
            _a("</tr>")
        _a("</tbody>")
        _a("</table>")
    else:
        _a('<p style="color: var(--text-mid);">No exposed debug interfaces detected.</p>')

    if findings:
        _a("<h3>Pinout Diagrams</h3>")
        _a('<p style="color: var(--text-mid); font-size: 0.85em; margin-bottom: 1em;">'
           "Annotated header close-ups with pin assignments and probe wiring guides. "
           "Click to expand.</p>")
        try:
            from retrace.export.pinout_diagram import generate_pinout_svg
            for f in findings:
                iface = f["interface"]
                comp_id = f.get("component", "")
                comp = next((c for c in result.components if c.id == comp_id), None)
                finding_dict = {
                    "type": "debug_interface",
                    "interface": iface,
                    "component_id": comp_id,
                    "cvss_base": f.get("cvss_base"),
                }
                svg_content = generate_pinout_svg(result, finding_dict, width=720)
                b64_svg = __import__("base64").b64encode(
                    svg_content.encode("utf-8")).decode("ascii")
                comp_label = comp.marking if comp else comp_id
                _a('<details style="margin-bottom: 1em;">')
                _a(f'<summary style="cursor: pointer; color: var(--accent); '
                   f'font-weight: bold;">{_esc(iface)} — {_esc(comp_label)}</summary>')
                _a(f'<img src="data:image/svg+xml;base64,{b64_svg}" '
                   f'alt="{_esc(iface)} pinout" style="width: 100%; max-width: 720px; '
                   f'margin-top: 0.5em; border-radius: 8px;"/>')
                _a("</details>")
        except Exception:
            pass

    # Attack chain visualization
    if attack_paths:
        _a("<h3>Attack Chains</h3>")
        _a(_attack_chain_svg(attack_paths))

    _a("</section>")

    # ── 4b. Component Intelligence ─────────────────────────────────
    _intel_components = []
    try:
        from retrace.identification.matcher import _LOOKUP
        for comp in result.components:
            if not comp.part_number:
                continue
            entry = _LOOKUP.get(comp.part_number.upper())
            if entry and entry.get("security_intel"):
                _intel_components.append((comp, entry))
    except Exception:
        pass

    if _intel_components:
        _a(_sec_heading("sec-intel", "Component Intelligence"))
        _a('<p style="color: var(--text-mid); font-size: 0.85em; margin-bottom: 1em;">'
           "Security-relevant specifications extracted from component datasheets. "
           "Debug interfaces, boot mode pins, readout protection, and flash dump commands.</p>")
        _a('<div class="intel-grid">')
        _highlight_keys = {"debug_interfaces", "readout_protection", "boot_mode_pins",
                           "write_protect_pin", "flashrom_support", "debug_relevance",
                           "config_interface", "attestation", "certification"}
        for comp, entry in _intel_components:
            intel = entry["security_intel"]
            cat = entry.get("category", "")
            part = entry.get("part", comp.part_number)
            ds_url = entry.get("datasheet", "")
            _a('<div class="intel-card">')
            part_link = f'<a href="{_esc(ds_url)}" target="_blank" rel="noopener">{_esc(part)}</a>' if ds_url and _safe_url(ds_url) else _esc(part)
            _a(f'<h3>{part_link} <span class="intel-cat">{_esc(cat)}</span></h3>')
            _a('<table class="intel-table">')
            for k, v in intel.items():
                display_key = k.replace("_", " ").title()
                highlight = "intel-highlight" if k in _highlight_keys else ""
                if isinstance(v, list):
                    val_str = ", ".join(str(x) for x in v)
                elif isinstance(v, bool):
                    val_str = "Yes" if v else "No"
                else:
                    val_str = str(v)
                td_class = f' class="{highlight}"' if highlight else ""
                _a(f"<tr><td>{_esc(display_key)}</td><td{td_class}>{_esc(val_str)}</td></tr>")
            _a("</table>")
            try:
                from retrace.export.pinout_diagram import generate_ic_pinout_svg
                ic_svg = generate_ic_pinout_svg(comp, width=560)
                if ic_svg:
                    b64 = __import__("base64").b64encode(ic_svg.encode("utf-8")).decode("ascii")
                    _a('<details style="margin-top: 8px;">')
                    _a('<summary style="cursor: pointer; color: var(--accent); '
                       'font-size: 11px;">IC Pinout Diagram</summary>')
                    _a(f'<img src="data:image/svg+xml;base64,{b64}" '
                       f'alt="{_esc(part)} pinout" style="width: 100%; max-width: 560px; '
                       f'margin-top: 0.5em; border-radius: 6px;"/>')
                    _a("</details>")
            except Exception:
                pass
            _a("</div>")
        _a("</div>")
        _a("</section>")

    # ── 4. Component Inventory (BOM) ────────────────────────────────
    _a(_sec_heading("sec-bom", "Component Inventory"))
    if result.components:
        bom_cols = [
            ("Ref", True),
            ("Type", True),
            ("Part Number", True),
            ("Marking", True),
            ("Value", True),
            ("Package", True),
            ("Datasheet", False),
            ("Confidence", True),
        ]
        _a("<table>")
        _a("<thead><tr>")
        for col_name, sortable in bom_cols:
            if sortable:
                _a(f'<th data-sortable>{col_name}<span class="sort-arrow"></span></th>')
            else:
                _a(f"<th>{col_name}</th>")
        _a("</tr></thead>")
        _a("<tbody>")

        sorted_comps = sorted(result.components, key=lambda c: c.id)
        for comp in sorted_comps:
            label_color = _LABEL_COLORS.get(comp.label, "#6b7280")
            conf = comp.confidence
            if conf > 0.9:
                conf_color = "#22c55e"
            elif conf > 0.7:
                conf_color = "#f59e0b"
            else:
                conf_color = "#ef4444"
            conf_pct = int(conf * 100)

            ds_url = _safe_url(comp.datasheet_url)

            _a("<tr>")
            _a(f"<td>{_esc(comp.id)}</td>")
            _a(f'<td><span class="type-badge" style="background:rgba({_hex_to_rgb_str(label_color)},0.15);color:{label_color};border:1px solid rgba({_hex_to_rgb_str(label_color)},0.3);">{_esc(_pretty_type(comp.label))}</span></td>')
            # Part number
            pn = comp.part_number
            if pn and ds_url:
                _a(f'<td><a href="{_esc(ds_url)}" target="_blank" rel="noopener">{_esc(pn)}</a></td>')
            elif pn:
                _a(f"<td>{_esc(pn)}</td>")
            else:
                _a('<td style="color:var(--text-lo);">—</td>')
            _a(f"<td>{_esc(comp.marking)}</td>")
            _a(f"<td>{_esc(comp.value)}</td>")
            _a(f"<td>{_esc(comp.package)}</td>")
            # Datasheet column (separate from part number link)
            if ds_url:
                _a(f'<td><a href="{_esc(ds_url)}" target="_blank" rel="noopener">PDF</a></td>')
            else:
                _a('<td style="color:var(--text-lo);">—</td>')
            # Confidence bar
            _a(f'<td data-sort-value="{conf:.4f}">'
               f'<div class="conf-bar">'
               f'<div class="conf-bar-track"><div class="conf-bar-fill" style="width:{conf_pct}%;background:{conf_color};"></div></div>'
               f'<span class="conf-bar-text">{conf_pct}%</span>'
               f'</div></td>')
            _a("</tr>")

        _a("</tbody>")
        _a("</table>")
        _a(f'<div class="table-footer">{len(result.components)} component{"s" if len(result.components) != 1 else ""}</div>')
    else:
        _a('<p style="color: var(--text-mid);">No components detected.</p>')
    _a("</section>")

    # ── 5. Functional Zones ─────────────────────────────────────────
    if zones:
        _a(_sec_heading("sec-zones", "Functional Zones"))
        _a('<div class="zone-grid">')
        for zone_name, zone_type, zone_comps in zones:
            _a('<div class="zone-card">')
            _a(f"<h3>{_esc(zone_name)}</h3>")
            _a(f'<div class="zone-type">{_esc(zone_type)} &middot; {len(zone_comps)} component{"s" if len(zone_comps) != 1 else ""}</div>')
            if zone_comps:
                _a("<details><summary>Show components</summary>")
                _a(f'<div class="zone-components">{", ".join(_esc(c) for c in zone_comps)}</div>')
                _a("</details>")
            _a("</div>")
        _a("</div>")
        _a("</section>")

    # ── 6. Trace Analysis ───────────────────────────────────────────
    _a(_sec_heading("sec-traces", "Trace Analysis"))
    if result.traces:
        connected = sum(1 for t in result.traces if t.from_component or t.to_component)
        _a(f'<p style="color:var(--text-mid);margin-bottom:16px;">'
           f"{len(result.traces)} trace{'s' if len(result.traces) != 1 else ''}, "
           f"{connected} with connected endpoints.</p>")

        comp_map = {c.id: c for c in result.components}
        net_counts: Counter[str] = Counter()
        for trace in result.traces:
            net_type = _classify_net(trace, comp_map)
            net_counts[net_type] += 1

        if net_counts:
            _a('<div class="net-grid">')
            for net_type in ("power", "data", "debug", "clock", "signal", "ground", "unknown"):
                count = net_counts.get(net_type, 0)
                if count:
                    color = _NET_COLORS.get(net_type, "#6b7280")
                    _a(f'<div class="net-chip">'
                       f'<span class="net-dot" style="background:{color};"></span>'
                       f'<span class="net-count">{count}</span>'
                       f'<span class="net-label">{net_type}</span>'
                       f'</div>')
            _a("</div>")
    else:
        _a('<p style="color: var(--text-mid);">No traces detected.</p>')
    _a("</section>")

    # ── 7. Footer ───────────────────────────────────────────────────
    _a('<footer class="report-footer">')
    _a(f"Generated by re:trace v{_esc(__version__)} &middot; {_esc(timestamp)}")
    _a('<br>')
    _a('<a href="https://github.com/ericrihm/retrace" target="_blank" rel="noopener">github.com/ericrihm/retrace</a>')
    _a("</footer>")

    _a("</div>")  # .container
    _a('<button class="back-to-top" aria-label="Back to top">&#9650;</button>')
    _a(f"<script>{_JS}</script>")
    _a("</body>")
    _a("</html>")

    return "\n".join(parts)


def save_html_report(
    result: AnalysisResult,
    output_path: str,
    **kwargs: object,
) -> None:
    """Generate and write an HTML report to disk.

    Args:
        result: Completed AnalysisResult from Pipeline.run().
        output_path: Destination file path.
        **kwargs: Forwarded to :func:`generate_html_report`.
    """
    from pathlib import Path

    html_content = generate_html_report(result, **kwargs)  # type: ignore[arg-type]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html_content, encoding="utf-8")


def _hex_to_rgb_str(hex_color: str) -> str:
    """Convert '#rrggbb' to 'r,g,b' for use in rgba()."""
    h = hex_color.lstrip("#")
    return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"
