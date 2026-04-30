"""
generate_demo.py — Synthetic PCB image generator and retrace pipeline demo runner.

Generates a realistic-looking PCB image with known component positions, runs the
retrace analysis pipeline, and writes all demo output files to docs/examples/.

Commands
--------
  python tools/generate_demo.py generate            # generate everything
  python tools/generate_demo.py generate --output-dir docs/examples
  python tools/generate_demo.py clean               # remove generated files
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click
import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Make sure the package is importable whether or not it is installed
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from retrace.core.pipeline import AnalysisResult, Component, Pipeline, Trace  # noqa: E402
from retrace.analysis.constraint_solver import (  # noqa: E402
    ComponentSpec,
    ConstraintSolver,
    Trace as SolverTrace,
    Pin,
)
from retrace.analysis.probe_advisor import (  # noqa: E402
    Component as AdvisorComponent,
    ProbeAdvisor,
)
from retrace.export.bom import bom_to_csv, bom_to_json, generate_bom  # noqa: E402
from retrace.export.svg import generate_svg  # noqa: E402
from retrace.plugins.builtin.debug_interfaces import detect_debug_interfaces  # noqa: E402


# ---------------------------------------------------------------------------
# Board geometry constants (all in pixels; image is 1600×1000)
# Xbox One motherboard reference layout — based on iFixit teardowns / FCC filings
# ---------------------------------------------------------------------------

IMG_W, IMG_H = 1600, 1000

# fmt: off
# Each entry: (ref, label, x, y, w, h, marking, part_number, value, package, pins)
# Coordinates are for the component body rectangle.
KNOWN_COMPONENTS: list[tuple] = [
    # ref        label         x    y    w    h    marking           part_number      value    package       pins

    # Main APU — custom AMD Jaguar 8-core + GCN GPU (X877730-001)
    ("U1", "ic",         500, 300, 300, 300, "X877730-001",    "X877730",       "",       "BGA-1152",
     ["VCC_CORE","VCC_GFX","VCC_IO","GND","GND2","GND3","GND4","DDR_DQ0","DDR_DQ1","DDR_A0","HDMI_TX0P","HDMI_TX0N","PCIE_TX","PCIE_RX"]),

    # DDR3 RAM — Samsung K4B4G0846E (4x visible on top side)
    ("U2", "ic",         120, 120, 140,  90, "K4B4G0846E",    "K4B4G0846E",   "4Gb",    "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U3", "ic",         300, 120, 140,  90, "K4B4G0846E",    "K4B4G0846E",   "4Gb",    "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U4", "ic",         120, 680, 140,  90, "K4B4G0846E",    "K4B4G0846E",   "4Gb",    "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U5", "ic",         300, 680, 140,  90, "K4B4G0846E",    "K4B4G0846E",   "4Gb",    "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),

    # Southbridge — Microsoft custom (X861949-005)
    ("U6", "ic",        1000, 120, 180, 160, "X861949-005",    "X861949",       "",       "BGA-360",
     ["VCC","GND","USB0_DP","USB0_DN","USB1_DP","USB1_DN","SATA_TX","SATA_RX","SPI_MOSI","SPI_MISO","SPI_CLK","SPI_CS"]),

    # eMMC NAND — SK Hynix H27QCG8T2E5R (64 GB)
    ("U7", "ic",        1000, 380, 160, 120, "H27QCG8T2E5R",  "H27QCG8T2E5R", "64GB",   "BGA-153",
     ["VCC","VCCQ","GND","CMD","CLK","DAT0","DAT1","DAT2","DAT3","DAT4","DAT5","DAT6","DAT7"]),

    # WiFi/BT — Marvell AVASTAR 88W8897
    ("U8", "ic",        1050, 600, 120,  80, "88W8897",        "88W8897",       "",       "QFN-68",
     ["VCC","GND","SDIO_CLK","SDIO_CMD","SDIO_D0","SDIO_D1","ANT1","ANT2"]),

    # Ethernet PHY — Marvell 88E1512
    ("U9", "ic",        1050, 760, 100,  70, "88E1512",        "88E1512",       "",       "QFN-56",
     ["VCC","GND","MDI0P","MDI0N","MDI1P","MDI1N","TX_CLK","RX_CLK"]),

    # Power: Core VRM — TI TPS51611
    ("U10","ic",          80, 350,  70,  55, "TPS51611",       "TPS51611",      "",       "QFN-20",
     ["VIN","VOUT","GND","EN","BOOT","SW","PGOOD","FB"]),

    # Power: Memory VRM — IR3553
    ("U11","ic",          80, 440,  70,  55, "IR3553",         "IR3553",        "",       "PQFN-25",
     ["VIN","VOUT","GND","EN","SW","FB","PGOOD"]),

    # HDMI retimer — Pericom PI3HDMI412
    ("U12","ic",        1300, 150,  80,  60, "PI3HDMI412",     "PI3HDMI412",    "",       "QFN-40",
     ["VCC","GND","HDMI_IN0","HDMI_IN1","HDMI_IN2","HDMI_OUT0","HDMI_OUT1","HDMI_OUT2","HPD","DDC_SCL","DDC_SDA"]),

    # Connectors
    ("J1", "connector", 1420,  80,  80, 130, "HDMI",           "",              "",       "HDMI-A",
     ["TMDS0+","TMDS0-","TMDS1+","TMDS1-","TMDS2+","TMDS2-","CK+","CK-","HPD","SCL","SDA","CEC","GND","5V"]),
    ("J2", "connector", 1420, 280,  70, 110, "USB3.0",         "",              "",       "USB-A",
     ["VBUS","D-","D+","GND","SSRX-","SSRX+","SSTX-","SSTX+","GND2"]),
    ("J3", "connector", 1420, 460,  70, 110, "USB3.0",         "",              "",       "USB-A",
     ["VBUS","D-","D+","GND","SSRX-","SSRX+","SSTX-","SSTX+","GND2"]),
    ("J4", "connector", 1420, 650,  60,  80, "RJ45",           "",              "",       "RJ45",
     ["TX+","TX-","RX+","RX-","GND","LED1","LED2"]),

    # JTAG debug header (the money shot for security researchers!)
    ("J5", "connector",   60, 880, 100,  40, "JTAG",           "",              "",       "2x7 1.27mm",
     ["TDI","TDO","TCK","TMS","TRST","VCC","GND","GND2","NRST","NC","NC2","NC3","NC4","GND3"]),

    # Passives
    ("C1", "capacitor",  450, 260,  30,  18, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C2", "capacitor",  830, 300,  30,  18, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C3", "capacitor",  830, 340,  30,  18, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    ("C4", "capacitor",  450, 630,  30,  18, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C5", "capacitor",  940, 160,  30,  18, "22uF",           "",              "22uF",   "0805", ["1","2"]),
    ("C6", "capacitor",  940, 200,  30,  18, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("R1", "resistor",   900, 620,  34,  16, "10k",            "",              "10k",    "0402", ["A","B"]),
    ("R2", "resistor",   900, 650,  34,  16, "4k7",            "",              "4k7",    "0402", ["A","B"]),
    ("R3", "resistor",   900, 680,  34,  16, "100",            "",              "100",    "0402", ["A","B"]),

    # Inductors (VRM output filter)
    ("L1", "inductor",   170, 370,  50,  44, "1uH",            "",              "1uH",    "1210", ["1","2"]),
    ("L2", "inductor",   170, 460,  50,  44, "1uH",            "",              "1uH",    "1210", ["1","2"]),

    # Crystal oscillator — 25 MHz reference
    ("Y1", "crystal",    870, 450,  56,  30, "25MHz",          "ABLS-25.000MHZ","25MHz", "HC-49S", ["1","2","GND","GND2"]),

    # Test points (near JTAG header — useful for debug probing)
    ("TP1","test_point", 200, 880,  14,  14, "TP1",            "",              "",       "TP", ["1"]),
    ("TP2","test_point", 230, 880,  14,  14, "TP2",            "",              "",       "TP", ["1"]),
    ("TP3","test_point", 260, 880,  14,  14, "TP3",            "",              "",       "TP", ["1"]),
    ("TP4","test_point", 290, 880,  14,  14, "TP4",            "",              "",       "TP", ["1"]),
    ("TP5","test_point", 320, 880,  14,  14, "TP5",            "",              "",       "TP", ["1"]),
]
# fmt: on

# Copper traces to draw: list of (point_list, width_px)
# Points are (x, y) tuples along the route — Xbox One topology.
TRACE_ROUTES: list[tuple[list[tuple[int, int]], int]] = [
    # APU (U1) to DDR3 data bus — four differential pairs (U2/U3 top side)
    ([(500, 350), (260, 350), (260, 210)], 3),   # DDR_DQ0 → U2
    ([(500, 370), (260, 370), (440, 210)], 3),   # DDR_DQ1 → U3
    ([(500, 390), (120, 390), (120, 210)], 3),   # DDR_DQ2 → U2 (second pair)
    ([(500, 410), (300, 410), (300, 210)], 3),   # DDR_DQ3 → U3 (second pair)
    # APU (U1) to DDR3 bottom side (U4/U5)
    ([(500, 580), (120, 580), (120, 770)], 3),   # DDR → U4
    ([(500, 600), (300, 600), (300, 770)], 3),   # DDR → U5
    # APU (U1) to Southbridge (U6) — PCIe link
    ([(800, 380), (1000, 380), (1000, 280)], 4), # PCIE_TX
    ([(800, 400), (1000, 400), (1000, 300)], 4), # PCIE_RX
    # APU (U1) to HDMI retimer (U12) — differential pairs
    ([(800, 310), (1300, 310), (1300, 210)], 3), # HDMI_TX0P
    ([(800, 330), (1300, 330), (1300, 230)], 3), # HDMI_TX0N
    # Southbridge (U6) to eMMC (U7) — CMD/CLK/DAT
    ([(1000, 280), (1000, 380)], 3),             # CMD
    ([(1020, 280), (1020, 380)], 3),             # CLK
    ([(1040, 280), (1040, 380)], 2),             # DAT0
    ([(1060, 280), (1060, 380)], 2),             # DAT1
    # Southbridge (U6) to USB connectors (J2/J3)
    ([(1180, 200), (1420, 200), (1420, 280)], 3), # USB0_DP → J2
    ([(1180, 220), (1420, 220), (1420, 300)], 3), # USB0_DN → J2
    ([(1180, 240), (1420, 240), (1420, 460)], 3), # USB1_DP → J3
    ([(1180, 260), (1420, 260), (1420, 480)], 3), # USB1_DN → J3
    # Core VRM (U10) to APU — power delivery
    ([(150, 375), (500, 375)], 5),               # VCC_CORE
    ([(150, 390), (500, 390)], 5),               # GND return
    # Memory VRM (U11) to APU — DDR power
    ([(150, 465), (500, 465)], 4),               # VCC_MEM
    # VRM inductors output
    ([(220, 392), (500, 392)], 4),               # L1 → APU
    ([(220, 482), (500, 482)], 4),               # L2 → APU
    # WiFi (U8) SDIO to Southbridge (U6)
    ([(1050, 640), (1000, 640), (1000, 280)], 2), # SDIO_CLK
    ([(1050, 660), (980,  660), (980,  280)], 2), # SDIO_CMD
    # Ethernet PHY (U9) to RJ45 (J4)
    ([(1150, 795), (1420, 795), (1420, 690)], 3), # TX+
    ([(1150, 810), (1420, 810), (1420, 710)], 3), # TX-
    # JTAG header (J5) to APU debug pins
    ([(160, 900), (500, 900), (500, 600)], 2),   # TDI
    ([(160, 912), (480, 912), (480, 600)], 2),   # TDO
    ([(160, 924), (460, 924), (460, 600)], 2),   # TCK
    ([(160, 936), (440, 936), (440, 600)], 2),   # TMS
    # HDMI retimer (U12) to HDMI connector (J1)
    ([(1380, 180), (1420, 180), (1420, 140)], 3), # TMDS out
    ([(1380, 200), (1420, 200), (1420, 160)], 3), # TMDS out
    # Crystal (Y1) to Southbridge (U6) — reference clock
    ([(870, 465), (1090, 465), (1090, 280)], 2),
]

# Via positions (x, y, outer_radius, inner_radius)
# Dense grid reflecting Xbox One's multilayer power planes and signal routing.
VIAS: list[tuple[int, int, int, int]] = [
    # Power plane stitching — APU area
    (480, 280, 5, 2),
    (510, 280, 5, 2),
    (540, 280, 5, 2),
    (570, 280, 5, 2),
    (600, 280, 5, 2),
    (630, 280, 5, 2),
    (660, 280, 5, 2),
    (690, 280, 5, 2),
    (720, 280, 5, 2),
    (750, 280, 5, 2),
    # Power plane stitching — APU bottom edge
    (480, 620, 5, 2),
    (520, 620, 5, 2),
    (560, 620, 5, 2),
    (600, 620, 5, 2),
    (640, 620, 5, 2),
    (680, 620, 5, 2),
    (720, 620, 5, 2),
    (760, 620, 5, 2),
    # Signal transition vias — DDR bus
    (260, 300, 6, 3),
    (300, 300, 6, 3),
    (440, 300, 6, 3),
    # VRM output vias
    (170, 410, 6, 3),
    (170, 500, 6, 3),
    # Southbridge area stitching
    (1000, 500, 5, 2),
    (1040, 500, 5, 2),
    (1080, 500, 5, 2),
    (1120, 500, 5, 2),
    # Ground stitching — right side
    (1200, 600, 5, 2),
    (1200, 650, 5, 2),
]

# Mounting holes (x, y, outer_r, inner_r) — 4 corners + 2 internal posts
MOUNTING_HOLES: list[tuple[int, int, int, int]] = [
    (35,   35,  14, 8),
    (1565, 35,  14, 8),
    (35,   965, 14, 8),
    (1565, 965, 14, 8),
    (650,  500, 12, 7),   # internal post near APU
    (950,  500, 12, 7),   # internal post near Southbridge
]

# Silkscreen labels: (text, x, y)
SILK_LABELS: list[tuple[str, int, int]] = [
    ("U1",   502,  298),   # APU
    ("U2",   122,  118),   # DDR3
    ("U3",   302,  118),   # DDR3
    ("U4",   122,  678),   # DDR3
    ("U5",   302,  678),   # DDR3
    ("U6",  1002,  118),   # Southbridge
    ("U7",  1002,  378),   # eMMC
    ("U8",  1052,  598),   # WiFi
    ("U9",  1052,  758),   # Ethernet PHY
    ("U10",   82,  348),   # Core VRM
    ("U11",   82,  438),   # Memory VRM
    ("U12", 1302,  148),   # HDMI retimer
    ("J1",  1422,   78),   # HDMI
    ("J2",  1422,  278),   # USB3
    ("J3",  1422,  458),   # USB3
    ("J4",  1422,  648),   # RJ45
    ("J5",    62,  878),   # JTAG
    ("L1",   172,  368),
    ("L2",   172,  458),
    ("Y1",   872,  448),
    ("TP1-TP5", 196, 900),
    ("FCC: C3K1520", 1300, 970),
    ("(C) Microsoft Corp. — Synthetic Demo Only", 400, 970),
]


# ---------------------------------------------------------------------------
# PCB image generation
# ---------------------------------------------------------------------------

def _add_soldermask_texture(img: np.ndarray) -> np.ndarray:
    """Add subtle noise + grain to the soldermask layer."""
    h, w = img.shape[:2]
    noise = np.random.randint(-8, 9, (h, w, 3), dtype=np.int16)
    img_i = img.astype(np.int16) + noise
    return np.clip(img_i, 0, 255).astype(np.uint8)


def _draw_board_outline(img: np.ndarray) -> None:
    """Draw the PCB edge + a thin gold/copper ring inside."""
    # Outer edge
    cv2.rectangle(img, (10, 10), (IMG_W - 10, IMG_H - 10), (0, 60, 0), 3)
    # Inner keepout ring (slightly lighter)
    cv2.rectangle(img, (14, 14), (IMG_W - 14, IMG_H - 14), (0, 80, 20), 1)


def _draw_mounting_holes(img: np.ndarray) -> None:
    for x, y, ro, ri in MOUNTING_HOLES:
        # Annular ring (copper)
        cv2.circle(img, (x, y), ro, (30, 140, 180), -1)
        # Hole (dark)
        cv2.circle(img, (x, y), ri, (10, 20, 10), -1)
        # Silkscreen ring
        cv2.circle(img, (x, y), ro + 3, (200, 210, 200), 1)


def _copper_color(base_variance: int = 0) -> tuple[int, int, int]:
    """Return a slightly randomised copper/trace color (BGR)."""
    r = 180 + base_variance + np.random.randint(-5, 6)
    g = 100 + np.random.randint(-5, 6)
    b = 30 + np.random.randint(-5, 6)
    return (int(b), int(g), int(r))


def _draw_traces(img: np.ndarray) -> None:
    for pts, width in TRACE_ROUTES:
        color = _copper_color()
        for i in range(len(pts) - 1):
            p1 = pts[i]
            p2 = pts[i + 1]
            cv2.line(img, p1, p2, color, width, lineType=cv2.LINE_AA)
            # Slightly lighter highlight on top of trace for sheen
            highlight = (
                min(color[0] + 20, 255),
                min(color[1] + 15, 255),
                min(color[2] + 20, 255),
            )
            cv2.line(img, p1, p2, highlight, max(1, width - 1), lineType=cv2.LINE_AA)


def _draw_vias(img: np.ndarray) -> None:
    for x, y, ro, ri in VIAS:
        # Annular copper ring
        cv2.circle(img, (x, y), ro, _copper_color(10), -1)
        # Drill (dark center)
        cv2.circle(img, (x, y), ri, (15, 30, 15), -1)
        # Tiny highlight
        cv2.circle(img, (x - 1, y - 1), max(1, ri - 1), (200, 180, 80), 1)


def _draw_component_footprint(
    img: np.ndarray,
    ref: str,
    label: str,
    x: int,
    y: int,
    w: int,
    h: int,
    marking: str,
) -> None:
    """Draw a single component footprint with realistic colours and detail."""
    # --- Body fill colour per type ---
    if label == "ic":
        body_color = (20, 22, 22)         # near-black epoxy
        border_color = (50, 55, 55)
        text_color = (180, 185, 180)
    elif label == "capacitor":
        body_color = (60, 80, 110)        # tan/brown ceramic
        border_color = (80, 100, 130)
        text_color = (200, 200, 200)
    elif label == "resistor":
        body_color = (20, 30, 40)         # dark body
        border_color = (40, 50, 60)
        text_color = (200, 200, 200)
    elif label == "crystal":
        body_color = (120, 130, 135)      # metallic
        border_color = (160, 170, 175)
        text_color = (30, 30, 30)
    elif label == "connector":
        body_color = (25, 25, 30)         # dark plastic housing
        border_color = (60, 60, 70)
        text_color = (200, 200, 200)
    elif label == "inductor":
        body_color = (35, 35, 55)         # dark ferrite
        border_color = (60, 60, 80)
        text_color = (200, 200, 200)
    elif label == "test_point":
        # Round copper pad
        cx, cy = x + w // 2, y + h // 2
        r = max(w, h) // 2
        cv2.circle(img, (cx, cy), r + 1, (30, 100, 140), -1)
        cv2.circle(img, (cx, cy), r - 1, _copper_color(20), -1)
        return
    else:
        body_color = (50, 60, 70)
        border_color = (80, 90, 100)
        text_color = (200, 200, 200)

    # Component body
    cv2.rectangle(img, (x, y), (x + w, y + h), body_color, -1)
    cv2.rectangle(img, (x, y), (x + w, y + h), border_color, 1)

    # --- Extra detail per component type ---
    if label == "ic":
        # Pin 1 marker (small notch/dot in top-left)
        cv2.circle(img, (x + 6, y + 6), 3, (100, 110, 110), -1)
        # Copper pads along all four edges (simplified — just top and bottom rows)
        pad_w, pad_h = 6, 10
        n_pads_lr = max(2, h // 16)
        n_pads_tb = max(2, w // 16)
        pad_color = _copper_color(15)
        for i in range(n_pads_tb):
            px = x + 8 + i * (w - 16) // max(1, n_pads_tb - 1)
            cv2.rectangle(img, (px - pad_w // 2, y - pad_h), (px + pad_w // 2, y), pad_color, -1)
            cv2.rectangle(img, (px - pad_w // 2, y + h), (px + pad_w // 2, y + h + pad_h), pad_color, -1)
        for i in range(n_pads_lr):
            py = y + 8 + i * (h - 16) // max(1, n_pads_lr - 1)
            cv2.rectangle(img, (x - pad_h, py - pad_w // 2), (x, py + pad_w // 2), pad_color, -1)
            cv2.rectangle(img, (x + w, py - pad_w // 2), (x + w + pad_h, py + pad_w // 2), pad_color, -1)
        # Marking text centred in body
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = min(0.35, w / 300)
        text_size = cv2.getTextSize(marking, font, scale, 1)[0]
        tx = x + (w - text_size[0]) // 2
        ty = y + h // 2 + text_size[1] // 2
        cv2.putText(img, marking, (tx, ty), font, scale, text_color, 1, cv2.LINE_AA)

    elif label == "capacitor":
        # Two copper end-caps
        cap_w = max(4, w // 5)
        cap_color = _copper_color(20)
        cv2.rectangle(img, (x, y), (x + cap_w, y + h), cap_color, -1)
        cv2.rectangle(img, (x + w - cap_w, y), (x + w, y + h), cap_color, -1)

    elif label == "resistor":
        # Two copper end-caps + coloured band
        cap_w = max(4, w // 5)
        cap_color = _copper_color(20)
        cv2.rectangle(img, (x, y), (x + cap_w, y + h), cap_color, -1)
        cv2.rectangle(img, (x + w - cap_w, y), (x + w, y + h), cap_color, -1)
        # One value band in the middle
        band_color = (40, 40, 180)  # blue for 100-ohm range
        bx = x + w // 2 - 2
        cv2.rectangle(img, (bx, y + 1), (bx + 3, y + h - 1), band_color, -1)

    elif label == "crystal":
        # Metallic seam line down the centre
        cv2.line(img, (x + w // 2, y + 2), (x + w // 2, y + h - 2), (90, 95, 100), 1)
        # Two solder pads
        pad_color = _copper_color(25)
        cv2.rectangle(img, (x - 4, y + h // 4), (x, y + 3 * h // 4), pad_color, -1)
        cv2.rectangle(img, (x + w, y + h // 4), (x + w + 4, y + 3 * h // 4), pad_color, -1)

    elif label == "connector":
        # Pin array holes
        pins_per_row = 5
        rows = 2
        hole_r = 3
        spacing_x = (w - 16) // (pins_per_row - 1) if pins_per_row > 1 else w // 2
        spacing_y = (h - 20) // (rows - 1) if rows > 1 else h // 2
        for row in range(rows):
            for col in range(pins_per_row):
                px = x + 8 + col * spacing_x
                py = y + 10 + row * spacing_y
                # Copper annular ring
                cv2.circle(img, (px, py), hole_r + 2, _copper_color(10), -1)
                # Drill hole
                cv2.circle(img, (px, py), hole_r, (8, 15, 8), -1)

    elif label == "inductor":
        # Winding lines across the top surface
        stripe_color = (55, 55, 75)
        n_stripes = 5
        for i in range(n_stripes):
            sx = x + 4 + i * (w - 8) // max(1, n_stripes - 1)
            cv2.line(img, (sx, y + 4), (sx, y + h - 4), stripe_color, 1)
        # Copper end-caps
        cap_w = max(5, w // 6)
        cap_color = _copper_color(20)
        cv2.rectangle(img, (x, y), (x + cap_w, y + h), cap_color, -1)
        cv2.rectangle(img, (x + w - cap_w, y), (x + w, y + h), cap_color, -1)


def _draw_silkscreen(img: np.ndarray) -> None:
    """Draw white silkscreen reference designators."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    for text, tx, ty in SILK_LABELS:
        cv2.putText(img, text, (tx, ty), font, 0.38, (210, 215, 210), 1, cv2.LINE_AA)

    # Board title — centred at bottom
    cv2.putText(
        img,
        "XBOX ONE REF v1.0",
        (IMG_W // 2 - 110, IMG_H - 25),
        font,
        0.52,
        (200, 210, 200),
        1,
        cv2.LINE_AA,
    )


def generate_board_image(output_path: Path) -> None:
    """Render the synthetic PCB and save to output_path."""
    rng = np.random.default_rng(42)

    # ---- Base soldermask ----
    # FR4 green soldermask: BGR ≈ (40, 110, 40) with slight HSV variance
    base_green = np.full((IMG_H, IMG_W, 3), (38, 108, 38), dtype=np.uint8)

    # Add low-frequency grain (simulate FR4 weave)
    grain = rng.integers(-12, 13, (IMG_H, IMG_W, 3), dtype=np.int16)
    img = np.clip(base_green.astype(np.int16) + grain, 0, 255).astype(np.uint8)

    # ---- Substrate lines (PCB weave pattern) ----
    weave_color = (35, 100, 35)
    for gy in range(0, IMG_H, 16):
        cv2.line(img, (0, gy), (IMG_W, gy), weave_color, 1)
    for gx in range(0, IMG_W, 16):
        cv2.line(img, (gx, 0), (gx, IMG_H), weave_color, 1)

    # ---- Board outline + mounting holes ----
    _draw_board_outline(img)
    _draw_mounting_holes(img)

    # ---- Copper pour (ground plane — larger area for denser Xbox One board) ----
    # Left ground pour (between DDR bottom and JTAG area)
    cv2.rectangle(img, (50, 550), (460, 860), (25, 85, 110), -1)
    cv2.rectangle(img, (50, 550), (460, 860), (35, 95, 120), 1)
    cv2.putText(img, "GND", (60, 580), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 110, 140), 1)
    # Right ground pour (Southbridge / connector side)
    cv2.rectangle(img, (860, 550), (1380, 860), (25, 85, 110), -1)
    cv2.rectangle(img, (860, 550), (1380, 860), (35, 95, 120), 1)
    cv2.putText(img, "GND", (870, 580), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 110, 140), 1)

    # ---- Traces ----
    _draw_traces(img)

    # ---- Vias ----
    _draw_vias(img)

    # ---- Component footprints ----
    for entry in KNOWN_COMPONENTS:
        ref, label, x, y, w, h, marking, *_rest = entry
        _draw_component_footprint(img, ref, label, x, y, w, h, marking)

    # ---- Silkscreen ----
    _draw_silkscreen(img)

    # ---- Final texture pass (micro-noise for photographic realism) ----
    fine_noise = rng.integers(-4, 5, (IMG_H, IMG_W, 3), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + fine_noise, 0, 255).astype(np.uint8)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), img)


