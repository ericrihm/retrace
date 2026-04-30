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
import math
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import click
import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Make sure the package is importable whether or not it is installed
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from retrace.core.pipeline import AnalysisResult, Component, Pipeline, Trace
from retrace.analysis.constraint_solver import (
    ComponentSpec,
    ConstraintSolver,
    Trace as SolverTrace,
    Pin,
)
from retrace.analysis.probe_advisor import (
    Component as AdvisorComponent,
    ProbeAdvisor,
)
from retrace.export.bom import bom_to_csv, bom_to_json, generate_bom
from retrace.export.svg import generate_svg
from retrace.plugins.builtin.debug_interfaces import detect_debug_interfaces


# ---------------------------------------------------------------------------
# Board geometry constants (all in pixels; image is 1200×800)
# ---------------------------------------------------------------------------

IMG_W, IMG_H = 1200, 800

# fmt: off
# Each entry: (ref, label, x, y, w, h, marking, part_number, value, package, pins)
# Coordinates are for the component body rectangle.
KNOWN_COMPONENTS: list[tuple] = [
    # ref        label         x    y    w    h    marking        part_number      value      package      pins
    ("U1", "ic",         80,  80,  220, 200, "STM32F407VGT6",  "STM32F407",     "",        "LQFP-100",  ["VCC","GND","PA0","PA1","PB0","PB1","SWDIO","SWDCLK","NRST","BOOT0"]),
    ("U2", "ic",        450,  60,  180, 160, "W25Q128JVSIQ",   "W25Q128",       "128Mbit", "SOIC-8",    ["VCC","GND","MOSI","MISO","SCLK","CS","WP","HOLD"]),
    ("C1", "capacitor", 340, 100,   28,  16, "100nF",           "",              "100nF",   "0402",      ["1","2"]),
    ("C2", "capacitor", 380, 100,   28,  16, "10uF",            "",              "10uF",    "0603",      ["1","2"]),
    ("C3", "capacitor", 340, 130,   28,  16, "100nF",           "",              "100nF",   "0402",      ["1","2"]),
    ("R1", "resistor",  680, 110,   32,  14, "10k",             "",              "10k",     "0402",      ["A","B"]),
    ("R2", "resistor",  680, 136,   32,  14, "4k7",             "",              "4k7",     "0402",      ["A","B"]),
    ("Y1", "crystal",   780, 100,   52,  28, "8MHz",            "ABLS-8.000MHZ-B4-T","8MHz","HC-49S",   ["1","2","GND","GND2"]),
    ("J1", "connector", 970,  60,   80, 180, "SWD/JTAG",        "",              "",        "2x5 2.54mm",["VCC","SWDIO","GND","SWDCLK","GND2","NC","NC2","NC3","NC4","GND3"]),
    ("L1", "inductor",  680, 200,   44,  40, "10uH",            "",              "10uH",    "1210",      ["1","2"]),
    ("TP1","test_point",340, 440,   14,  14, "TP1",             "",              "",        "TP",        ["1"]),
    ("TP2","test_point",370, 440,   14,  14, "TP2",             "",              "",        "TP",        ["1"]),
    ("TP3","test_point",400, 440,   14,  14, "TP3",             "",              "",        "TP",        ["1"]),
    ("TP4","test_point",430, 440,   14,  14, "TP4",             "",              "",        "TP",        ["1"]),
]
# fmt: on

