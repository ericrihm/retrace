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

from retrace.core.pipeline import AnalysisResult, Component, Trace  # noqa: E402
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
from retrace.export.svg import generate_svg, generate_attack_surface_svg, generate_zones_svg  # noqa: E402
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

    # Main APU — AMD "Liverpool" custom SoC: 8-core Jaguar x86-64 + GCN 1.1 (12 CU, 768 shaders)
    # TSMC 28nm, ~363mm² die. No separate southbridge — USB3, SATA, PCIe integrated on-die.
    ("U1", "ic",         500, 300, 300, 300, "Liverpool",      "AMD Liverpool",  "",       "BGA-1170",
     ["VCC_CORE","VCC_GFX","VCC_IO","GND","GND2","GND3","GND4","DDR_DQ0","DDR_DQ1","DDR_A0","HDMI_TX0P","HDMI_TX0N","PCIE_TX","PCIE_RX"]),

    # DDR3 RAM — SK Hynix H5TQ4G63AFR-PBC (4Gbit each, 16 chips total = 8GB, DDR3-1866)
    ("U2", "ic",         120, 120, 140,  90, "H5TQ4G63AFR",    "H5TQ4G63AFR-PBC", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U3", "ic",         300, 120, 140,  90, "H5TQ4G63AFR",    "H5TQ4G63AFR-PBC", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U4", "ic",         120, 680, 140,  90, "H5TQ4G63AFR",    "H5TQ4G63AFR-PBC", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U5", "ic",         300, 680, 140,  90, "H5TQ4G63AFR",    "H5TQ4G63AFR-PBC", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),

    # Southbridge — Microsoft X861949-005 (USB3, SATA, PCIe hub controller)
    ("U6", "ic",        1000, 120, 140, 100, "X861949",        "X861949-005",   "",       "BGA-360",
     ["VCC","GND","HDMI_TX0P","HDMI_TX0N","HDMI_TX1P","HDMI_TX1N","HDMI_TX2P","HDMI_TX2N","HDMI_CKP","HDMI_CKN","SDA","SCL"]),

    # eMMC — SK Hynix H26M42003GMR (8GB eMMC 4.51)
    ("U7", "ic",        1000, 300, 160, 120, "H26M42003GMR",  "H26M42003GMR",  "8GB",    "BGA-153",
     ["VCC","VCCQ","GND","CMD","CLK","DAT0","DAT1","DAT2","DAT3","DAT4","DAT5","DAT6","DAT7"]),

    # WiFi/BT — Marvell AVASTAR 88W8897 (2x2 802.11ac + BT 4.0)
    ("U8", "ic",        1050, 500, 120,  80, "88W8897",        "88W8897-NNB2",  "",       "QFN-68",
     ["VCC","GND","SDIO_CLK","SDIO_CMD","SDIO_D0","SDIO_D1","ANT1","ANT2"]),

    # Ethernet PHY — Realtek RTL8151GNM (GbE)
    ("U9", "ic",        1050, 660, 100,  70, "RTL8151GNM",     "RTL8151GNM",    "",       "QFN-40",
     ["VCC","GND","MDI0P","MDI0N","MDI1P","MDI1N","TX_CLK","RX_CLK"]),

    # Power: APU core VRM — ON Semi NCP4204 (multi-phase controller)
    ("U10","ic",          80, 350,  70,  55, "NCP4204",        "NCP4204",       "",       "QFN-52",
     ["VIN","VOUT","GND","EN","BOOT","SW","PGOOD","FB"]),

    # Power: Memory VRM — IR3553 (DDR3 rail)
    ("U11","ic",          80, 440,  70,  55, "IR3553",         "IR3553",        "",       "PQFN-25",
     ["VIN","VOUT","GND","EN","SW","FB","PGOOD"]),

    # HDMI-in mux — TI TMDS442 (HDMI passthrough switching)
    ("U12","ic",        1300, 150,  80,  60, "TMDS442",        "TMDS442",       "",       "QFP-48",
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

    # -----------------------------------------------------------------------
    # DDR3 RAM — back-side pair (U13-U16), mirroring U2-U5 at lower Y
    # -----------------------------------------------------------------------
    ("U13","ic",         500, 120, 140,  90, "H5TQ4G63AFR",    "H5TQ4G63AFR-PBC", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U14","ic",         680, 120, 140,  90, "H5TQ4G63AFR",    "H5TQ4G63AFR-PBC", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U15","ic",         500, 680, 140,  90, "H5TQ4G63AFR",    "H5TQ4G63AFR-PBC", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U16","ic",         680, 680, 140,  90, "H5TQ4G63AFR",    "H5TQ4G63AFR-PBC", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),

    # -----------------------------------------------------------------------
    # Power section — additional VRMs, DrMOS, LDOs (U17-U22)
    # -----------------------------------------------------------------------
    # DrMOS integrated power stages for APU core VRM
    ("U17","ic",          80, 260,  60,  45, "NCP302155",      "NCP302155",     "",       "PQFN-40",
     ["VIN","VOUT","BST","SW","GND","EN","PGOOD","ILIM"]),
    ("U18","ic",         170, 260,  60,  45, "NCP302155",      "NCP302155",     "",       "PQFN-40",
     ["VIN","VOUT","BST","SW","GND","EN","PGOOD","ILIM"]),
    # PWM controllers for multi-phase VRM
    ("U19","ic",          80, 530,  70,  50, "NCP81111",       "NCP81111",      "",       "QFN-36",
     ["VIN","VCC","GND","PWM1","PWM2","FB","COMP","SS","PGOOD","EN"]),
    ("U20","ic",         170, 530,  70,  50, "NCP81111",       "NCP81111",      "",       "QFN-36",
     ["VIN","VCC","GND","PWM1","PWM2","FB","COMP","SS","PGOOD","EN"]),
    # 1.1V IO rail buck converter
    ("U21","ic",          80, 610,  55,  40, "TPS54331",       "TPS54331DR",    "",       "SOIC-8",
     ["VIN","BOOT","GND","VSNS","COMP","EN","SS","PH"]),
    # 3.3V LDO for HDMI/USB subsystem
    ("U22","ic",        1300, 250,  50,  35, "TLV1117-33",     "TLV1117LV33",   "3.3V",  "SOT-223",
     ["VIN","VOUT","GND","GND2"]),

    # -----------------------------------------------------------------------
    # Decoupling capacitors (C7-C50) — every IC gets 2-4 caps
    # -----------------------------------------------------------------------
    # APU (U1) decoupling — 8 caps around perimeter
    ("C7", "capacitor",  470, 300,  28,  16, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C8", "capacitor",  470, 340,  28,  16, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C9", "capacitor",  470, 380,  28,  16, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    ("C10","capacitor",  470, 420,  28,  16, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C11","capacitor",  810, 310,  28,  16, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C12","capacitor",  810, 350,  28,  16, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    ("C13","capacitor",  810, 390,  28,  16, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C14","capacitor",  810, 430,  28,  16, "100nF",          "",              "100nF",  "0402", ["1","2"]),

    # DDR3 U2 decoupling
    ("C15","capacitor",  100, 112,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C16","capacitor",  270, 112,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # DDR3 U3 decoupling
    ("C17","capacitor",  280, 112,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C18","capacitor",  448, 112,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # DDR3 U4 decoupling
    ("C19","capacitor",  100, 780,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C20","capacitor",  270, 780,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # DDR3 U5 decoupling
    ("C21","capacitor",  280, 780,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C22","capacitor",  448, 780,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # DDR3 U13 decoupling
    ("C23","capacitor",  480, 112,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C24","capacitor",  648, 112,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # DDR3 U14 decoupling
    ("C25","capacitor",  660, 112,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C26","capacitor",  828, 112,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # DDR3 U15 decoupling
    ("C27","capacitor",  480, 780,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C28","capacitor",  648, 780,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # DDR3 U16 decoupling
    ("C29","capacitor",  660, 780,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C30","capacitor",  828, 780,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),

    # HDMI encoder U6 decoupling
    ("C31","capacitor",  980, 112,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C32","capacitor",  980, 230,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # eMMC U7 decoupling
    ("C33","capacitor",  980, 290,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C34","capacitor",  980, 430,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # WiFi U8 decoupling
    ("C35","capacitor", 1030, 492,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C36","capacitor", 1180, 492,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # Ethernet PHY U9 decoupling
    ("C37","capacitor", 1030, 652,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C38","capacitor", 1160, 652,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),

    # VRM bulk caps (near U10/U11/U17-U21)
    ("C39","capacitor",   60, 310,  30,  20, "470uF",          "",              "470uF",  "1210", ["1","2"]),
    ("C40","capacitor",  160, 310,  30,  20, "470uF",          "",              "470uF",  "1210", ["1","2"]),
    ("C41","capacitor",   60, 500,  26,  16, "22uF",           "",              "22uF",   "0805", ["1","2"]),
    ("C42","capacitor",  160, 500,  26,  16, "22uF",           "",              "22uF",   "0805", ["1","2"]),
    ("C43","capacitor",   60, 580,  26,  16, "22uF",           "",              "22uF",   "0805", ["1","2"]),
    ("C44","capacitor",  160, 580,  26,  16, "22uF",           "",              "22uF",   "0805", ["1","2"]),

    # HDMI retimer U12 decoupling
    ("C45","capacitor", 1280, 142,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C46","capacitor", 1390, 142,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # LDO U22 output cap
    ("C47","capacitor", 1360, 252,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # Crystal Y1 load caps
    ("C48","capacitor",  860, 420,  22,  14, "22pF",           "",              "22pF",   "0402", ["1","2"]),
    ("C49","capacitor",  930, 420,  22,  14, "22pF",           "",              "22pF",   "0402", ["1","2"]),
    # Spare bulk cap near APU
    ("C50","capacitor",  830, 260,  28,  16, "100uF",          "",              "100uF",  "1206", ["1","2"]),

    # -----------------------------------------------------------------------
    # Pull-up / pull-down resistors (R4-R20)
    # -----------------------------------------------------------------------
    # I2C pull-ups near HDMI encoder U6
    ("R4", "resistor",   960, 130,  30,  14, "4k7",            "",              "4k7",    "0402", ["A","B"]),
    ("R5", "resistor",   960, 150,  30,  14, "4k7",            "",              "4k7",    "0402", ["A","B"]),
    # I2C pull-ups near HDMI retimer U12
    ("R6", "resistor",  1290, 130,  30,  14, "4k7",            "",              "4k7",    "0402", ["A","B"]),
    ("R7", "resistor",  1290, 210,  30,  14, "4k7",            "",              "4k7",    "0402", ["A","B"]),
    # USB termination resistors near J2
    ("R8", "resistor",  1390, 290,  30,  14, "90",             "",              "90",     "0402", ["A","B"]),
    ("R9", "resistor",  1390, 310,  30,  14, "90",             "",              "90",     "0402", ["A","B"]),
    # USB termination resistors near J3
    ("R10","resistor",  1390, 470,  30,  14, "90",             "",              "90",     "0402", ["A","B"]),
    ("R11","resistor",  1390, 490,  30,  14, "90",             "",              "90",     "0402", ["A","B"]),
    # Reset pull-up
    ("R12","resistor",   840, 380,  30,  14, "10k",            "",              "10k",    "0402", ["A","B"]),
    # DDR3 termination resistors
    ("R13","resistor",   120, 220,  30,  14, "49.9",           "",              "49.9",   "0402", ["A","B"]),
    ("R14","resistor",   300, 220,  30,  14, "49.9",           "",              "49.9",   "0402", ["A","B"]),
    ("R15","resistor",   500, 220,  30,  14, "49.9",           "",              "49.9",   "0402", ["A","B"]),
    ("R16","resistor",   680, 220,  30,  14, "49.9",           "",              "49.9",   "0402", ["A","B"]),
    # LED current limiters
    ("R17","resistor",  1250, 850,  30,  14, "330",            "",              "330",    "0402", ["A","B"]),
    ("R18","resistor",  1290, 850,  30,  14, "330",            "",              "330",    "0402", ["A","B"]),
    ("R19","resistor",  1330, 850,  30,  14, "330",            "",              "330",    "0402", ["A","B"]),
    ("R20","resistor",  1370, 850,  30,  14, "330",            "",              "330",    "0402", ["A","B"]),

    # -----------------------------------------------------------------------
    # ESD protection diodes (D1-D6)
    # -----------------------------------------------------------------------
    # USB ESD near J2, J3
    ("D1", "ic",        1400, 260,  36,  22, "USBLC6",         "USBLC6-2SC6",   "",       "SOT-23-6",
     ["IO1","GND","IO2","IO2B","VCC","IO1B"]),
    ("D2", "ic",        1400, 440,  36,  22, "USBLC6",         "USBLC6-2SC6",   "",       "SOT-23-6",
     ["IO1","GND","IO2","IO2B","VCC","IO1B"]),
    # HDMI ESD near J1
    ("D3", "ic",        1400, 100,  40,  20, "IP4283CZ",       "IP4283CZ10",    "",       "SOT-665",
     ["IO1","IO2","IO3","GND","IO4","IO5","IO6","IO7","IO8","VCC"]),
    # Ethernet ESD near J4
    ("D4", "ic",        1400, 630,  36,  22, "PRTR5V0",        "PRTR5V0U2X",    "",       "SOT-143",
     ["IO1","GND","IO2","VCC"]),
    # HDMI-in ESD near U12
    ("D5", "ic",        1380, 170,  36,  22, "IP4283CZ",       "IP4283CZ10",    "",       "SOT-665",
     ["IO1","IO2","IO3","GND","IO4","IO5","IO6","IO7","IO8","VCC"]),
    # JTAG ESD near J5
    ("D6", "ic",          60, 850,  36,  22, "PRTR5V0",        "PRTR5V0U2X",    "",       "SOT-143",
     ["IO1","GND","IO2","VCC"]),

    # -----------------------------------------------------------------------
    # MOSFETs for VRM power stages (Q1-Q6)
    # -----------------------------------------------------------------------
    ("Q1", "ic",         100, 300,  30,  25, "BSC014N04",      "BSC014N04LS",   "",       "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q2", "ic",         140, 300,  30,  25, "BSC014N04",      "BSC014N04LS",   "",       "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q3", "ic",         100, 470,  30,  25, "BSC014N04",      "BSC014N04LS",   "",       "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q4", "ic",         140, 470,  30,  25, "BSC014N04",      "BSC014N04LS",   "",       "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q5", "ic",         100, 560,  30,  25, "BSC014N04",      "BSC014N04LS",   "",       "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q6", "ic",         140, 560,  30,  25, "BSC014N04",      "BSC014N04LS",   "",       "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),

    # -----------------------------------------------------------------------
    # Additional connectors (J6-J10)
    # -----------------------------------------------------------------------
    # SATA connector (right side, below Ethernet)
    ("J6", "connector", 1420, 800,  80,  50, "SATA",           "",              "",       "SATA-7P",
     ["TX+","TX-","RX+","RX-","GND","GND2","GND3"]),
    # WiFi antenna connector near U8
    ("J7", "connector", 1180, 520,  30,  30, "ANT",            "",              "",       "U.FL",
     ["SIG","GND"]),
    # IR receiver (front panel area)
    ("J8", "connector", 1300, 880,  40,  30, "IR",             "",              "",       "3-pin",
     ["VCC","SIG","GND"]),
    # Optical audio (TOSLINK)
    ("J9", "connector", 1420, 870,  60,  50, "TOSLINK",        "",              "",       "TOSLINK",
     ["TX","GND","VCC"]),
    # DC power connector (left side)
    ("J10","connector",   60, 50,   70,  50, "DC 12V",         "",              "",       "Barrel-5.5mm",
     ["VCC_12V","GND"]),

    # -----------------------------------------------------------------------
    # Status LEDs (D7-D10)
    # -----------------------------------------------------------------------
    ("D7", "resistor",  1250, 880,  20,  14, "PWR",            "",              "GREEN",  "0805", ["A","K"]),
    ("D8", "resistor",  1280, 880,  20,  14, "DISK",           "",              "AMBER",  "0805", ["A","K"]),
    ("D9", "resistor",  1310, 880,  20,  14, "WIFI",           "",              "BLUE",   "0805", ["A","K"]),
    ("D10","resistor",  1340, 880,  20,  14, "KINECT",         "",              "WHITE",  "0805", ["A","K"]),

    # -----------------------------------------------------------------------
    # Additional test points (TP6-TP15) — scattered near power rails, DDR, PCIe
    # -----------------------------------------------------------------------
    ("TP6", "test_point", 350, 880,  14,  14, "TP6",           "",              "",       "TP", ["1"]),
    ("TP7", "test_point", 380, 880,  14,  14, "TP7",           "",              "",       "TP", ["1"]),
    ("TP8", "test_point",  80, 660,  14,  14, "TP8",           "",              "",       "TP", ["1"]),
    ("TP9", "test_point", 170, 660,  14,  14, "TP9",           "",              "",       "TP", ["1"]),
    ("TP10","test_point", 870, 280,  14,  14, "TP10",          "",              "",       "TP", ["1"]),
    ("TP11","test_point", 870, 320,  14,  14, "TP11",          "",              "",       "TP", ["1"]),
    ("TP12","test_point", 870, 360,  14,  14, "TP12",          "",              "",       "TP", ["1"]),
    ("TP13","test_point", 870, 400,  14,  14, "TP13",          "",              "",       "TP", ["1"]),
    ("TP14","test_point", 870, 500,  14,  14, "TP14",          "",              "",       "TP", ["1"]),
    ("TP15","test_point", 870, 540,  14,  14, "TP15",          "",              "",       "TP", ["1"]),

    # -----------------------------------------------------------------------
    # Additional inductors for new VRM phases
    # -----------------------------------------------------------------------
    ("L3", "inductor",   170, 280,  50,  40, "0.47uH",         "",             "0.47uH", "1210", ["1","2"]),
    ("L4", "inductor",   170, 550,  50,  40, "1uH",            "",             "1uH",    "1210", ["1","2"]),
    ("L5", "inductor",   170, 620,  50,  40, "2.2uH",          "",             "2.2uH",  "1210", ["1","2"]),

    # -----------------------------------------------------------------------
    # Additional passives to fill board density (C51-C56, R21-R25)
    # -----------------------------------------------------------------------
    # DrMOS U17/U18 input bypass caps
    ("C51","capacitor",   60, 260,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    ("C52","capacitor",  240, 260,  24,  14, "10uF",           "",              "10uF",   "0805", ["1","2"]),
    # PWM controller U19/U20 bypass
    ("C53","capacitor",   60, 555,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    ("C54","capacitor",  248, 555,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    # WiFi module U8 additional bypass
    ("C55","capacitor", 1030, 590,  24,  14, "1uF",            "",              "1uF",    "0402", ["1","2"]),
    # SATA connector J6 decoupling
    ("C56","capacitor", 1400, 800,  24,  14, "100nF",          "",              "100nF",  "0402", ["1","2"]),
    # Ethernet PHY RGMII termination
    ("R21","resistor",  1030, 740,  30,  14, "33",             "",              "33",     "0402", ["A","B"]),
    ("R22","resistor",  1070, 740,  30,  14, "33",             "",              "33",     "0402", ["A","B"]),
    # SATA AC coupling
    ("R23","resistor",  1390, 810,  30,  14, "0",              "",              "0",      "0402", ["A","B"]),
    # WiFi SDIO pull-up
    ("R24","resistor",  1050, 480,  30,  14, "10k",            "",              "10k",    "0402", ["A","B"]),
    # APU PLL filter resistor
    ("R25","resistor",   840, 460,  30,  14, "1k",             "",              "1k",     "0402", ["A","B"]),
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

    # -----------------------------------------------------------------------
    # New DDR3 (U13-U16) data bus to APU
    # -----------------------------------------------------------------------
    ([(500, 350), (570, 350), (570, 210)], 3),   # DDR_DQ4 → U13
    ([(500, 370), (750, 370), (750, 210)], 3),   # DDR_DQ5 → U14
    ([(500, 580), (570, 580), (570, 770)], 3),   # DDR_DQ6 → U15
    ([(500, 600), (750, 600), (750, 770)], 3),   # DDR_DQ7 → U16

    # -----------------------------------------------------------------------
    # Power section traces
    # -----------------------------------------------------------------------
    # DrMOS U17/U18 to APU core VRM bus
    ([(140, 282), (240, 282), (500, 320)], 5),   # U17 → APU core
    ([(230, 282), (350, 282), (500, 340)], 5),   # U18 → APU core
    # PWM controllers U19/U20 to DrMOS phases
    ([(80, 555), (80, 490), (80, 370)], 2),      # U19 PWM → U10
    ([(170, 555), (170, 500), (170, 370)], 2),   # U20 PWM → U10
    # IO rail buck U21 to APU IO
    ([(135, 630), (350, 630), (500, 560)], 4),   # 1.1V IO → APU
    # LDO U22 to HDMI/USB area
    ([(1350, 267), (1420, 267), (1420, 260)], 3),# 3.3V → HDMI connector area
    # Inductor L3 → DrMOS output
    ([(220, 300), (350, 300), (500, 310)], 4),   # L3 → APU
    # Inductor L4 → PWM area
    ([(220, 570), (350, 570), (500, 520)], 4),   # L4 → APU
    # Inductor L5 → IO buck output
    ([(220, 640), (350, 640), (500, 540)], 4),   # L5 → APU

    # -----------------------------------------------------------------------
    # MOSFET gate traces from VRM controllers
    # -----------------------------------------------------------------------
    ([(80, 380), (100, 380), (100, 325)], 2),    # U10 → Q1 gate
    ([(80, 395), (140, 395), (140, 325)], 2),    # U10 → Q2 gate
    ([(80, 465), (100, 465), (100, 495)], 2),    # U11 → Q3 gate
    ([(80, 475), (140, 475), (140, 495)], 2),    # U11 → Q4 gate
    ([(80, 635), (100, 635), (100, 585)], 2),    # U21 → Q5 gate
    ([(135, 635), (140, 635), (140, 585)], 2),   # U21 → Q6 gate

    # -----------------------------------------------------------------------
    # ESD protection traces
    # -----------------------------------------------------------------------
    ([(1420, 160), (1400, 160), (1400, 122)], 2),# HDMI ESD D3 → J1
    ([(1420, 310), (1400, 310), (1400, 282)], 2),# USB ESD D1 → J2
    ([(1420, 500), (1400, 500), (1400, 462)], 2),# USB ESD D2 → J3
    ([(1420, 680), (1400, 680), (1400, 652)], 2),# Eth ESD D4 → J4
    ([(1300, 180), (1380, 180), (1380, 192)], 2),# HDMI-in ESD D5 → U12
    ([(60, 870), (60, 862), (60, 850)], 2),      # JTAG ESD D6 → J5

    # -----------------------------------------------------------------------
    # Additional connectors traces
    # -----------------------------------------------------------------------
    # SATA J6 to APU PCIe/SATA
    ([(1420, 820), (900, 820), (900, 600), (800, 600)], 3), # SATA → APU
    # WiFi antenna J7 to U8
    ([(1180, 535), (1170, 535), (1170, 540)], 2),# ANT → WiFi
    # IR receiver J8 to APU
    ([(1300, 895), (900, 895), (900, 600), (800, 595)], 2), # IR → APU
    # TOSLINK J9 to APU audio
    ([(1420, 895), (950, 895), (950, 600), (800, 590)], 2), # TOSLINK → APU
    # DC power J10 to VRMs
    ([(60, 100), (60, 260)], 5),                 # 12V → VRM area

    # -----------------------------------------------------------------------
    # LED traces from APU GPIO
    # -----------------------------------------------------------------------
    ([(800, 570), (1250, 570), (1250, 880)], 2), # PWR LED
    ([(800, 575), (1280, 575), (1280, 880)], 2), # DISK LED
    ([(800, 580), (1310, 580), (1310, 880)], 2), # WIFI LED
    ([(800, 585), (1340, 585), (1340, 880)], 2), # KINECT LED
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

    # New DDR3 U13/U14 bus transition vias
    (570, 300, 6, 3),
    (610, 300, 6, 3),
    (750, 300, 6, 3),
    (790, 300, 6, 3),
    # New DDR3 U15/U16 bus transition vias
    (570, 700, 6, 3),
    (610, 700, 6, 3),
    (750, 700, 6, 3),
    (790, 700, 6, 3),

    # DrMOS / VRM area vias
    (100, 250, 5, 2),
    (140, 250, 5, 2),
    (180, 250, 5, 2),
    (100, 520, 5, 2),
    (140, 520, 5, 2),
    (100, 600, 5, 2),
    (140, 600, 5, 2),

    # MOSFET area power vias
    (120, 340, 6, 3),
    (160, 340, 6, 3),
    (120, 510, 6, 3),

    # ESD protection area vias
    (1400, 140, 5, 2),
    (1400, 280, 5, 2),
    (1400, 460, 5, 2),
    (1400, 650, 5, 2),

    # SATA/audio right-side vias
    (900, 810, 5, 2),
    (950, 810, 5, 2),

    # LED trace transition vias
    (1250, 580, 5, 2),
    (1290, 580, 5, 2),
    (1330, 580, 5, 2),

    # Power input via
    (60, 150, 6, 3),
    (60, 200, 6, 3),

    # Ground stitching between APU and connectors
    (900, 350, 5, 2),
    (900, 400, 5, 2),
    (900, 450, 5, 2),
    (900, 550, 5, 2),
    (950, 350, 5, 2),
    (950, 400, 5, 2),
    (950, 450, 5, 2),
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
    ("U13",  502,  118),   # DDR3
    ("U14",  682,  118),   # DDR3
    ("U15",  502,  678),   # DDR3
    ("U16",  682,  678),   # DDR3
    ("U17",   82,  258),   # DrMOS
    ("U18",  172,  258),   # DrMOS
    ("U19",   82,  528),   # PWM
    ("U20",  172,  528),   # PWM
    ("U21",   82,  608),   # Buck
    ("U22", 1302,  248),   # LDO
    ("J6",  1422,  798),   # SATA
    ("J7",  1182,  518),   # ANT
    ("J8",  1302,  878),   # IR
    ("J9",  1422,  868),   # TOSLINK
    ("J10",   62,   48),   # DC Power
    ("L3",   172,  278),
    ("L4",   172,  548),
    ("L5",   172,  618),
    ("D1",  1402,  258),   # USB ESD
    ("D2",  1402,  438),   # USB ESD
    ("D3",  1402,   98),   # HDMI ESD
    ("D4",  1402,  628),   # Eth ESD
    ("D6",    62,  848),   # JTAG ESD
    ("Q1-Q6", 102, 338),   # MOSFETs
    ("TP6-TP7", 346, 900),
    ("TP8-9",  82, 678),
    ("TP10-15", 872, 558),
    ("FCC: C3K1520", 1300, 970),
    ("(C) Microsoft Corp. — Synthetic Demo Only", 400, 970),
]


# ===========================================================================
# CISCO ASA 5506-X BOARD — enterprise firewall / NGIPS
# Intel Atom C2508 (Rangeley) + Xilinx Spartan-6 Trust Anchor FPGA
# ArcaneDoor APT target, Thrangrycat (CVE-2019-1649), CISA ED 25-03
# ===========================================================================

CISCO_IMG_W, CISCO_IMG_H = 1600, 1000

# fmt: off
CISCO_COMPONENTS: list[tuple] = [
    # Intel Atom C2508 (Rangeley) — main CPU, FCBGA-1283
    ("U1", "ic", 420, 280, 260, 260, "ATOM C2508", "C2508", "", "FCBGA-1283",
     ["VCC","GND","DDR3_DQ0","DDR3_A0","PCIE_TX0","PCIE_RX0","SATA_TX","SATA_RX",
      "USB_DP","USB_DN","SPI_MOSI","SPI_MISO","SPI_CLK","SPI_CS","JTAG_TDI",
      "JTAG_TDO","JTAG_TCK","JTAG_TMS","UART_TX","UART_RX","GbE0_TX","GbE0_RX",
      "GbE1_TX","GbE1_RX","GbE2_TX","GbE2_RX","GbE3_TX","GbE3_RX","QAT_IN","QAT_OUT"]),

    # DDR3 ECC RAM — 4x Micron MT41K256M16HA (1GB each = 4GB total)
    ("U2", "ic", 130, 180, 120, 70, "MT41K256M16", "MT41K256M16HA", "1GB", "BGA-96",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","A0","CK","CKE","CS","RAS","CAS","WE"]),
    ("U3", "ic", 130, 360, 120, 70, "MT41K256M16", "MT41K256M16HA", "1GB", "BGA-96",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","A0","CK","CKE","CS","RAS","CAS","WE"]),
    ("U4", "ic", 130, 500, 120, 70, "MT41K256M16", "MT41K256M16HA", "1GB", "BGA-96",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","A0","CK","CKE","CS","RAS","CAS","WE"]),
    ("U5", "ic", 130, 640, 120, 70, "MT41K256M16", "MT41K256M16HA", "1GB", "BGA-96",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","A0","CK","CKE","CS","RAS","CAS","WE"]),

    # Xilinx Spartan-6 LX45T FPGA — Trust Anchor module (Thrangrycat CVE-2019-1649)
    ("U6", "ic", 750, 160, 160, 140, "XC6SLX45T", "XC6SLX45T-2FGG484", "", "BGA-484",
     ["VCC","GND","INIT_B","DONE","PROG_B","CCLK","SPI_DI","SPI_DO","SPI_CLK","SPI_CS",
      "PROC_RST","PROC_CLK","TRUST_VERIFY","TRUST_STATUS","JTAG_TDI","JTAG_TDO"]),

    # SPI NOR flash — FPGA bitstream (unencrypted — Thrangrycat attack surface)
    ("U7", "ic", 950, 200, 60, 36, "W25Q128JV", "W25Q128JVSIQ", "16MB", "SOIC-8",
     ["CS","DO","WP","GND","DI","CLK","HOLD","VCC"]),

    # Intel I354 — 4-port GbE PCIe NIC (additional ports beyond SoC integrated MACs)
    ("U8", "ic", 900, 480, 150, 130, "I354-AM4", "I354-AM4", "", "BGA-576",
     ["VCC","GND","P0_TX","P0_RX","P1_TX","P1_RX","P2_TX","P2_RX","P3_TX","P3_RX",
      "PCIE_TX","PCIE_RX","MDIO","MDC","LED0","LED1"]),

    # eUSB flash module — 8GB ASA firmware storage
    ("U9", "ic", 350, 650, 80, 50, "eUSB 8GB", "SATADOM-SL", "8GB", "eUSB",
     ["VCC","GND","USB_DP","USB_DN"]),

    # mSATA SSD connector — 50GB FirePOWER storage
    ("J6", "connector", 100, 790, 150, 60, "mSATA 50GB", "", "50GB", "mSATA",
     ["SATA_TX+","SATA_TX-","SATA_RX+","SATA_RX-","GND","3V3"]),

    # VRM: TPS54331 — 12V→3.3V step-down
    ("U10", "ic", 80, 100, 60, 42, "TPS54331", "TPS54331DR", "", "SOIC-8",
     ["VIN","BOOT","GND","VSNS","COMP","EN","SS","PH"]),

    # VRM: NCP5232 — CPU core VRM
    ("U11", "ic", 300, 140, 70, 42, "NCP5232", "NCP5232", "", "QFN-20",
     ["VIN","VOUT","GND","EN","FB","SS","PGOOD","SW"]),

    # VRM: TPS51200 — DDR3 VTT termination
    ("U12", "ic", 80, 460, 50, 32, "TPS51200", "TPS51200DR", "", "SON-10",
     ["VIN","VOUT","VREF","GND","EN","VTTR"]),

    # 8x GbE RJ45 ports (front panel — the firewall interfaces)
    ("J1", "connector", 850, 800, 70, 80, "GbE-1", "", "", "RJ45-MAG",
     ["TX+","TX-","RX+","RX-","GND","LED_G","LED_A"]),
    ("J2", "connector", 930, 800, 70, 80, "GbE-2", "", "", "RJ45-MAG",
     ["TX+","TX-","RX+","RX-","GND","LED_G","LED_A"]),
    ("J3", "connector", 1010, 800, 70, 80, "GbE-3", "", "", "RJ45-MAG",
     ["TX+","TX-","RX+","RX-","GND","LED_G","LED_A"]),
    ("J4", "connector", 1090, 800, 70, 80, "GbE-4", "", "", "RJ45-MAG",
     ["TX+","TX-","RX+","RX-","GND","LED_G","LED_A"]),
    ("J5", "connector", 1170, 800, 70, 80, "GbE-5", "", "", "RJ45-MAG",
     ["TX+","TX-","RX+","RX-","GND","LED_G","LED_A"]),
    ("J7", "connector", 1250, 800, 70, 80, "GbE-6", "", "", "RJ45-MAG",
     ["TX+","TX-","RX+","RX-","GND","LED_G","LED_A"]),
    ("J8", "connector", 1330, 800, 70, 80, "GbE-7", "", "", "RJ45-MAG",
     ["TX+","TX-","RX+","RX-","GND","LED_G","LED_A"]),
    ("J9", "connector", 1410, 800, 70, 80, "GbE-8", "", "", "RJ45-MAG",
     ["TX+","TX-","RX+","RX-","GND","LED_G","LED_A"]),

    # Console RJ45 (serial management — RS-232)
    ("J10", "connector", 700, 800, 70, 80, "CONSOLE", "", "", "RJ45",
     ["TX","RX","GND","VCC"]),

    # Management GbE port (separate from data plane)
    ("J11", "connector", 1490, 800, 70, 80, "MGMT", "", "", "RJ45-MAG",
     ["TX+","TX-","RX+","RX-","GND"]),

    # USB Type A — external storage
    ("J12", "connector", 600, 800, 60, 60, "USB-A", "", "", "USB-A",
     ["VBUS","D-","D+","GND"]),

    # USB Mini-B — alternate serial console
    ("J13", "connector", 520, 800, 50, 50, "USB Mini-B", "", "", "USB-Mini-B",
     ["VBUS","D-","D+","GND","ID"]),

    # DC power jack — 12V 60W barrel connector
    ("J14", "connector", 50, 800, 60, 60, "DC 12V", "", "", "Barrel-5.5mm",
     ["VCC_12V","GND"]),

    # JTAG header — 14-pin, near CPU (x86 debug chain)
    ("J15", "connector", 650, 130, 90, 30, "JTAG", "", "", "2x7 2.54mm",
     ["TDI","TDO","TCK","TMS","TRST","VCC","GND","GND2","NRST"]),

    # Passives — decoupling, pull-ups, bypass caps
    ("C1", "capacitor", 380, 260, 26, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C2", "capacitor", 380, 560, 26, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C3", "capacitor", 700, 300, 26, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C4", "capacitor", 730, 140, 26, 14, "22uF", "", "22uF", "0805", ["1","2"]),
    ("C5", "capacitor", 860, 440, 26, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C6", "capacitor", 1060, 460, 26, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("R1", "resistor", 750, 120, 28, 12, "10k", "", "10k", "0402", ["A","B"]),
    ("R2", "resistor", 780, 120, 28, 12, "4k7", "", "4k7", "0402", ["A","B"]),
    ("R3", "resistor", 300, 580, 28, 12, "182", "", "182", "0402", ["A","B"]),

    # Inductors (VRM output filters)
    ("L1", "inductor", 200, 110, 42, 36, "2.2uH", "", "2.2uH", "1210", ["1","2"]),
    ("L2", "inductor", 60, 460, 42, 36, "1uH", "", "1uH", "1210", ["1","2"]),

    # Crystal — 25MHz reference for Atom CPU
    ("Y1", "crystal", 350, 570, 48, 24, "25MHz", "ABLS-25.000MHZ", "25MHz", "HC-49S",
     ["1","2","GND","GND2"]),

    # Test points near JTAG / AVR54 rework area
    ("TP1", "test_point", 770, 130, 12, 12, "TP1", "", "", "TP", ["1"]),
    ("TP2", "test_point", 790, 130, 12, 12, "TP2", "", "", "TP", ["1"]),
    ("TP3", "test_point", 810, 130, 12, 12, "TP3", "", "", "TP", ["1"]),
    ("TP4", "test_point", 830, 130, 12, 12, "R182", "", "", "TP", ["1"]),

    # -----------------------------------------------------------------------
    # CPU decoupling (C_CPU1-C_CPU20) — 20 caps around the Intel Atom C2508
    # -----------------------------------------------------------------------
    ("C_CPU1", "capacitor", 390, 280, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU2", "capacitor", 390, 310, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU3", "capacitor", 390, 340, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU4", "capacitor", 390, 370, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU5", "capacitor", 390, 400, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU6", "capacitor", 390, 430, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_CPU7", "capacitor", 390, 460, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_CPU8", "capacitor", 390, 490, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU9", "capacitor", 390, 520, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU10","capacitor", 700, 280, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU11","capacitor", 700, 310, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU12","capacitor", 700, 340, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_CPU13","capacitor", 700, 370, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU14","capacitor", 700, 400, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU15","capacitor", 700, 430, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_CPU16","capacitor", 700, 460, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU17","capacitor", 700, 490, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU18","capacitor", 700, 520, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_CPU19","capacitor", 440, 560, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_CPU20","capacitor", 480, 560, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),

    # -----------------------------------------------------------------------
    # FPGA decoupling (C_FPGA1-C_FPGA10) — 10 caps around Xilinx Spartan-6
    # -----------------------------------------------------------------------
    ("C_FPGA1", "capacitor", 730, 155, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_FPGA2", "capacitor", 730, 180, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_FPGA3", "capacitor", 730, 205, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_FPGA4", "capacitor", 730, 230, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_FPGA5", "capacitor", 730, 255, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_FPGA6", "capacitor", 920, 160, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_FPGA7", "capacitor", 920, 185, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_FPGA8", "capacitor", 920, 240, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_FPGA9", "capacitor", 920, 265, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_FPGA10","capacitor", 920, 290, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),

    # -----------------------------------------------------------------------
    # DDR3 decoupling (C_DDR1-C_DDR8) — 2 per DDR3 chip
    # -----------------------------------------------------------------------
    ("C_DDR1", "capacitor", 110, 175, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_DDR2", "capacitor", 260, 190, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_DDR3", "capacitor", 110, 355, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_DDR4", "capacitor", 260, 370, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_DDR5", "capacitor", 110, 495, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_DDR6", "capacitor", 260, 510, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_DDR7", "capacitor", 110, 635, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_DDR8", "capacitor", 260, 650, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),

    # -----------------------------------------------------------------------
    # VRM section — multi-phase VRMs for CPU core, FPGA, DDR3, IO
    # -----------------------------------------------------------------------
    # CPU core VRM — IR3564B multi-phase controller
    ("U_VRM1", "ic", 270, 60, 55, 40, "IR3564B", "IR3564B", "", "QFN-48",
     ["VIN","VOUT","GND","EN","FB","SS","PGOOD","SW","PWM1","PWM2","PWM3"]),
    # FPGA core VRM — TPS54620 4.5-17V step-down
    ("U_VRM2", "ic", 780, 60, 55, 40, "TPS54620", "TPS54620RGY", "", "QFN-14",
     ["VIN","VOUT","GND","EN","FB","SW","BOOT"]),
    # DDR3 VDDQ VRM — TPS54231 step-down
    ("U_VRM3", "ic", 80, 385, 55, 40, "TPS54231", "TPS54231DR", "", "SOIC-8",
     ["VIN","VOUT","GND","EN","FB","SS","COMP","PH"]),
    # IO 3.3V VRM — TPS54331 step-down
    ("U_VRM4", "ic", 80, 560, 55, 40, "TPS54331", "TPS54331DR", "", "SOIC-8",
     ["VIN","VOUT","GND","EN","FB","SS","COMP","PH"]),
    # MOSFETs — high-side / low-side for each VRM phase
    ("Q1", "ic", 260, 105, 28, 22, "BSC014N", "BSC014N04LS", "", "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q2", "ic", 295, 105, 28, 22, "BSC014N", "BSC014N04LS", "", "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q3", "ic", 330, 105, 28, 22, "BSC014N", "BSC014N04LS", "", "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q4", "ic", 365, 105, 28, 22, "BSC014N", "BSC014N04LS", "", "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q5", "ic", 770, 105, 28, 22, "BSC014N", "BSC014N04LS", "", "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q6", "ic", 805, 105, 28, 22, "BSC014N", "BSC014N04LS", "", "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q7", "ic", 60, 425, 28, 22, "BSC014N", "BSC014N04LS", "", "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    ("Q8", "ic", 60, 600, 28, 22, "BSC014N", "BSC014N04LS", "", "TDSON-8",
     ["GATE","DRAIN","SOURCE","GND"]),
    # VRM output inductors
    ("L_VRM1", "inductor", 330, 60, 42, 36, "0.47uH", "", "0.47uH", "1210", ["1","2"]),
    ("L_VRM2", "inductor", 840, 60, 42, 36, "0.68uH", "", "0.68uH", "1210", ["1","2"]),
    ("L_VRM3", "inductor", 140, 385, 42, 36, "1uH", "", "1uH", "1210", ["1","2"]),
    ("L_VRM4", "inductor", 140, 560, 42, 36, "2.2uH", "", "2.2uH", "1210", ["1","2"]),

    # -----------------------------------------------------------------------
    # Network PHY / switch (U_NET1-U_NET2)
    # -----------------------------------------------------------------------
    # Intel i350-AM4 quad GbE PHY (second, for ports 5-8)
    ("U_NET1", "ic", 1100, 480, 140, 120, "I350-AM4", "I350-AM4", "", "BGA-576",
     ["VCC","GND","P0_TX","P0_RX","P1_TX","P1_RX","P2_TX","P2_RX","P3_TX","P3_RX",
      "PCIE_TX","PCIE_RX","MDIO","MDC","LED0","LED1"]),
    # Marvell 88E6176 managed switch fabric
    ("U_NET2", "ic", 1100, 360, 140, 100, "88E6176", "88E6176-TFJ2", "", "QFP-176",
     ["VCC","GND","P0_TX","P0_RX","P1_TX","P1_RX","P2_TX","P2_RX","P3_TX","P3_RX",
      "MDIO","MDC","RESET","LED0","LED1"]),

    # -----------------------------------------------------------------------
    # Network decoupling and magnetics (C_NET1-C_NET16, FL1-FL8)
    # -----------------------------------------------------------------------
    # Decoupling for I354 (U8)
    ("C_NET1", "capacitor", 880, 470, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_NET2", "capacitor", 880, 495, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_NET3", "capacitor", 880, 520, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_NET4", "capacitor", 880, 545, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    # Decoupling for I350-AM4 (U_NET1)
    ("C_NET5", "capacitor", 1080, 475, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_NET6", "capacitor", 1080, 500, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_NET7", "capacitor", 1080, 525, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_NET8", "capacitor", 1080, 550, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    # Decoupling for 88E6176 (U_NET2)
    ("C_NET9", "capacitor", 1080, 355, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_NET10","capacitor", 1080, 380, 24, 14, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_NET11","capacitor", 1250, 365, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_NET12","capacitor", 1250, 390, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    # RJ45 magnetics-side decoupling (bulk)
    ("C_NET13","capacitor", 850, 780, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_NET14","capacitor", 1010, 780, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_NET15","capacitor", 1170, 780, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_NET16","capacitor", 1330, 780, 24, 14, "100nF", "", "100nF", "0402", ["1","2"]),
    # Ethernet magnetic modules (FL1-FL8) — one per GbE port
    ("FL1", "inductor", 850, 750, 36, 28, "HX1198", "", "", "SOP-16", ["TX+","TX-","RX+","RX-"]),
    ("FL2", "inductor", 930, 750, 36, 28, "HX1198", "", "", "SOP-16", ["TX+","TX-","RX+","RX-"]),
    ("FL3", "inductor", 1010, 750, 36, 28, "HX1198", "", "", "SOP-16", ["TX+","TX-","RX+","RX-"]),
    ("FL4", "inductor", 1090, 750, 36, 28, "HX1198", "", "", "SOP-16", ["TX+","TX-","RX+","RX-"]),
    ("FL5", "inductor", 1170, 750, 36, 28, "HX1198", "", "", "SOP-16", ["TX+","TX-","RX+","RX-"]),
    ("FL6", "inductor", 1250, 750, 36, 28, "HX1198", "", "", "SOP-16", ["TX+","TX-","RX+","RX-"]),
    ("FL7", "inductor", 1330, 750, 36, 28, "HX1198", "", "", "SOP-16", ["TX+","TX-","RX+","RX-"]),
    ("FL8", "inductor", 1410, 750, 36, 28, "HX1198", "", "", "SOP-16", ["TX+","TX-","RX+","RX-"]),

    # -----------------------------------------------------------------------
    # SPI flash decoupling (C_SPI1-C_SPI4) — around W25Q128JV
    # -----------------------------------------------------------------------
    ("C_SPI1", "capacitor", 930, 195, 22, 12, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_SPI2", "capacitor", 1015, 195, 22, 12, "100nF", "", "100nF", "0402", ["1","2"]),
    ("C_SPI3", "capacitor", 1015, 215, 22, 12, "10uF", "", "10uF", "0805", ["1","2"]),
    ("C_SPI4", "capacitor", 1015, 235, 22, 12, "100nF", "", "100nF", "0402", ["1","2"]),

    # -----------------------------------------------------------------------
    # Boot flash (U_BOOT1) — eUSB boot module (redundant)
    # -----------------------------------------------------------------------
    ("U_BOOT1", "ic", 450, 650, 70, 45, "eUSB 4GB", "SATADOM-SH", "4GB", "eUSB",
     ["VCC","GND","USB_DP","USB_DN"]),

    # -----------------------------------------------------------------------
    # Clock / PLL (U_CLK1-U_CLK2, Y_CLK1-Y_CLK2)
    # -----------------------------------------------------------------------
    # IDT 5V49EE504 clock generator — CPU, FPGA, PCIe ref clocks
    ("U_CLK1", "ic", 530, 140, 55, 40, "5V49EE504", "5V49EE504", "", "QFN-32",
     ["VCC","GND","CLK_OUT0","CLK_OUT1","CLK_OUT2","CLK_OUT3","REF_IN","SDA","SCL"]),
    # SI5351 programmable clock — low-jitter PLL for GbE
    ("U_CLK2", "ic", 1300, 480, 50, 35, "SI5351A", "SI5351A-B-GT", "", "MSOP-10",
     ["VCC","GND","CLK0","CLK1","CLK2","XTAL_IN","XTAL_OUT","SDA","SCL"]),
    # 25MHz crystal for CPU PLL
    ("Y_CLK1", "crystal", 530, 190, 44, 22, "25MHz", "ABLS-25.000MHZ", "25MHz", "HC-49S",
     ["1","2","GND","GND2"]),
    # 50MHz crystal for clock generator
    ("Y_CLK2", "crystal", 600, 140, 44, 22, "50MHz", "ABLS-50.000MHZ", "50MHz", "HC-49S",
     ["1","2","GND","GND2"]),

    # -----------------------------------------------------------------------
    # Power management (U_PM1-U_PM2) — PMIC, power sequencer
    # -----------------------------------------------------------------------
    # LTC2977 8-channel power manager
    ("U_PM1", "ic", 160, 60, 65, 45, "LTC2977", "LTC2977", "", "QFN-64",
     ["VCC","GND","V1","V2","V3","V4","V5","V6","V7","V8","PGOOD","ALERT","SDA","SCL"]),
    # UCD9090A power sequencer / monitor
    ("U_PM2", "ic", 160, 110, 60, 40, "UCD9090A", "UCD9090ARGCT", "", "QFN-40",
     ["VCC","GND","MON1","MON2","MON3","MON4","EN1","EN2","EN3","EN4","PMBUS_SDA","PMBUS_SCL"]),

    # -----------------------------------------------------------------------
    # Reset supervisor (U_RST1)
    # -----------------------------------------------------------------------
    ("U_RST1", "ic", 600, 60, 40, 28, "TPS3808", "TPS3808G01", "", "SOT-23-6",
     ["VDD","GND","CT","MR","RESET","SENSE"]),

    # -----------------------------------------------------------------------
    # ESD protection (D1-D8) — TVS on USB, console, network ports
    # -----------------------------------------------------------------------
    ("D1", "ic", 580, 780, 32, 18, "USBLC6", "USBLC6-2SC6", "", "SOT-23-6",
     ["IO1","GND","IO2","IO2B","VCC","IO1B"]),
    ("D2", "ic", 500, 780, 32, 18, "USBLC6", "USBLC6-2SC6", "", "SOT-23-6",
     ["IO1","GND","IO2","IO2B","VCC","IO1B"]),
    ("D3", "ic", 680, 780, 32, 18, "PRTR5V0", "PRTR5V0U2X", "", "SOT-143",
     ["IO1","GND","IO2","VCC"]),
    ("D4", "ic", 1490, 780, 32, 18, "PRTR5V0", "PRTR5V0U2X", "", "SOT-143",
     ["IO1","GND","IO2","VCC"]),
    ("D5", "ic", 830, 780, 32, 18, "SRV05", "SRV05-4HTG", "", "SOT-23-6",
     ["IO1","IO2","GND","IO3","IO4","VCC"]),
    ("D6", "ic", 1090, 780, 32, 18, "SRV05", "SRV05-4HTG", "", "SOT-23-6",
     ["IO1","IO2","GND","IO3","IO4","VCC"]),
    ("D7", "ic", 1330, 780, 32, 18, "SRV05", "SRV05-4HTG", "", "SOT-23-6",
     ["IO1","IO2","GND","IO3","IO4","VCC"]),
    ("D8", "ic", 630, 118, 32, 18, "PRTR5V0", "PRTR5V0U2X", "", "SOT-143",
     ["IO1","GND","IO2","VCC"]),

    # -----------------------------------------------------------------------
    # Status LEDs (D_LED1-D_LED4)
    # -----------------------------------------------------------------------
    ("D_LED1", "resistor", 1380, 920, 18, 12, "PWR", "", "GREEN", "0805", ["A","K"]),
    ("D_LED2", "resistor", 1410, 920, 18, 12, "STATUS", "", "AMBER", "0805", ["A","K"]),
    ("D_LED3", "resistor", 1440, 920, 18, 12, "ACT", "", "GREEN", "0805", ["A","K"]),
    ("D_LED4", "resistor", 1470, 920, 18, 12, "ALARM", "", "RED", "0805", ["A","K"]),

    # -----------------------------------------------------------------------
    # Additional test points (TP_NEW1-TP_NEW10) — power, debug, signal
    # -----------------------------------------------------------------------
    ("TP_NEW1", "test_point", 340, 60, 12, 12, "VCORE", "", "", "TP", ["1"]),
    ("TP_NEW2", "test_point", 360, 60, 12, 12, "1V0", "", "", "TP", ["1"]),
    ("TP_NEW3", "test_point", 380, 60, 12, 12, "3V3", "", "", "TP", ["1"]),
    ("TP_NEW4", "test_point", 860, 60, 12, 12, "VTT", "", "", "TP", ["1"]),
    ("TP_NEW5", "test_point", 880, 60, 12, 12, "1V8", "", "", "TP", ["1"]),
    ("TP_NEW6", "test_point", 1300, 300, 12, 12, "PCIE_CLK", "", "", "TP", ["1"]),
    ("TP_NEW7", "test_point", 1320, 300, 12, 12, "MDIO", "", "", "TP", ["1"]),
    ("TP_NEW8", "test_point", 1340, 300, 12, 12, "SPI_CLK", "", "", "TP", ["1"]),
    ("TP_NEW9", "test_point", 550, 700, 12, 12, "UART_TX", "", "", "TP", ["1"]),
    ("TP_NEW10","test_point", 570, 700, 12, 12, "UART_RX", "", "", "TP", ["1"]),

    # -----------------------------------------------------------------------
    # Pull-up / termination resistors (R_NEW1-R_NEW20)
    # -----------------------------------------------------------------------
    # I2C pull-ups for PMBUS / clock gen
    ("R_NEW1", "resistor", 230, 60, 26, 12, "4k7", "", "4k7", "0402", ["A","B"]),
    ("R_NEW2", "resistor", 230, 78, 26, 12, "4k7", "", "4k7", "0402", ["A","B"]),
    # DDR3 termination resistors (per channel)
    ("R_NEW3", "resistor", 260, 190, 26, 12, "49.9", "", "49.9", "0402", ["A","B"]),
    ("R_NEW4", "resistor", 260, 370, 26, 12, "49.9", "", "49.9", "0402", ["A","B"]),
    ("R_NEW5", "resistor", 260, 510, 26, 12, "49.9", "", "49.9", "0402", ["A","B"]),
    ("R_NEW6", "resistor", 260, 650, 26, 12, "49.9", "", "49.9", "0402", ["A","B"]),
    # SPI flash pull-ups (CS, HOLD, WP)
    ("R_NEW7", "resistor", 1020, 200, 26, 12, "10k", "", "10k", "0402", ["A","B"]),
    ("R_NEW8", "resistor", 1020, 218, 26, 12, "10k", "", "10k", "0402", ["A","B"]),
    ("R_NEW9", "resistor", 1020, 236, 26, 12, "10k", "", "10k", "0402", ["A","B"]),
    # JTAG pull-ups (TMS, TRST)
    ("R_NEW10","resistor", 635, 118, 26, 12, "10k", "", "10k", "0402", ["A","B"]),
    ("R_NEW11","resistor", 738, 118, 26, 12, "10k", "", "10k", "0402", ["A","B"]),
    # Reset supervisor threshold resistors
    ("R_NEW12","resistor", 600, 95, 26, 12, "100k", "", "100k", "0402", ["A","B"]),
    ("R_NEW13","resistor", 640, 95, 26, 12, "47k", "", "47k", "0402", ["A","B"]),
    # LED current limiters
    ("R_NEW14","resistor", 1380, 940, 26, 12, "330", "", "330", "0402", ["A","B"]),
    ("R_NEW15","resistor", 1410, 940, 26, 12, "330", "", "330", "0402", ["A","B"]),
    ("R_NEW16","resistor", 1440, 940, 26, 12, "330", "", "330", "0402", ["A","B"]),
    ("R_NEW17","resistor", 1470, 940, 26, 12, "330", "", "330", "0402", ["A","B"]),
    # Network MDIO pull-ups
    ("R_NEW18","resistor", 1250, 480, 26, 12, "4k7", "", "4k7", "0402", ["A","B"]),
    ("R_NEW19","resistor", 1250, 498, 26, 12, "4k7", "", "4k7", "0402", ["A","B"]),
    # Clock generator filter resistor
    ("R_NEW20","resistor", 530, 120, 26, 12, "1k", "", "1k", "0402", ["A","B"]),
]
# fmt: on

CISCO_TRACE_ROUTES: list[tuple[list[tuple[int, int]], int]] = [
    # CPU (U1) ↔ DDR3 data bus (4 channels)
    ([(420, 350), (250, 350), (250, 250)], 3),   # DDR Ch0 → U2
    ([(420, 380), (250, 380), (250, 430)], 3),   # DDR Ch1 → U3
    ([(420, 450), (250, 450), (250, 570)], 3),   # DDR Ch2 → U4
    ([(420, 500), (250, 500), (250, 710)], 3),   # DDR Ch3 → U5
    # CPU (U1) → Trust Anchor FPGA (U6) — processor reset + verify
    ([(680, 350), (750, 350), (750, 300)], 3),   # PROC_RST
    ([(680, 370), (770, 370), (770, 300)], 3),   # PROC_CLK
    ([(680, 390), (790, 390), (790, 300)], 2),   # TRUST_VERIFY
    ([(680, 410), (810, 410), (810, 300)], 2),   # TRUST_STATUS
    # FPGA (U6) → SPI flash (U7) — bitstream load (UNENCRYPTED — Thrangrycat)
    ([(910, 230), (950, 230), (950, 218)], 2),   # SPI_CLK
    ([(910, 250), (960, 250), (960, 230)], 2),   # SPI_MOSI (DI)
    ([(910, 270), (970, 270), (970, 218)], 2),   # SPI_MISO (DO)
    ([(910, 210), (950, 210), (950, 200)], 2),   # SPI_CS
    # CPU (U1) → Intel I354 (U8) — PCIe x4 link
    ([(680, 430), (900, 430), (900, 480)], 4),   # PCIE_TX
    ([(680, 450), (920, 450), (920, 480)], 4),   # PCIE_RX
    # I354 (U8) → GbE ports (J1-J4) — first 4 ports
    ([(1050, 540), (1050, 800)], 3),             # Port 1
    ([(1050, 560), (970,  560), (970,  800)], 3),# Port 2
    ([(1050, 580), (890,  580), (890,  800)], 3),# Port 3
    ([(1050, 600), (810,  600), (810,  800)], 3),# Port 4 (approximate)
    # CPU (U1) integrated GbE → ports J5-J8 (SoC's built-in 4x GbE)
    ([(680, 470), (1210, 470), (1210, 800)], 3), # GbE0 → J5
    ([(680, 490), (1290, 490), (1290, 800)], 3), # GbE1 → J6
    ([(680, 510), (1370, 510), (1370, 800)], 3), # GbE2 → J7
    ([(680, 530), (1450, 530), (1450, 800)], 3), # GbE3 → J8
    # CPU (U1) → MGMT port (J11) via separate MAC
    ([(680, 340), (1490, 340), (1490, 800)], 3),
    # CPU (U1) → eUSB flash (U9) — firmware storage
    ([(420, 530), (350, 530), (350, 650)], 2),   # USB_DP
    ([(420, 540), (370, 540), (370, 675)], 2),   # USB_DN
    # CPU (U1) → mSATA SSD (J6) — SATA for FirePOWER storage
    ([(420, 510), (300, 510), (300, 790)], 3),   # SATA_TX
    ([(420, 520), (280, 520), (280, 810)], 3),   # SATA_RX
    # CPU (U1) → Console (J10) via UART
    ([(420, 420), (400, 420), (400, 700), (700, 700), (700, 800)], 2),  # UART_TX
    ([(420, 430), (380, 430), (380, 720), (720, 720), (720, 800)], 2),  # UART_RX
    # CPU (U1) → USB ports (J12, J13)
    ([(420, 440), (360, 440), (360, 740), (600, 740), (600, 800)], 2),  # USB_A
    ([(420, 460), (340, 460), (340, 760), (520, 760), (520, 800)], 2),  # USB_Mini
    # JTAG header (J15) → CPU debug pins
    ([(650, 160), (500, 160), (500, 280)], 2),   # TDI
    ([(660, 160), (490, 160), (490, 280)], 2),   # TDO
    ([(670, 160), (480, 160), (480, 280)], 2),   # TCK
    ([(680, 160), (470, 160), (470, 280)], 2),   # TMS
    # VRM: TPS54331 (U10) → power rails
    ([(140, 121), (420, 121), (420, 280)], 5),   # 3.3V rail → CPU area
    # VRM: NCP5232 (U11) → CPU core
    ([(370, 161), (420, 161), (420, 280)], 5),   # Vcore → CPU
    # VRM: TPS51200 (U12) → DDR3
    ([(130, 476), (130, 430)], 4),               # VTT → RAM
    # DC power (J14) → VRMs
    ([(110, 830), (110, 142), (80, 142)], 5),    # 12V → TPS54331
    # Crystal (Y1) → CPU ref clock
    ([(398, 582), (420, 582), (420, 540)], 2),
    # R182 (AVR54 rework location) — LPC clock fix resistor
    ([(830, 136), (680, 136), (680, 280)], 1),   # LPC_CLK fix path

    # -----------------------------------------------------------------------
    # VRM section traces — power delivery to CPU, FPGA, DDR3, IO
    # -----------------------------------------------------------------------
    # CPU core VRM (U_VRM1) → output inductor L_VRM1 → CPU
    ([(325, 80), (372, 80), (420, 280)], 5),     # Vcore → CPU
    # U_VRM1 → MOSFET gates Q1-Q4
    ([(270, 80), (260, 105)], 2),                # VRM1 → Q1
    ([(280, 80), (295, 105)], 2),                # VRM1 → Q2
    ([(290, 80), (330, 105)], 2),                # VRM1 → Q3
    ([(300, 80), (365, 105)], 2),                # VRM1 → Q4
    # FPGA VRM (U_VRM2) → L_VRM2 → FPGA
    ([(835, 80), (882, 80), (750, 160)], 4),     # Vfpga → FPGA
    # U_VRM2 → MOSFETs Q5-Q6
    ([(780, 80), (770, 105)], 2),                # VRM2 → Q5
    ([(790, 80), (805, 105)], 2),                # VRM2 → Q6
    # DDR3 VRM (U_VRM3) → L_VRM3 → DDR3 rail
    ([(135, 403), (182, 403), (182, 350), (130, 250)], 4),  # VDDQ → DDR3
    # U_VRM3 → Q7
    ([(80, 405), (60, 425)], 2),                 # VRM3 → Q7
    # IO VRM (U_VRM4) → L_VRM4 → IO rail
    ([(135, 580), (182, 580), (182, 540), (420, 540)], 4),  # 3.3V → CPU IO
    # U_VRM4 → Q8
    ([(80, 580), (60, 600)], 2),                 # VRM4 → Q8
    # DC power → VRM inputs (12V distribution)
    ([(110, 830), (110, 60), (160, 60)], 5),     # 12V → U_PM1
    ([(160, 80), (270, 80)], 4),                 # PM → CPU VRM
    ([(160, 80), (780, 60)], 4),                 # PM → FPGA VRM

    # -----------------------------------------------------------------------
    # Network switch fabric traces
    # -----------------------------------------------------------------------
    # I354 (U8) → switch fabric (U_NET2) — MDIO management
    ([(1050, 520), (1100, 520), (1100, 460)], 2),# MDIO
    # Switch fabric (U_NET2) → I350 (U_NET1) — inter-switch link
    ([(1100, 460), (1100, 480)], 3),             # ISL data
    # I350 (U_NET1) → GbE ports J5-J8 via magnetics
    ([(1240, 540), (1210, 540), (1210, 750)], 3),# NET1 → FL5 → J5
    ([(1240, 560), (1290, 560), (1290, 750)], 3),# NET1 → FL6 → J7
    ([(1240, 580), (1370, 580), (1370, 750)], 3),# NET1 → FL7 → J8
    ([(1240, 600), (1450, 600), (1450, 750)], 3),# NET1 → FL8 → J9
    # Magnetics FL1-FL4 → GbE ports J1-J4
    ([(886, 764), (886, 800)], 3),               # FL1 → J1
    ([(966, 764), (966, 800)], 3),               # FL2 → J2
    ([(1046, 764), (1046, 800)], 3),             # FL3 → J3
    ([(1126, 764), (1126, 800)], 3),             # FL4 → J4

    # -----------------------------------------------------------------------
    # Clock generator traces
    # -----------------------------------------------------------------------
    # Clock gen (U_CLK1) → CPU ref clock
    ([(585, 160), (420, 160), (420, 280)], 2),   # CLK_OUT0 → CPU
    # Clock gen (U_CLK1) → FPGA ref clock
    ([(585, 170), (750, 170), (750, 160)], 2),   # CLK_OUT1 → FPGA
    # SI5351 (U_CLK2) → I354 (U8) ref clock
    ([(1300, 497), (1050, 497), (1050, 480)], 2),# CLK2 → I354
    # SI5351 (U_CLK2) → I350 (U_NET1) ref clock
    ([(1300, 507), (1240, 507), (1240, 480)], 2),# CLK2 → I350

    # -----------------------------------------------------------------------
    # Power management traces
    # -----------------------------------------------------------------------
    # LTC2977 (U_PM1) → VRM enable signals
    ([(225, 75), (270, 75)], 2),                 # PGOOD → CPU VRM
    ([(225, 85), (780, 65)], 2),                 # PGOOD → FPGA VRM
    # UCD9090A (U_PM2) → monitored rails
    ([(220, 130), (300, 130), (300, 140)], 2),   # MON → CPU VRM
    ([(220, 140), (420, 280)], 2),               # MON → CPU

    # -----------------------------------------------------------------------
    # Reset supervisor traces
    # -----------------------------------------------------------------------
    # TPS3808 (U_RST1) → CPU reset pin
    ([(640, 74), (680, 74), (680, 280)], 2),     # RESET → CPU

    # -----------------------------------------------------------------------
    # ESD protection traces
    # -----------------------------------------------------------------------
    ([(580, 789), (600, 800)], 2),               # D1 → USB-A (J12)
    ([(500, 789), (520, 800)], 2),               # D2 → USB Mini-B (J13)
    ([(680, 789), (700, 800)], 2),               # D3 → Console (J10)
    ([(1490, 789), (1490, 800)], 2),             # D4 → MGMT (J11)
    ([(830, 789), (850, 800)], 2),               # D5 → GbE-1 (J1)
    ([(1090, 789), (1090, 800)], 2),             # D6 → GbE-4 (J4)
    ([(1330, 789), (1330, 800)], 2),             # D7 → GbE-7 (J8)
    ([(630, 136), (650, 136)], 2),               # D8 → JTAG (J15)

    # -----------------------------------------------------------------------
    # Boot flash trace
    # -----------------------------------------------------------------------
    ([(450, 672), (420, 672), (420, 540)], 2),   # U_BOOT1 → CPU USB

    # -----------------------------------------------------------------------
    # LED traces from CPU GPIO
    # -----------------------------------------------------------------------
    ([(680, 300), (1380, 300), (1380, 920)], 2), # PWR LED
    ([(680, 310), (1410, 310), (1410, 920)], 2), # STATUS LED
    ([(680, 320), (1440, 320), (1440, 920)], 2), # ACT LED
    ([(680, 330), (1470, 330), (1470, 920)], 2), # ALARM LED
]

CISCO_TRACE_ENDPOINTS: list[tuple[str, str]] = [
    ("U1","U2"), ("U1","U3"), ("U1","U4"), ("U1","U5"),  # DDR3
    ("U1","U6"), ("U1","U6"), ("U1","U6"), ("U1","U6"),  # CPU↔FPGA
    ("U6","U7"), ("U6","U7"), ("U6","U7"), ("U6","U7"),  # FPGA↔SPI flash
    ("U1","U8"), ("U1","U8"),                             # CPU↔I354 PCIe
    ("U8","J1"), ("U8","J2"), ("U8","J3"), ("U8","J4"),  # I354→ports 1-4
    ("U1","J5"), ("U1","J7"), ("U1","J8"), ("U1","J9"),  # SoC→ports 5-8
    ("U1","J11"),                                         # MGMT port
    ("U1","U9"), ("U1","U9"),                             # CPU→eUSB
    ("U1","J6"), ("U1","J6"),                             # CPU→mSATA
    ("U1","J10"), ("U1","J10"),                           # CPU→Console UART
    ("U1","J12"), ("U1","J13"),                           # CPU→USB ports
    ("J15","U1"), ("J15","U1"), ("J15","U1"), ("J15","U1"),  # JTAG→CPU
    ("U10","U1"), ("U11","U1"), ("U12","U2"),             # VRMs→targets
    ("J14","U10"),                                        # DC power→VRM
    ("Y1","U1"),                                          # Crystal→CPU
    ("TP4","U1"),                                         # AVR54 rework
    # VRM section traces
    ("U_VRM1","U1"),                                      # CPU core VRM → CPU
    ("U_VRM1","Q1"), ("U_VRM1","Q2"), ("U_VRM1","Q3"), ("U_VRM1","Q4"),  # VRM1 → MOSFETs
    ("U_VRM2","U6"),                                      # FPGA VRM → FPGA
    ("U_VRM2","Q5"), ("U_VRM2","Q6"),                     # VRM2 → MOSFETs
    ("U_VRM3","U2"),                                      # DDR3 VRM → DDR3
    ("U_VRM3","Q7"),                                      # VRM3 → MOSFET
    ("U_VRM4","U1"),                                      # IO VRM → CPU IO
    ("U_VRM4","Q8"),                                      # VRM4 → MOSFET
    ("J14","U_PM1"), ("U_PM1","U_VRM1"), ("U_PM1","U_VRM2"),  # DC → PM → VRMs
    # Network switch fabric traces
    ("U8","U_NET2"),                                      # I354 → switch MDIO
    ("U_NET2","U_NET1"),                                  # switch → I350 ISL
    ("U_NET1","J5"), ("U_NET1","J7"), ("U_NET1","J8"), ("U_NET1","J9"),  # I350 → ports
    ("FL1","J1"), ("FL2","J2"), ("FL3","J3"), ("FL4","J4"),  # magnetics → ports
    # Clock traces
    ("U_CLK1","U1"), ("U_CLK1","U6"),                     # clk gen → CPU, FPGA
    ("U_CLK2","U8"), ("U_CLK2","U_NET1"),                 # SI5351 → NICs
    # Power management traces
    ("U_PM1","U_VRM1"), ("U_PM1","U_VRM2"),               # PM PGOOD → VRMs
    ("U_PM2","U_VRM1"), ("U_PM2","U1"),                   # sequencer → VRM/CPU
    # Reset supervisor
    ("U_RST1","U1"),                                      # reset → CPU
    # ESD protection
    ("D1","J12"), ("D2","J13"), ("D3","J10"), ("D4","J11"),  # ESD → connectors
    ("D5","J1"), ("D6","J4"), ("D7","J8"), ("D8","J15"),  # ESD → ports/JTAG
    # Boot flash
    ("U_BOOT1","U1"),                                     # boot flash → CPU
    # LEDs
    ("U1","D_LED1"), ("U1","D_LED2"), ("U1","D_LED3"), ("U1","D_LED4"),  # CPU → LEDs
]

CISCO_VIAS: list[tuple[int, int, int, int]] = [
    # CPU power plane stitching
    (400,260,5,2),(430,260,5,2),(460,260,5,2),(490,260,5,2),
    (520,260,5,2),(550,260,5,2),(580,260,5,2),(610,260,5,2),
    (640,260,5,2),(670,260,5,2),
    # CPU bottom edge
    (400,560,5,2),(440,560,5,2),(480,560,5,2),(520,560,5,2),
    (560,560,5,2),(600,560,5,2),(640,560,5,2),(680,560,5,2),
    # DDR bus transition vias
    (260,300,6,3),(260,420,6,3),(260,560,6,3),(260,700,6,3),
    # FPGA area
    (740,150,5,2),(780,150,5,2),(820,150,5,2),(860,150,5,2),(900,150,5,2),
    # I354 area
    (880,470,5,2),(920,470,5,2),(960,470,5,2),(1000,470,5,2),(1040,470,5,2),
    # VRM area
    (160,140,6,3),(160,480,6,3),
    # Ground stitching near RJ45s
    (900,780,5,2),(960,780,5,2),(1020,780,5,2),(1080,780,5,2),
    (1140,780,5,2),(1200,780,5,2),(1260,780,5,2),(1320,780,5,2),
    # VRM section vias — power plane transitions
    (300,90,6,3),(330,90,6,3),(360,90,6,3),(390,90,6,3),
    (810,90,6,3),(840,90,6,3),(870,90,6,3),
    (100,400,5,2),(140,400,5,2),(180,400,5,2),
    (100,575,5,2),(140,575,5,2),(180,575,5,2),
    # MOSFET drain/source vias
    (274,130,5,2),(309,130,5,2),(344,130,5,2),(379,130,5,2),
    (784,130,5,2),(819,130,5,2),
    (74,450,5,2),(74,625,5,2),
    # I350 / switch fabric area vias
    (1090,470,5,2),(1130,470,5,2),(1170,470,5,2),(1210,470,5,2),
    (1090,360,5,2),(1130,360,5,2),(1170,360,5,2),(1210,360,5,2),
    (1250,360,5,2),
    # Clock generator area vias
    (550,155,5,2),(570,155,5,2),(590,155,5,2),(610,155,5,2),
    # Power management area vias
    (190,75,5,2),(210,75,5,2),(230,75,5,2),
    (190,125,5,2),(210,125,5,2),
    # Reset supervisor vias
    (620,75,5,2),(640,75,5,2),
    # ESD protection area vias
    (590,790,5,2),(510,790,5,2),(690,790,5,2),(840,790,5,2),
    (1100,790,5,2),(1340,790,5,2),(1500,790,5,2),
    # SPI flash area vias
    (940,200,5,2),(960,200,5,2),(980,200,5,2),
    # LED area vias
    (1380,900,5,2),(1410,900,5,2),(1440,900,5,2),(1470,900,5,2),
    # Ground stitching — magnetics area
    (870,740,5,2),(950,740,5,2),(1030,740,5,2),(1110,740,5,2),
    (1190,740,5,2),(1270,740,5,2),(1350,740,5,2),(1430,740,5,2),
    # Boot flash area
    (460,670,5,2),(480,670,5,2),
    # Test point area vias
    (350,75,5,2),(370,75,5,2),(870,75,5,2),(890,75,5,2),
    (1310,310,5,2),(1330,310,5,2),
]

CISCO_MOUNTING_HOLES: list[tuple[int, int, int, int]] = [
    (30,30,14,8), (1570,30,14,8), (30,970,14,8), (1570,970,14,8),
    (550,500,12,7), (1100,500,12,7),
]

CISCO_SILK_LABELS: list[tuple[str, int, int]] = [
    ("U1",422,278),("U2",132,178),("U3",132,358),("U4",132,498),("U5",132,638),
    ("U6",752,158),("U7",952,198),("U8",902,478),("U9",352,648),
    ("U10",82,98),("U11",302,138),("U12",82,458),
    ("J1-J8",900,798),("CONSOLE",702,798),("MGMT",1492,798),
    ("J14 DC",52,798),("J15 JTAG",652,128),
    ("L1",202,108),("L2",62,458),("Y1",352,568),
    ("R182/AVR54",830,118),
    # VRM section labels
    ("U_VRM1",272,58),("U_VRM2",782,58),("U_VRM3",82,383),("U_VRM4",82,558),
    ("Q1-Q4",262,100),("Q5-Q6",772,100),("Q7",62,423),("Q8",62,598),
    ("L_VRM1",332,58),("L_VRM2",842,58),("L_VRM3",142,383),("L_VRM4",142,558),
    # Network labels
    ("U_NET1 I350",1102,478),("U_NET2 88E6176",1102,358),
    ("FL1-FL8",870,738),
    # Clock / PLL labels
    ("U_CLK1",532,138),("U_CLK2",1302,478),
    ("Y_CLK1",532,188),("Y_CLK2",602,138),
    # Power management labels
    ("U_PM1 LTC2977",162,58),("U_PM2 UCD9090A",162,108),
    # Reset supervisor
    ("U_RST1",602,58),
    # Boot flash
    ("U_BOOT1",452,648),
    # ESD protection
    ("D1",582,778),("D2",502,778),("D3",682,778),("D4",1492,778),
    ("D5",832,778),("D6",1092,778),("D7",1332,778),("D8",632,116),
    # LEDs
    ("D_LED1-4",1382,918),
    # Test points
    ("TP_NEW1-5",342,55),("TP_NEW6-8",1302,298),("TP_NEW9-10",552,698),
    # Board markings
    ("800-XXXXX-XX  V05",1300,970),
    ("Cisco ASA 5506-X — Synthetic Demo Only",350,970),
    ("TRUST ANCHOR",770,308),
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


def _draw_board_outline(img: np.ndarray, w: int = IMG_W, h: int = IMG_H) -> None:
    cv2.rectangle(img, (10, 10), (w - 10, h - 10), (0, 60, 0), 3)
    cv2.rectangle(img, (14, 14), (w - 14, h - 14), (0, 80, 20), 1)


def _draw_mounting_holes(img: np.ndarray, holes: list[tuple] | None = None) -> None:
    for x, y, ro, ri in (holes or MOUNTING_HOLES):
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


def _draw_traces(img: np.ndarray, routes: list[tuple] | None = None) -> None:
    for pts, width in (routes or TRACE_ROUTES):
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


def _draw_vias(img: np.ndarray, via_list: list[tuple] | None = None) -> None:
    for x, y, ro, ri in (via_list or VIAS):
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


def _draw_silkscreen(
    img: np.ndarray,
    labels: list[tuple] | None = None,
    title: str = "XBOX ONE 1540 (Durango) X877750-003",
    img_w: int = IMG_W,
    img_h: int = IMG_H,
) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    for text, tx, ty in (labels or SILK_LABELS):
        cv2.putText(img, text, (tx, ty), font, 0.38, (210, 215, 210), 1, cv2.LINE_AA)
    text_w = cv2.getTextSize(title, font, 0.52, 1)[0][0]
    cv2.putText(img, title, (img_w // 2 - text_w // 2, img_h - 25), font, 0.52, (200, 210, 200), 1, cv2.LINE_AA)


def generate_board_image(
    output_path: Path,
    img_w: int = IMG_W,
    img_h: int = IMG_H,
    components: list[tuple] | None = None,
    trace_routes: list[tuple] | None = None,
    vias: list[tuple] | None = None,
    mounting_holes: list[tuple] | None = None,
    silk_labels: list[tuple] | None = None,
    board_title: str = "XBOX ONE 1540 (Durango) X877750-003",
    seed: int = 42,
) -> None:
    """Render a synthetic PCB and save to output_path."""
    components = components or KNOWN_COMPONENTS
    trace_routes = trace_routes or TRACE_ROUTES
    vias = vias or VIAS
    mounting_holes = mounting_holes or MOUNTING_HOLES
    silk_labels = silk_labels or SILK_LABELS
    rng = np.random.default_rng(seed)

    base_green = np.full((img_h, img_w, 3), (38, 108, 38), dtype=np.uint8)

    grain = rng.integers(-12, 13, (img_h, img_w, 3), dtype=np.int16)
    img = np.clip(base_green.astype(np.int16) + grain, 0, 255).astype(np.uint8)

    weave_color = (35, 100, 35)
    for gy in range(0, img_h, 16):
        cv2.line(img, (0, gy), (img_w, gy), weave_color, 1)
    for gx in range(0, img_w, 16):
        cv2.line(img, (gx, 0), (gx, img_h), weave_color, 1)

    _draw_board_outline(img, img_w, img_h)
    _draw_mounting_holes(img, mounting_holes)

    # Ground pours
    cv2.rectangle(img, (50, 550), (460, 860), (25, 85, 110), -1)
    cv2.rectangle(img, (50, 550), (460, 860), (35, 95, 120), 1)
    cv2.putText(img, "GND", (60, 580), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 110, 140), 1)
    cv2.rectangle(img, (860, 550), (1380, 860), (25, 85, 110), -1)
    cv2.rectangle(img, (860, 550), (1380, 860), (35, 95, 120), 1)
    cv2.putText(img, "GND", (870, 580), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 110, 140), 1)

    _draw_traces(img, trace_routes)
    _draw_vias(img, vias)

    for entry in components:
        ref, label, x, y, w, h, marking, *_rest = entry
        _draw_component_footprint(img, ref, label, x, y, w, h, marking)

    _draw_silkscreen(img, silk_labels, board_title, img_w, img_h)

    fine_noise = rng.integers(-4, 5, (img_h, img_w, 3), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + fine_noise, 0, 255).astype(np.uint8)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), img)


# ---------------------------------------------------------------------------
# Build a synthetic AnalysisResult from the known component list
# ---------------------------------------------------------------------------

XBOX_TRACE_ENDPOINTS: list[tuple[str, str]] = [
    # Original 34 traces
    ("U1","U2"),("U1","U3"),("U1","U2"),("U1","U3"),("U1","U4"),("U1","U5"),
    ("U1","U6"),("U1","U6"),("U1","U12"),("U1","U12"),
    ("U6","U7"),("U6","U7"),("U6","U7"),("U6","U7"),
    ("U6","J2"),("U6","J2"),("U6","J3"),("U6","J3"),
    ("U10","U1"),("U10","U1"),("U11","U1"),("L1","U1"),("L2","U1"),
    ("U8","U6"),("U8","U6"),("U9","J4"),("U9","J4"),
    ("J5","U1"),("J5","U1"),("J5","U1"),("J5","U1"),
    ("U12","J1"),("U12","J1"),("Y1","U6"),
    # New DDR3 U13-U16 (4 traces)
    ("U1","U13"),("U1","U14"),("U1","U15"),("U1","U16"),
    # Power: DrMOS, PWM, buck, LDO, inductors (9 traces)
    ("U17","U1"),("U18","U1"),
    ("U19","U10"),("U20","U10"),
    ("U21","U1"),("U22","J1"),
    ("L3","U1"),("L4","U1"),("L5","U1"),
    # MOSFET gate drives (6 traces)
    ("U10","Q1"),("U10","Q2"),("U11","Q3"),("U11","Q4"),("U21","Q5"),("U21","Q6"),
    # ESD protection (6 traces)
    ("D3","J1"),("D1","J2"),("D2","J3"),("D4","J4"),("D5","U12"),("D6","J5"),
    # Connectors: SATA, ANT, IR, TOSLINK, DC power (5 traces)
    ("J6","U1"),("J7","U8"),("J8","U1"),("J9","U1"),("J10","U17"),
    # Status LEDs (4 traces)
    ("U1","D7"),("U1","D8"),("U1","D9"),("U1","D10"),
]


XBOX_ZONES: list[tuple[str, str, list[str]]] = [
    ("APU Complex", "cpu", ["U1"]),
    ("DDR3 Memory Bank A", "memory", ["U2", "U3", "U13", "U14",
     "C15", "C16", "C17", "C18", "C23", "C24", "C25", "C26",
     "R13", "R14", "R15", "R16"]),
    ("DDR3 Memory Bank B", "memory", ["U4", "U5", "U15", "U16",
     "C19", "C20", "C21", "C22", "C27", "C28", "C29", "C30"]),
    ("Power Delivery", "power", ["U10", "U11", "U17", "U18", "U19", "U20", "U21",
     "L1", "L2", "L3", "L4", "L5",
     "Q1", "Q2", "Q3", "Q4", "Q5", "Q6",
     "C39", "C40", "C41", "C42", "C43", "C44",
     "C51", "C52", "C53", "C54", "J10"]),
    ("HDMI Output", "io", ["U6", "U12", "U22", "J1",
     "C31", "C32", "C45", "C46", "C47",
     "R4", "R5", "R6", "R7",
     "D3", "D5"]),
    ("Storage", "storage", ["U7", "J6", "C33", "C34", "C56", "R23"]),
    ("Wireless / Networking", "network", ["U8", "U9", "J4", "J7",
     "C35", "C36", "C37", "C38", "C55", "D4",
     "R21", "R22", "R24"]),
    ("USB Subsystem", "io", ["J2", "J3", "D1", "D2",
     "R8", "R9", "R10", "R11"]),
    ("Debug / JTAG", "debug", ["J5", "D6",
     "TP1", "TP2", "TP3", "TP4", "TP5", "TP6", "TP7"]),
    ("APU Decoupling", "power", ["C1", "C2", "C3", "C4", "C5", "C6",
     "C7", "C8", "C9", "C10",
     "C11", "C12", "C13", "C14", "C50", "R1", "R2", "R3", "R12", "R25",
     "C48", "C49", "Y1"]),
    ("Front Panel", "io", ["J8", "J9",
     "D7", "D8", "D9", "D10",
     "R17", "R18", "R19", "R20"]),
    ("Power Rail Test Points", "debug", ["TP8", "TP9",
     "TP10", "TP11", "TP12", "TP13", "TP14", "TP15"]),
]

CISCO_ZONES: list[tuple[str, str, list[str]]] = [
    ("Intel Atom C2508 CPU", "cpu", ["U1",
     "C_CPU1", "C_CPU2", "C_CPU3", "C_CPU4", "C_CPU5", "C_CPU6", "C_CPU7",
     "C_CPU8", "C_CPU9", "C_CPU10", "C_CPU11", "C_CPU12", "C_CPU13", "C_CPU14",
     "C_CPU15", "C_CPU16", "C_CPU17", "C_CPU18", "C_CPU19", "C_CPU20"]),
    ("DDR3 ECC Memory", "memory", ["U2", "U3", "U4", "U5",
     "C_DDR1", "C_DDR2", "C_DDR3", "C_DDR4", "C_DDR5", "C_DDR6", "C_DDR7", "C_DDR8",
     "R_NEW3", "R_NEW4", "R_NEW5", "R_NEW6"]),
    ("Trust Anchor Module", "debug", ["U6", "U7",
     "C_FPGA1", "C_FPGA2", "C_FPGA3", "C_FPGA4", "C_FPGA5",
     "C_FPGA6", "C_FPGA7", "C_FPGA8", "C_FPGA9", "C_FPGA10",
     "C_SPI1", "C_SPI2", "C_SPI3", "C_SPI4",
     "R_NEW7", "R_NEW8", "R_NEW9"]),
    ("Power Delivery", "power", ["U10", "U11", "U12", "L1", "L2",
     "U_VRM1", "U_VRM2", "U_VRM3", "U_VRM4",
     "Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8",
     "L_VRM1", "L_VRM2", "L_VRM3", "L_VRM4",
     "U_PM1", "U_PM2", "U_RST1",
     "TP_NEW1", "TP_NEW2", "TP_NEW3", "TP_NEW4", "TP_NEW5",
     "R_NEW1", "R_NEW2", "R_NEW12", "R_NEW13"]),
    ("Intel I354 NIC", "network", ["U8",
     "C_NET1", "C_NET2", "C_NET3", "C_NET4"]),
    ("Intel I350 / Switch Fabric", "network", ["U_NET1", "U_NET2",
     "C_NET5", "C_NET6", "C_NET7", "C_NET8",
     "C_NET9", "C_NET10", "C_NET11", "C_NET12",
     "R_NEW18", "R_NEW19"]),
    ("Data Plane Ports", "network", ["J1", "J2", "J3", "J4", "J5", "J7", "J8", "J9",
     "FL1", "FL2", "FL3", "FL4", "FL5", "FL6", "FL7", "FL8",
     "C_NET13", "C_NET14", "C_NET15", "C_NET16",
     "D5", "D6", "D7"]),
    ("Management / Console", "io", ["J10", "J11", "J12", "J13",
     "D1", "D2", "D3", "D4"]),
    ("Storage", "storage", ["U9", "J6", "U_BOOT1"]),
    ("JTAG Debug Chain", "debug", ["J15", "TP1", "TP2", "TP3", "TP4", "D8",
     "R_NEW10", "R_NEW11"]),
    ("DC Power Input", "power", ["J14"]),
    ("Clock / PLL", "io", ["U_CLK1", "U_CLK2", "Y_CLK1", "Y_CLK2", "Y1",
     "R_NEW20"]),
    ("CPU Decoupling", "power", ["C1", "C2", "C3", "C4", "C5", "C6"]),
    ("Status LEDs", "io", ["D_LED1", "D_LED2", "D_LED3", "D_LED4",
     "R_NEW14", "R_NEW15", "R_NEW16", "R_NEW17"]),
    ("Signal Test Points", "debug", ["TP_NEW6", "TP_NEW7", "TP_NEW8",
     "TP_NEW9", "TP_NEW10"]),
    ("Passives", "power", ["R1", "R2", "R3"]),
]


# ---------------------------------------------------------------------------
# Attack surface data — per-board attack paths for security SVG
# ---------------------------------------------------------------------------

# Xbox One attack paths (adjusted refs to match KNOWN_COMPONENTS)
XBOX_ATTACK_PATHS = [
    ("J5", "U1", "JTAG debug access"),
    ("U1", "U7", "eMMC bus (firmware extraction)"),
    ("U1", "U6", "Southbridge (peripheral control)"),
]
XBOX_SECURITY_REFS = ["J5", "U1", "U6", "U7", "TP1", "TP2", "TP3", "TP4", "TP5"]

# Cisco ASA attack paths (Thrangrycat CVE-2019-1649)
CISCO_ATTACK_PATHS = [
    ("J15", "U1", "JTAG debug → CPU"),
    ("J10", "U1", "Serial console → bootloader"),
    ("U1", "U6", "CPU → FPGA Trust Anchor"),
    ("U7", "U6", "Unencrypted SPI flash → FPGA bitstream"),
    ("U1", "U7", "CPU SPI bus → flash R/W"),
]
CISCO_SECURITY_REFS = ["J15", "J10", "U1", "U6", "U7", "TP1", "TP2", "TP3", "TP4"]


def _build_synthetic_result(
    image_path: str,
    comp_list: list[tuple] | None = None,
    trace_list: list[tuple] | None = None,
    endpoint_list: list[tuple[str, str]] | None = None,
    img_w: int = IMG_W,
    img_h: int = IMG_H,
    layers: int = 8,
) -> AnalysisResult:
    comp_list = comp_list or KNOWN_COMPONENTS
    trace_list = trace_list or TRACE_ROUTES
    endpoint_list = endpoint_list or XBOX_TRACE_ENDPOINTS
    components: list[Component] = []
    traces: list[Trace] = []

    for i, entry in enumerate(comp_list):
        ref, label, x, y, w, h, marking, part_number, value, package, _pins = entry
        components.append(
            Component(
                id=ref, label=label,
                confidence=round(0.88 + 0.1 * (i % 3) / 2, 3),
                bbox=(x, y, w, h), marking=marking,
                part_number=part_number, value=value, package=package,
            )
        )

    for idx, (pts, _width) in enumerate(trace_list):
        from_ref, to_ref = endpoint_list[idx] if idx < len(endpoint_list) else ("", "")
        traces.append(
            Trace(
                id=f"T{idx:03d}",
                points=list(pts),
                width_px=float(_width),
                from_component=from_ref,
                to_component=to_ref,
            )
        )

    return AnalysisResult(
        image_path=image_path,
        components=components,
        traces=traces,
        board_dimensions=(img_w, img_h),
        layer_count_estimate=layers,
        duration_seconds=0.0,
        pipeline_version="0.1.0",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


# ---------------------------------------------------------------------------
# Probe advisor output
# ---------------------------------------------------------------------------

def _run_probe_advisor(
    result: AnalysisResult,
    comp_list: list[tuple] | None = None,
    net_labels: list[str] | None = None,
    board_label: str = "",
) -> str:
    _default_nets = [
        "VCC_CORE","VCC_GFX","VCC_IO","GND","DDR_DQ0","DDR_DQ1","PCIE_TX","PCIE_RX",
        "HDMI_TX0P","HDMI_TX0N","SPI_MOSI","SPI_CLK","USB0_DP","USB0_DN","TDI","TDO","TCK","TMS",
    ]
    advisor = ProbeAdvisor(net_labels=net_labels or _default_nets, alpha=1.0)
    comp_list = comp_list or KNOWN_COMPONENTS

    advisor_comps: list[AdvisorComponent] = []
    for entry in comp_list:
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
        f"Board: {board_label or result.image_path}",
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

def _run_constraint_solver(
    result: AnalysisResult,
    comp_list: list[tuple] | None = None,
    solver_traces: list[SolverTrace] | None = None,
    board_label: str = "",
) -> str:
    comp_list = comp_list or KNOWN_COMPONENTS
    comp_specs: list[ComponentSpec] = []
    for entry in comp_list:
        ref, label, x, y, w, h, _marking, _pn, _val, _pkg, pins = entry
        cx = float(x + w / 2)
        cy = float(y + h / 2)
        comp_specs.append(ComponentSpec(ref=ref, kind=label, pins=pins, location=(cx, cy)))

    if solver_traces is None:
        solver_traces = [
            SolverTrace(Pin("U1","DDR_DQ0"), Pin("U2","DQ0"), confidence=0.95),
            SolverTrace(Pin("U1","DDR_DQ1"), Pin("U3","DQ0"), confidence=0.95),
            SolverTrace(Pin("U1","PCIE_TX"), Pin("U6","VCC"), confidence=0.88),
            SolverTrace(Pin("U1","PCIE_RX"), Pin("U6","GND"), confidence=0.88),
            SolverTrace(Pin("U1","HDMI_TX0P"),Pin("U12","HDMI_IN0"),confidence=0.92),
            SolverTrace(Pin("U1","HDMI_TX0N"),Pin("U12","HDMI_IN1"),confidence=0.92),
            SolverTrace(Pin("U6","SPI_MOSI"),Pin("U7","CMD"), confidence=0.90),
            SolverTrace(Pin("U6","SPI_CLK"), Pin("U7","CLK"), confidence=0.90),
            SolverTrace(Pin("U6","USB0_DP"), Pin("J2","D+"),  confidence=0.93),
            SolverTrace(Pin("U6","USB0_DN"), Pin("J2","D-"),  confidence=0.93),
            SolverTrace(Pin("U6","USB1_DP"), Pin("J3","D+"),  confidence=0.93),
            SolverTrace(Pin("U6","USB1_DN"), Pin("J3","D-"),  confidence=0.93),
            SolverTrace(Pin("U10","VOUT"),   Pin("L1","1"),   confidence=0.91),
            SolverTrace(Pin("U11","VOUT"),   Pin("L2","1"),   confidence=0.91),
            SolverTrace(Pin("U9","MDI0P"),   Pin("J4","TX+"), confidence=0.89),
            SolverTrace(Pin("U9","MDI0N"),   Pin("J4","TX-"), confidence=0.89),
            SolverTrace(Pin("J5","TDI"),     Pin("U1","VCC_CORE"),confidence=0.75),
            SolverTrace(Pin("U8","SDIO_CLK"),Pin("U6","SPI_CLK"),confidence=0.85),
            SolverTrace(Pin("U12","HDMI_OUT0"),Pin("J1","TMDS0+"),confidence=0.94),
            SolverTrace(Pin("U12","HDMI_OUT1"),Pin("J1","TMDS0-"),confidence=0.94),
        ]

    solver = ConstraintSolver(proximity_threshold_px=80.0)
    res = solver.solve(comp_specs, solver_traces)

    lines = [
        "re:trace Constraint Solver — Inferred Netlist",
        "=" * 50,
        "",
        f"Board: {board_label or result.image_path}",
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

def _run_debug_interface_detection(result: AnalysisResult, board_label: str = "") -> str:
    findings = detect_debug_interfaces(result)
    high = [f for f in findings if f["severity"] == "high"]
    medium = [f for f in findings if f["severity"] == "medium"]
    low = [f for f in findings if f["severity"] == "low"]

    lines = [
        "re:trace Debug Interface Detector",
        "=" * 40,
        "",
        f"Board: {board_label or result.image_path}",
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

CISCO_SOLVER_TRACES = [
    SolverTrace(Pin("U1","DDR3_DQ0"),  Pin("U2","DQ0"),   confidence=0.95),
    SolverTrace(Pin("U1","DDR3_A0"),   Pin("U3","A0"),    confidence=0.95),
    SolverTrace(Pin("U1","PCIE_TX0"),  Pin("U8","PCIE_TX"),confidence=0.92),
    SolverTrace(Pin("U1","PCIE_RX0"),  Pin("U8","PCIE_RX"),confidence=0.92),
    SolverTrace(Pin("U6","SPI_DI"),    Pin("U7","DI"),    confidence=0.94),
    SolverTrace(Pin("U6","SPI_DO"),    Pin("U7","DO"),    confidence=0.94),
    SolverTrace(Pin("U6","SPI_CLK"),   Pin("U7","CLK"),   confidence=0.94),
    SolverTrace(Pin("U6","SPI_CS"),    Pin("U7","CS"),    confidence=0.94),
    SolverTrace(Pin("U6","PROC_RST"),  Pin("U1","GND"),   confidence=0.88),
    SolverTrace(Pin("U6","TRUST_VERIFY"),Pin("U1","VCC"), confidence=0.85),
    SolverTrace(Pin("U1","SATA_TX"),   Pin("J6","SATA_TX+"),confidence=0.91),
    SolverTrace(Pin("U1","SATA_RX"),   Pin("J6","SATA_RX+"),confidence=0.91),
    SolverTrace(Pin("U1","UART_TX"),   Pin("J10","TX"),   confidence=0.93),
    SolverTrace(Pin("U1","UART_RX"),   Pin("J10","RX"),   confidence=0.93),
    SolverTrace(Pin("U1","USB_DP"),    Pin("J12","D+"),   confidence=0.90),
    SolverTrace(Pin("U1","USB_DN"),    Pin("J12","D-"),   confidence=0.90),
    SolverTrace(Pin("J15","TDI"),      Pin("U1","JTAG_TDI"),confidence=0.80),
    SolverTrace(Pin("J15","TDO"),      Pin("U1","JTAG_TDO"),confidence=0.80),
    SolverTrace(Pin("U10","PH"),       Pin("L1","1"),     confidence=0.91),
    SolverTrace(Pin("U11","SW"),       Pin("U1","VCC"),   confidence=0.91),
]

CISCO_NET_LABELS = [
    "VCC_CORE","VCC_3V3","VCC_1V0","GND","DDR3_DQ0","DDR3_A0","PCIE_TX","PCIE_RX",
    "SPI_CLK","SPI_MOSI","SPI_MISO","SPI_CS","SATA_TX","SATA_RX","UART_TX","UART_RX",
    "USB_DP","USB_DN","JTAG_TDI","JTAG_TDO","JTAG_TCK","JTAG_TMS","PROC_RST",
    "TRUST_VERIFY","TRUST_STATUS","GbE0_TX","GbE0_RX",
]


def _generate_one_board(
    out: Path,
    prefix: str,
    board_title: str,
    img_w: int,
    img_h: int,
    comp_list: list[tuple],
    trace_routes: list[tuple],
    endpoints: list[tuple[str, str]],
    vias: list[tuple],
    mounting_holes: list[tuple],
    silk_labels: list[tuple],
    layers: int,
    net_labels: list[str] | None = None,
    solver_traces_override: list[SolverTrace] | None = None,
    zones: list[tuple[str, str, list[str]]] | None = None,
    attack_paths: list[tuple[str, str, str]] | None = None,
    security_refs: list[str] | None = None,
    seed: int = 42,
) -> None:
    from dataclasses import asdict as _asdict

    img_name = f"{prefix}_board.png"
    board_img = out / img_name
    click.echo(f"  [1/8] Generating {prefix} PCB image → {board_img}")
    generate_board_image(
        board_img, img_w, img_h, comp_list, trace_routes, vias,
        mounting_holes, silk_labels, board_title, seed,
    )
    click.echo(f"        Saved ({board_img.stat().st_size // 1024} KB)")

    click.echo(f"  [2/8] Building {prefix} analysis result...")
    result = _build_synthetic_result(
        str(board_img), comp_list, trace_routes, endpoints, img_w, img_h, layers,
    )

    det_json = out / f"{prefix}_detection.json"
    click.echo(f"  [3/8] Writing → {det_json}")
    det_json.write_text(json.dumps({
        "version": result.pipeline_version, "timestamp": result.timestamp,
        "image": result.image_path, "board_dimensions": list(result.board_dimensions),
        "layer_count_estimate": result.layer_count_estimate,
        "components": [_asdict(c) for c in result.components],
        "traces": [_asdict(t) for t in result.traces],
        "summary": result.summary(),
    }, indent=2) + "\n")

    bom = generate_bom(result)
    (out / f"{prefix}_bom.json").write_text(bom_to_json(bom) + "\n")
    (out / f"{prefix}_bom.csv").write_text(bom_to_csv(bom))

    svg_path = out / f"{prefix}_annotated.svg"
    click.echo(f"  [4/8] Writing SVG overlay → {svg_path}")
    svg_str = generate_svg(result, image_href=img_name, title=board_title, zones=zones)
    svg_path.write_text(svg_str, encoding="utf-8")

    # Attack surface SVG
    atk_svg_path = out / f"{prefix}_attack_surface.svg"
    click.echo(f"  [5/8] Writing attack surface SVG → {atk_svg_path}")
    atk_svg_str = generate_attack_surface_svg(
        result,
        attack_paths=attack_paths or [],
        security_refs=security_refs or [],
        title=f"{board_title} — Attack Surface",
    )
    atk_svg_path.write_text(atk_svg_str, encoding="utf-8")

    # Zones-only SVG
    zones_svg_path = out / f"{prefix}_zones.svg"
    click.echo(f"  [6/8] Writing zones SVG → {zones_svg_path}")
    zones_svg_str = generate_zones_svg(
        result,
        zones=zones or [],
        title=f"{board_title} — Functional Zones",
    )
    zones_svg_path.write_text(zones_svg_str, encoding="utf-8")

    probe_path = out / f"{prefix}_probe.txt"
    click.echo(f"  [7/8] Running probe advisor → {probe_path}")
    probe_path.write_text(
        _run_probe_advisor(result, comp_list, net_labels, board_label=board_title)
    )

    solver_path = out / f"{prefix}_solver.txt"
    dbg_path = out / f"{prefix}_debug.txt"
    click.echo(f"  [8/8] Running solver + debug detector → {solver_path}")
    solver_path.write_text(
        _run_constraint_solver(result, comp_list, solver_traces_override, board_label=board_title)
    )
    dbg_path.write_text(_run_debug_interface_detection(result, board_label=board_title))

    for p in [board_img, det_json, svg_path, atk_svg_path, zones_svg_path,
              probe_path, solver_path, dbg_path,
              out / f"{prefix}_bom.json", out / f"{prefix}_bom.csv"]:
        if p.exists():
            click.echo(f"    ✓  {p.name}  ({p.stat().st_size:,} bytes)")


@click.group()
def cli():
    """re:trace synthetic PCB demo generator."""


@cli.command()
@click.option("--output-dir", default="docs/examples", show_default=True)
def generate(output_dir: str):
    """Generate both Xbox One and Cisco ASA 5506-X demo boards."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    click.echo(click.style("\n═══ Xbox One — Gaming Console ═══", fg="cyan", bold=True))
    _generate_one_board(
        out, prefix="xbox",
        board_title="Xbox One Model 1540 — Durango (AMD Liverpool APU, 28nm)",
        img_w=IMG_W, img_h=IMG_H,
        comp_list=KNOWN_COMPONENTS,
        trace_routes=TRACE_ROUTES,
        endpoints=XBOX_TRACE_ENDPOINTS,
        vias=VIAS, mounting_holes=MOUNTING_HOLES, silk_labels=SILK_LABELS,
        layers=8, zones=XBOX_ZONES,
        attack_paths=XBOX_ATTACK_PATHS,
        security_refs=XBOX_SECURITY_REFS,
        seed=42,
    )

    click.echo(click.style("\n═══ Cisco ASA 5506-X — Enterprise Firewall ═══", fg="red", bold=True))
    _generate_one_board(
        out, prefix="cisco",
        board_title="CISCO ASA5506-X V05",
        img_w=CISCO_IMG_W, img_h=CISCO_IMG_H,
        comp_list=CISCO_COMPONENTS,
        trace_routes=CISCO_TRACE_ROUTES,
        endpoints=CISCO_TRACE_ENDPOINTS,
        vias=CISCO_VIAS, mounting_holes=CISCO_MOUNTING_HOLES,
        silk_labels=CISCO_SILK_LABELS,
        layers=10,
        net_labels=CISCO_NET_LABELS,
        solver_traces_override=CISCO_SOLVER_TRACES,
        zones=CISCO_ZONES,
        attack_paths=CISCO_ATTACK_PATHS,
        security_refs=CISCO_SECURITY_REFS,
        seed=99,
    )

    # Legacy filenames (symlinks for backward compat with README)
    for old, new in [
        ("synthetic_board.png", "xbox_board.png"),
        ("annotated_board.svg", "xbox_annotated.svg"),
        ("bom_output.json", "xbox_bom.json"),
        ("bom_output.csv", "xbox_bom.csv"),
        ("detection_result.json", "xbox_detection.json"),
        ("probe_recommendations.txt", "xbox_probe.txt"),
        ("constraint_solver_output.txt", "xbox_solver.txt"),
        ("debug_interfaces.txt", "xbox_debug.txt"),
    ]:
        old_path = out / old
        new_path = out / new
        if new_path.exists() and old_path.exists():
            old_path.unlink()
        if new_path.exists() and not old_path.exists():
            import shutil
            shutil.copy2(new_path, old_path)

    click.echo(click.style("\nDone! Both boards generated.", fg="green", bold=True))


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
    for prefix in ("xbox", "cisco"):
        for suffix in ("_board.png", "_annotated.svg", "_attack_surface.svg", "_zones.svg",
                       "_detection.json",
                       "_bom.json", "_bom.csv", "_probe.txt", "_solver.txt", "_debug.txt"):
            fpath = out / f"{prefix}{suffix}"
            if fpath.exists():
                fpath.unlink()
                click.echo(f"  Removed {fpath}")
                removed += 1
    for legacy in ("synthetic_board.png", "annotated_board.svg", "bom_output.json",
                   "bom_output.csv", "detection_result.json", "probe_recommendations.txt",
                   "constraint_solver_output.txt", "debug_interfaces.txt"):
        fpath = out / legacy
        if fpath.exists():
            fpath.unlink()
            click.echo(f"  Removed {fpath}")
            removed += 1
    click.echo(f"Cleaned {removed} file(s).")


if __name__ == "__main__":
    cli()