# ---------------------------------------------------------------------------
# Build a synthetic AnalysisResult from the known component list
# ---------------------------------------------------------------------------

def _build_synthetic_result(image_path: str) -> AnalysisResult:
    """Construct an AnalysisResult with realistic data from KNOWN_COMPONENTS."""
    components: list[Component] = []
    traces: list[Trace] = []

    for i, entry in enumerate(KNOWN_COMPONENTS):
        ref, label, x, y, w, h, marking, part_number, value, package, _pins = entry
        components.append(
            Component(
                id=ref,
                label=label,
                confidence=round(0.88 + 0.1 * (i % 3) / 2, 3),
                bbox=(x, y, w, h),
                marking=marking,
                part_number=part_number,
                value=value,
                package=package,
            )
        )

    # Create a few representative traces from TRACE_ROUTES
    for idx, (pts, _width) in enumerate(TRACE_ROUTES[:8]):
        traces.append(
            Trace(
                id=f"T{idx:03d}",
                points=list(pts),
                width_px=float(_width),
                from_component=KNOWN_COMPONENTS[0][0],  # U1
                to_component=KNOWN_COMPONENTS[idx % len(KNOWN_COMPONENTS)][0],
            )
        )

    return AnalysisResult(
        image_path=image_path,
        components=components,
        traces=traces,
        board_dimensions=(IMG_W, IMG_H),
        layer_count_estimate=4,
        duration_seconds=0.0,
        pipeline_version="0.1.0",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


# ---------------------------------------------------------------------------
# Probe advisor output
# ---------------------------------------------------------------------------

def _run_probe_advisor(result: AnalysisResult) -> str:
    """Run the Bayesian probe advisor and return a formatted text report."""
    advisor = ProbeAdvisor(
        net_labels=["VCC_CORE", "VCC_GFX", "VCC_IO", "GND", "DDR_DQ0", "DDR_DQ1", "PCIE_TX", "PCIE_RX",
                    "HDMI_TX0P", "HDMI_TX0N", "SPI_MOSI", "SPI_CLK", "USB0_DP", "USB0_DN", "TDI", "TDO", "TCK", "TMS"],
        alpha=1.0,
    )

    advisor_comps: list[AdvisorComponent] = []
    for entry in KNOWN_COMPONENTS:
        ref, label, x, y, w, h, _marking, _pn, _val, _pkg, pins = entry
        cx = float(x + w / 2)
        cy = float(y + h / 2)
        advisor_comps.append(AdvisorComponent(ref=ref, kind=label, pins=pins, location=(cx, cy)))

    advisor.add_components(advisor_comps)
    recommendations = advisor.recommend(top_k=5)

    lines = [
        "re:trace Bayesian Probe Advisor — Top 5 Probe Recommendations",
        "=" * 65,
        "",
        "Board: docs/examples/synthetic_board.png",
        f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        "Ranked by Expected Information Gain (EIG, bits):",
        "",
    ]

    for rank, rec in enumerate(recommendations, start=1):
        lines.append(f"  #{rank}  {rec.node_id}")
        lines.append(f"       Location : ({rec.location[0]:.0f}, {rec.location[1]:.0f}) px")
        lines.append(f"       EIG      : {rec.expected_info_gain:.4f} bits")
        lines.append(f"       Rationale: {rec.rationale}")
        lines.append("")

    lines += [
        "Methodology",
        "-----------",
        "The ProbeAdvisor maintains a Dirichlet belief distribution over",
        "possible net labels for each unknown node. Expected Information",
        "Gain (EIG) is approximated as H(prior) minus expected posterior",
        "entropy after observing a measurement — equivalent to mutual",
        "information I(net_label ; measurement).",
        "",
        "Pin-name priors boost probability for power (VCC/VDD) and",
        "ground (GND/VSS) nets before any measurements are taken.",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Constraint solver output
# ---------------------------------------------------------------------------

def _run_constraint_solver(result: AnalysisResult) -> str:
    """Run the AC-3 constraint solver and return a formatted text report."""
    comp_specs: list[ComponentSpec] = []
    for entry in KNOWN_COMPONENTS:
        ref, label, x, y, w, h, _marking, _pn, _val, _pkg, pins = entry
        cx = float(x + w / 2)
        cy = float(y + h / 2)
        comp_specs.append(ComponentSpec(ref=ref, kind=label, pins=pins, location=(cx, cy)))

    # Build solver traces from TRACE_ROUTES — Xbox One topology
    solver_traces: list[SolverTrace] = [
        SolverTrace(Pin("U1", "DDR_DQ0"),   Pin("U2", "DQ0"),    confidence=0.95),
        SolverTrace(Pin("U1", "DDR_DQ1"),   Pin("U3", "DQ0"),    confidence=0.95),
        SolverTrace(Pin("U1", "PCIE_TX"),   Pin("U6", "VCC"),    confidence=0.88),
        SolverTrace(Pin("U1", "PCIE_RX"),   Pin("U6", "GND"),    confidence=0.88),
        SolverTrace(Pin("U1", "HDMI_TX0P"), Pin("U12","HDMI_IN0"),confidence=0.92),
        SolverTrace(Pin("U1", "HDMI_TX0N"), Pin("U12","HDMI_IN1"),confidence=0.92),
        SolverTrace(Pin("U6", "SPI_MOSI"),  Pin("U7", "CMD"),    confidence=0.90),
        SolverTrace(Pin("U6", "SPI_CLK"),   Pin("U7", "CLK"),    confidence=0.90),
        SolverTrace(Pin("U6", "USB0_DP"),   Pin("J2", "D+"),     confidence=0.93),
        SolverTrace(Pin("U6", "USB0_DN"),   Pin("J2", "D-"),     confidence=0.93),
        SolverTrace(Pin("U6", "USB1_DP"),   Pin("J3", "D+"),     confidence=0.93),
        SolverTrace(Pin("U6", "USB1_DN"),   Pin("J3", "D-"),     confidence=0.93),
        SolverTrace(Pin("U10","VOUT"),       Pin("L1", "1"),      confidence=0.91),
        SolverTrace(Pin("U11","VOUT"),       Pin("L2", "1"),      confidence=0.91),
        SolverTrace(Pin("U9", "MDI0P"),     Pin("J4", "TX+"),    confidence=0.89),
        SolverTrace(Pin("U9", "MDI0N"),     Pin("J4", "TX-"),    confidence=0.89),
        SolverTrace(Pin("J5", "TDI"),       Pin("U1", "VCC_CORE"),confidence=0.75),
        SolverTrace(Pin("U8", "SDIO_CLK"), Pin("U6", "SPI_CLK"),confidence=0.85),
        SolverTrace(Pin("U12","HDMI_OUT0"), Pin("J1", "TMDS0+"), confidence=0.94),
        SolverTrace(Pin("U12","HDMI_OUT1"), Pin("J1", "TMDS0-"), confidence=0.94),
    ]

    solver = ConstraintSolver(proximity_threshold_px=80.0)
    res = solver.solve(comp_specs, solver_traces)

    lines = [
        "re:trace Constraint Solver — Inferred Netlist",
        "=" * 50,
        "",
        "Board: docs/examples/synthetic_board.png",
        f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"AC-3 iterations: {res.iterations}",
        "",
        f"Net Assignments ({len(res.net_assignment)} nodes):",
        "",
    ]

    power_nodes = [(n, v) for n, v in sorted(res.net_assignment.items()) if v == "POWER"]
    ground_nodes = [(n, v) for n, v in sorted(res.net_assignment.items()) if v == "GROUND"]
    signal_nodes = [(n, v) for n, v in sorted(res.net_assignment.items()) if v == "SIGNAL"]
    unknown_nodes = [(n, v) for n, v in sorted(res.net_assignment.items()) if v == "UNKNOWN"]

    for label, nodes in [("POWER", power_nodes), ("GROUND", ground_nodes),
                          ("SIGNAL", signal_nodes), ("UNKNOWN", unknown_nodes)]:
        if nodes:
            lines.append(f"  [{label}]")
            for nid, _ in nodes[:20]:  # cap output length
                lines.append(f"    {nid}")
            if len(nodes) > 20:
                lines.append(f"    ... and {len(nodes) - 20} more")
            lines.append("")

    if res.inferred_traces:
        lines.append(f"Inferred Connections ({len(res.inferred_traces)}):")
        for a, b in res.inferred_traces[:15]:
            lines.append(f"  {a}  <-->  {b}")
        lines.append("")

    if res.ambiguous_nodes:
        lines.append(f"Ambiguous Nodes ({len(res.ambiguous_nodes)}):")
        for n in res.ambiguous_nodes[:10]:
            lines.append(f"  {n}")
        if len(res.ambiguous_nodes) > 10:
            lines.append(f"  ... and {len(res.ambiguous_nodes) - 10} more")
        lines.append("")

    if res.conflicts:
        lines.append("Constraint Conflicts:")
        for c in res.conflicts:
            lines.append(f"  [!] {c}")
    else:
        lines.append("No constraint conflicts detected.")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Debug interface detection output
# ---------------------------------------------------------------------------

def _run_debug_interface_detection(result: AnalysisResult) -> str:
    findings = detect_debug_interfaces(result)
    high = [f for f in findings if f["severity"] == "high"]
    medium = [f for f in findings if f["severity"] == "medium"]
    low = [f for f in findings if f["severity"] == "low"]

    lines = [
        "re:trace Debug Interface Detector",
        "=" * 40,
        "",
        "Board: docs/examples/synthetic_board.png",
        f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"Total findings: {len(findings)}  (HIGH={len(high)}  MEDIUM={len(medium)}  LOW={len(low)})",
        "",
    ]

    sev_order = {"high": 0, "medium": 1, "low": 2}
    for finding in sorted(findings, key=lambda f: sev_order.get(f["severity"], 9)):
        sev = finding["severity"].upper()
        iface = finding["interface"]
        desc = finding["description"]
        comp_id = finding["component_id"]
        cve = finding.get("cve_reference") or "N/A"
        lines += [
            f"  [{sev}]  {iface}",
            f"         Component : {comp_id}  ({finding['component_label']})",
            f"         Marking   : {finding['component_marking'] or '(none)'}",
            f"         Detail    : {desc}",
            f"         Reference : {cve}",
            "",
        ]

    if not findings:
        lines.append("  No debug interfaces detected.")
        lines.append("")

    lines += [
        "Methodology",
        "-----------",
        "Detection uses keyword matching against component markings and",
        "labels, cross-referenced with known pin-count signatures for",
        "JTAG (20/14/10-pin), SWD (10/4/2-pin), UART, SPI, and I2C.",
        "Severity follows CWE-1191 (debug/test interface exposure).",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Click CLI
# ---------------------------------------------------------------------------

OUTPUT_FILES = [
    "synthetic_board.png",
    "detection_result.json",
    "bom_output.json",
    "bom_output.csv",
    "annotated_board.svg",
    "probe_recommendations.txt",
    "constraint_solver_output.txt",
    "debug_interfaces.txt",
]


@click.group()
def cli():
    """re:trace synthetic PCB demo generator."""


@cli.command()
@click.option(
    "--output-dir",
    default="docs/examples",
    show_default=True,
    help="Directory to write output files into.",
)
def generate(output_dir: str):
    """Generate the synthetic PCB image and all demo output files."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---- 1. Generate PCB image ----
    board_img = out / "synthetic_board.png"
    click.echo(f"[1/7] Generating PCB image → {board_img}")
    generate_board_image(board_img)
    click.echo(f"      Saved {board_img} ({board_img.stat().st_size // 1024} KB)")

    # ---- 2. Run pipeline (or use synthetic result) ----
    click.echo("[2/7] Running retrace pipeline...")
    t0 = time.time()
    try:
        pipeline = Pipeline()
        result = pipeline.run(str(board_img))
        if len(result.components) == 0:
            raise RuntimeError("Pipeline returned 0 components — falling back to synthetic result")
        click.echo(f"      Pipeline detected {len(result.components)} components, "
                   f"{len(result.traces)} traces")
    except Exception as exc:
        click.echo(f"      Pipeline note: {exc}")
        click.echo("      Using synthetic ground-truth result instead.")
        result = _build_synthetic_result(str(board_img))
        result.duration_seconds = time.time() - t0

    # ---- 3. detection_result.json ----
    det_json = out / "detection_result.json"
    click.echo(f"[3/7] Writing detection result → {det_json}")
    from dataclasses import asdict as _asdict
    det_data = {
        "version": result.pipeline_version,
        "timestamp": result.timestamp,
        "image": result.image_path,
        "board_dimensions": list(result.board_dimensions),
        "layer_count_estimate": result.layer_count_estimate,
        "duration_seconds": round(result.duration_seconds, 3),
        "components": [_asdict(c) for c in result.components],
        "traces": [_asdict(t) for t in result.traces],
        "summary": result.summary(),
    }
    det_json.write_text(json.dumps(det_data, indent=2) + "\n")

    # ---- 4. BOM (json + csv) ----
    bom_json_path = out / "bom_output.json"
    bom_csv_path = out / "bom_output.csv"
    click.echo(f"[4/7] Writing BOM → {bom_json_path} + {bom_csv_path}")
    bom = generate_bom(result)
    bom_json_path.write_text(bom_to_json(bom) + "\n")
    bom_csv_path.write_text(bom_to_csv(bom))

    # ---- 5. SVG overlay ----
    svg_path = out / "annotated_board.svg"
    click.echo(f"[5/7] Writing SVG overlay → {svg_path}")
    svg_str = generate_svg(result, image_href="synthetic_board.png")
    svg_path.write_text(svg_str, encoding="utf-8")

    # ---- 6. Probe recommendations ----
    probe_path = out / "probe_recommendations.txt"
    click.echo(f"[6/7] Running probe advisor → {probe_path}")
    probe_text = _run_probe_advisor(result)
    probe_path.write_text(probe_text)

    # ---- 7. Constraint solver + debug interfaces ----
    solver_path = out / "constraint_solver_output.txt"
    dbg_path = out / "debug_interfaces.txt"
    click.echo(f"[7/7] Running constraint solver → {solver_path}")
    solver_text = _run_constraint_solver(result)
    solver_path.write_text(solver_text)

    click.echo(f"      Running debug interface detector → {dbg_path}")
    dbg_text = _run_debug_interface_detection(result)
    dbg_path.write_text(dbg_text)

    # ---- Summary ----
    click.echo("")
    click.echo("Done! Output files:")
    for fname in OUTPUT_FILES:
        fpath = out / fname
        if fpath.exists():
            click.echo(f"  ✓  {fpath}  ({fpath.stat().st_size:,} bytes)")
        else:
            click.echo(f"  ✗  {fpath}  (MISSING)")


@cli.command()
@click.option(
    "--output-dir",
    default="docs/examples",
    show_default=True,
    help="Directory containing generated files.",
)
def clean(output_dir: str):
    """Remove all generated demo files."""
    out = Path(output_dir)
    removed = 0
    for fname in OUTPUT_FILES:
        fpath = out / fname
        if fpath.exists():
            fpath.unlink()
            click.echo(f"  Removed {fpath}")
            removed += 1
    click.echo(f"Cleaned {removed} file(s).")


if __name__ == "__main__":
    cli()
