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

    # Main APU — AMD "Liverpool" custom SoC: 8-core Jaguar x86-64 + GCN 1.1 (12 CU, 768 shaders)
    # TSMC 28nm, ~363mm² die. No separate southbridge — USB3, SATA, PCIe integrated on-die.
    ("U1", "ic",         500, 300, 300, 300, "Liverpool",      "AMD Liverpool",  "",       "BGA-1170",
     ["VCC_CORE","VCC_GFX","VCC_IO","GND","GND2","GND3","GND4","DDR_DQ0","DDR_DQ1","DDR_A0","HDMI_TX0P","HDMI_TX0N","PCIE_TX","PCIE_RX"]),

    # DDR3 RAM — Samsung K4B4G1646E-BYK0 (4Gbit each, 8 chips total = 8GB, DDR3-2133)
    ("U2", "ic",         120, 120, 140,  90, "K4B4G1646E",    "K4B4G1646E-BYK0", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U3", "ic",         300, 120, 140,  90, "K4B4G1646E",    "K4B4G1646E-BYK0", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U4", "ic",         120, 680, 140,  90, "K4B4G1646E",    "K4B4G1646E-BYK0", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),
    ("U5", "ic",         300, 680, 140,  90, "K4B4G1646E",    "K4B4G1646E-BYK0", "4Gb",  "BGA-78",
     ["VDD","VDDQ","VSS","VSSQ","DQ0","DQ1","DQ2","DQ3","A0","A1","CK","CKE","CS","RAS","CAS","WE"]),

    # HDMI encoder — Panasonic MN864729 (HDMI 1.4 transmitter)
    ("U6", "ic",        1000, 120, 140, 100, "MN864729",       "MN864729",      "",       "QFP-80",
     ["VCC","GND","HDMI_TX0P","HDMI_TX0N","HDMI_TX1P","HDMI_TX1N","HDMI_TX2P","HDMI_TX2N","HDMI_CKP","HDMI_CKN","SDA","SCL"]),

    # eMMC — Samsung KLMBG4GEAC-B001 (8GB eMMC 4.51)
    ("U7", "ic",        1000, 300, 160, 120, "KLMBG4GEAC",    "KLMBG4GEAC-B001", "8GB",  "BGA-153",
     ["VCC","VCCQ","GND","CMD","CLK","DAT0","DAT1","DAT2","DAT3","DAT4","DAT5","DAT6","DAT7"]),

    # WiFi/BT — Marvell AVASTAR 88W8897 (2x2 802.11ac + BT 4.0)
    ("U8", "ic",        1050, 500, 120,  80, "88W8897",        "88W8897-NNB2",  "",       "QFN-68",
     ["VCC","GND","SDIO_CLK","SDIO_CMD","SDIO_D0","SDIO_D1","ANT1","ANT2"]),

    # Ethernet PHY — Marvell 88EC060-NNB2 (GbE)
    ("U9", "ic",        1050, 660, 100,  70, "88EC060",        "88EC060-NNB2",  "",       "QFN-56",
     ["VCC","GND","MDI0P","MDI0N","MDI1P","MDI1N","TX_CLK","RX_CLK"]),

    # Power: APU core VRM — ON Semi NCP81174 (multi-phase)
    ("U10","ic",          80, 350,  70,  55, "NCP81174",       "NCP81174",      "",       "QFN-52",
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
    ("U1","U2"),("U1","U3"),("U1","U2"),("U1","U3"),("U1","U4"),("U1","U5"),
    ("U1","U6"),("U1","U6"),("U1","U12"),("U1","U12"),
    ("U6","U7"),("U6","U7"),("U6","U7"),("U6","U7"),
    ("U6","J2"),("U6","J2"),("U6","J3"),("U6","J3"),
    ("U10","U1"),("U10","U1"),("U11","U1"),("L1","U1"),("L2","U1"),
    ("U8","U6"),("U8","U6"),("U9","J4"),("U9","J4"),
    ("J5","U1"),("J5","U1"),("J5","U1"),("J5","U1"),
    ("U12","J1"),("U12","J1"),("Y1","U6"),
]