# Copper traces to draw: list of (point_list, width_px)
# Points are (x, y) tuples along the route.
TRACE_ROUTES: list[tuple[list[tuple[int, int]], int]] = [
    # U1 VCC to decoupling cap C1
    ([(190, 130), (340, 130), (340, 108)], 2),
    # U1 GND to C1 other pad
    ([(190, 175), (354, 175), (354, 116)], 2),
    # U1 SPI to W25Q128
    ([(300,  95), (450,  95)], 3),
    ([(300, 115), (450, 115)], 3),
    ([(300, 135), (450, 135)], 3),
    ([(300, 155), (450, 155)], 3),
    # U1 SWD to J1
    ([(300, 178), (970, 178)], 2),
    ([(300, 194), (970, 194)], 2),
    # U1 crystal pins to Y1
    ([(300, 214), (780, 110)], 2),
    ([(300, 230), (780, 128)], 2),
    # U1 to R1 (pull-up)
    ([(300, 250), (680, 117)], 2),
    # R1/R2 to L1 (power path)
    ([(712, 117), (724, 220)], 2),
    ([(712, 143), (724, 230)], 2),
    # L1 to J1 power pin
    ([(724, 200), (970, 140)], 3),
    # Test point cluster (UART)
    ([(354, 447), (500, 447)], 2),
    ([(384, 447), (500, 460)], 2),
    ([(414, 447), (500, 473)], 2),
    ([(444, 447), (500, 486)], 2),
]

# Via positions (x, y, outer_radius, inner_radius)
VIAS: list[tuple[int, int, int, int]] = [
    (340, 300, 5, 2),
    (380, 300, 5, 2),
    (420, 300, 5, 2),
    (460, 300, 5, 2),
    (500, 300, 5, 2),
    (540, 300, 5, 2),
    (580, 300, 5, 2),
    (620, 300, 5, 2),
    (660, 300, 5, 2),
    (700, 300, 5, 2),
    (300, 350, 5, 2),
    (300, 390, 5, 2),
    (724, 240, 6, 3),
    (724, 260, 6, 3),
]

# Mounting holes (x, y, outer_r, inner_r)
MOUNTING_HOLES: list[tuple[int, int, int, int]] = [
    (35, 35, 14, 8),
    (1165, 35, 14, 8),
    (35, 765, 14, 8),
    (1165, 765, 14, 8),
]

# Silkscreen labels: (text, x, y)
SILK_LABELS: list[tuple[str, int, int]] = [
    ("U1",  82,  78),
    ("U2", 452,  58),
    ("C1", 342,  98),
    ("C2", 382,  98),
    ("C3", 342, 128),
    ("R1", 682, 108),
    ("R2", 682, 134),
    ("Y1", 782,  98),
    ("J1", 972,  58),
    ("L1", 682, 198),
    ("TP1-TP4", 336, 460),
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

    # Board label
    cv2.putText(
        img,
        "re:trace DEMO BOARD  rev1.0",
        (IMG_W // 2 - 130, IMG_H - 25),
        font,
        0.45,
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

    # ---- Copper pour (ground plane section) ----
    cv2.rectangle(img, (50, 500), (900, 780), (25, 85, 110), -1)
    cv2.rectangle(img, (50, 500), (900, 780), (35, 95, 120), 1)
    cv2.putText(img, "GND", (60, 530), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 110, 140), 1)

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
        net_labels=["VCC", "GND", "SPI_MOSI", "SPI_MISO", "SPI_CLK", "SWD_DATA", "SWD_CLK", "UART_TX", "UART_RX"],
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

    # Build solver traces from TRACE_ROUTES — map index positions to pin names heuristically
    solver_traces: list[SolverTrace] = [
        SolverTrace(Pin("U1", "VCC"),   Pin("C1", "1"),    confidence=0.95),
        SolverTrace(Pin("U1", "GND"),   Pin("C1", "2"),    confidence=0.95),
        SolverTrace(Pin("U1", "PB0"),   Pin("U2", "MOSI"), confidence=0.90),
        SolverTrace(Pin("U1", "PB1"),   Pin("U2", "MISO"), confidence=0.90),
        SolverTrace(Pin("U1", "PA1"),   Pin("U2", "SCLK"), confidence=0.90),
        SolverTrace(Pin("U1", "PA0"),   Pin("U2", "CS"),   confidence=0.85),
        SolverTrace(Pin("U1", "SWDIO"), Pin("J1", "SWDIO"),confidence=0.92),
        SolverTrace(Pin("U1", "SWDCLK"),Pin("J1", "SWDCLK"),confidence=0.92),
        SolverTrace(Pin("J1", "VCC"),   Pin("L1", "1"),    confidence=0.88),
        SolverTrace(Pin("L1", "2"),     Pin("R1", "A"),    confidence=0.80),
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