XBOX_ZONES: list[tuple[str, str, list[str]]] = [
    ("APU Complex", "cpu", ["U1"]),
    ("DDR3 Memory Bank A", "memory", ["U2", "U3"]),
    ("DDR3 Memory Bank B", "memory", ["U4", "U5"]),
    ("Power Delivery", "power", ["U10", "U11", "L1", "L2"]),
    ("HDMI Output", "io", ["U6", "U12", "J1"]),
    ("Storage", "storage", ["U7"]),
    ("Wireless / Networking", "network", ["U8", "U9", "J4"]),
    ("USB Subsystem", "io", ["J2", "J3"]),
    ("Debug / JTAG", "debug", ["J5", "TP1", "TP2", "TP3", "TP4", "TP5"]),
]

CISCO_ZONES: list[tuple[str, str, list[str]]] = [
    ("Intel Atom C2508 CPU", "cpu", ["U1"]),
    ("DDR3 ECC Memory", "memory", ["U2", "U3", "U4", "U5"]),
    ("Trust Anchor Module", "debug", ["U6", "U7"]),
    ("Power Delivery", "power", ["U10", "U11", "U12", "L1", "L2"]),
    ("Intel I354 NIC", "network", ["U8"]),
    ("Data Plane Ports", "network", ["J1", "J2", "J3", "J4", "J5", "J7", "J8", "J9"]),
    ("Management / Console", "io", ["J10", "J11", "J12", "J13"]),
    ("Storage", "storage", ["U9", "J6"]),
    ("JTAG Debug Chain", "debug", ["J15", "TP1", "TP2", "TP3", "TP4"]),
    ("DC Power Input", "power", ["J14"]),
]


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

def _run_constraint_solver(
    result: AnalysisResult,
    comp_list: list[tuple] | None = None,
    solver_traces: list[SolverTrace] | None = None,
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
    seed: int = 42,
) -> None:
    from dataclasses import asdict as _asdict

    img_name = f"{prefix}_board.png"
    board_img = out / img_name
    click.echo(f"  [1/6] Generating {prefix} PCB image → {board_img}")
    generate_board_image(
        board_img, img_w, img_h, comp_list, trace_routes, vias,
        mounting_holes, silk_labels, board_title, seed,
    )
    click.echo(f"        Saved ({board_img.stat().st_size // 1024} KB)")

    click.echo(f"  [2/6] Building {prefix} analysis result...")
    result = _build_synthetic_result(
        str(board_img), comp_list, trace_routes, endpoints, img_w, img_h, layers,
    )

    det_json = out / f"{prefix}_detection.json"
    click.echo(f"  [3/6] Writing → {det_json}")
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
    click.echo(f"  [4/6] Writing SVG overlay → {svg_path}")
    svg_str = generate_svg(result, image_href=img_name, title=board_title, zones=zones)
    svg_path.write_text(svg_str, encoding="utf-8")

    probe_path = out / f"{prefix}_probe.txt"
    click.echo(f"  [5/6] Running probe advisor → {probe_path}")
    probe_path.write_text(_run_probe_advisor(result, comp_list, net_labels))

    solver_path = out / f"{prefix}_solver.txt"
    dbg_path = out / f"{prefix}_debug.txt"
    click.echo(f"  [6/6] Running solver + debug detector → {solver_path}")
    solver_path.write_text(_run_constraint_solver(result, comp_list, solver_traces_override))
    dbg_path.write_text(_run_debug_interface_detection(result))

    for p in [board_img, det_json, svg_path, probe_path, solver_path, dbg_path,
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
        layers=8, zones=XBOX_ZONES, seed=42,
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
        for suffix in ("_board.png", "_annotated.svg", "_detection.json",
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
