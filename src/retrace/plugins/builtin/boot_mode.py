"""Built-in plugin: detects accessible boot mode pins on MCUs and SoCs.

Many microcontrollers have boot mode selection pins that, if physically
accessible (test point, header, unpopulated pad), allow forcing the chip
into a bootloader, DFU, or ISP mode — enabling firmware extraction or
replacement without any software authentication.
"""

from __future__ import annotations

from typing import Any

from retrace.core.pipeline import AnalysisResult

_BOOT_MODE_DB: list[dict[str, Any]] = [
    {
        "family_keywords": {"stm32"},
        "boot_pins": ["BOOT0", "BOOT1"],
        "description": "STM32 BOOT0/BOOT1 — forces System Memory bootloader (UART/USB DFU)",
        "bootloader_protocol": "UART (AN2606) or USB DFU (AN3156)",
        "extraction_tool": "stm32flash -r firmware.bin /dev/ttyUSB0",
        "severity": "high",
    },
    {
        "family_keywords": {"esp32", "esp8266"},
        "boot_pins": ["GPIO0", "IO0"],
        "description": "ESP32 GPIO0 — pull low during reset to enter UART bootloader",
        "bootloader_protocol": "UART (esptool.py)",
        "extraction_tool": "esptool.py -p /dev/ttyUSB0 read_flash 0 ALL flash.bin",
        "severity": "high",
    },
    {
        "family_keywords": {"nrf52", "nrf53", "nrf91"},
        "boot_pins": ["SWDIO", "SWCLK"],
        "description": "nRF5x — if APPROTECT not enabled, full flash read via SWD",
        "bootloader_protocol": "SWD (nrfjprog / OpenOCD)",
        "extraction_tool": "nrfjprog --readcode firmware.hex",
        "severity": "high",
    },
    {
        "family_keywords": {"pic", "pic16", "pic18", "pic32", "dspic"},
        "boot_pins": ["PGC", "PGD", "MCLR"],
        "description": "PIC ICSP — In-Circuit Serial Programming pins",
        "bootloader_protocol": "ICSP (PICkit / MPLAB Snap)",
        "extraction_tool": "pk2cmd -P PIC18F4520 -GF firmware.hex",
        "severity": "high",
    },
    {
        "family_keywords": {"atmega", "attiny", "avr", "arduino"},
        "boot_pins": ["RESET", "MOSI", "MISO", "SCK"],
        "description": "AVR ISP — In-System Programming via SPI",
        "bootloader_protocol": "ISP (avrdude)",
        "extraction_tool": "avrdude -p m328p -c usbasp -U flash:r:firmware.hex:i",
        "severity": "high",
    },
    {
        "family_keywords": {"samd", "saml", "same", "samc"},
        "boot_pins": ["SWDIO", "SWCLK", "RESET"],
        "description": "SAM D/L/E — Cortex-M with SWD and optional UART bootloader",
        "bootloader_protocol": "SWD (OpenOCD) or SAM-BA UART bootloader",
        "extraction_tool": "openocd -f target/at91samdXX.cfg -c 'flash read_image fw.bin'",
        "severity": "high",
    },
    {
        "family_keywords": {"lpc", "lpc1", "lpc2", "lpc4", "lpc5"},
        "boot_pins": ["ISP_EN", "P2.10"],
        "description": "NXP LPC ISP — pull ISP pin low during reset for UART bootloader",
        "bootloader_protocol": "UART ISP (lpc21isp / Flash Magic)",
        "extraction_tool": "lpc21isp -control firmware.hex /dev/ttyUSB0 115200 12000",
        "severity": "high",
    },
    {
        "family_keywords": {"rp2040", "rp2350", "pico"},
        "boot_pins": ["BOOTSEL"],
        "description": "RP2040 BOOTSEL — hold during reset to mount as USB mass storage",
        "bootloader_protocol": "USB UF2 mass storage (picotool)",
        "extraction_tool": "picotool save -a firmware.bin",
        "severity": "medium",
    },
    {
        "family_keywords": {"efm32", "efr32"},
        "boot_pins": ["SWDIO", "SWCLK", "DBG_SWCLKTCK"],
        "description": "Silicon Labs EFM32/EFR32 — SWD debug if AAP not locked",
        "bootloader_protocol": "SWD (Simplicity Commander)",
        "extraction_tool": "commander readmem --range 0x0:0x40000 --outfile fw.bin",
        "severity": "high",
    },
]

_TEST_POINT_LABELS = frozenset({"test_point", "header", "connector", "pad"})


def _comp_text(comp: Any) -> str:
    marking = getattr(comp, "marking", "") or ""
    part = getattr(comp, "part_number", "") or ""
    return f"{marking} {part}".lower()


def detect_boot_mode_pins(board: AnalysisResult) -> list[dict[str, Any]]:
    """Detect MCUs with known boot mode pins and nearby test points."""
    findings: list[dict[str, Any]] = []

    mcus: list[tuple[Any, dict[str, Any]]] = []
    for comp in board.components:
        text = _comp_text(comp)
        for entry in _BOOT_MODE_DB:
            if any(kw in text for kw in entry["family_keywords"]):
                mcus.append((comp, entry))
                break

    test_points = [
        c for c in board.components
        if getattr(c, "label", "").lower() in _TEST_POINT_LABELS
    ]

    for mcu, entry in mcus:
        mcu_marking = getattr(mcu, "marking", "") or mcu.id
        accessible_pins: list[str] = []

        for tp in test_points:
            tp_text = _comp_text(tp).upper()
            for pin in entry["boot_pins"]:
                if pin.upper() in tp_text:
                    accessible_pins.append(pin)

        findings.append({
            "type": "boot_mode",
            "severity": entry["severity"],
            "description": entry["description"],
            "component_id": mcu.id,
            "component_marking": mcu_marking,
            "boot_pins": entry["boot_pins"],
            "accessible_pins": accessible_pins,
            "bootloader_protocol": entry["bootloader_protocol"],
            "extraction_tool": entry["extraction_tool"],
            "cve_reference": "CWE-1191",
            "cvss_base": 7.6 if accessible_pins else 4.6,
            "cvss_vector": (
                "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"
                if accessible_pins else
                "CVSS:3.1/AV:P/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N"
            ),
            "mitre_attack": ["T1200", "T0839"],
        })

    return findings


class BootModeAnalyzer:
    """Retrace analyzer plugin that detects accessible boot mode pins."""

    name = "boot_mode"

    def analyze(self, board: AnalysisResult) -> dict[str, Any]:
        findings = detect_boot_mode_pins(board)
        accessible = sum(1 for f in findings if f["accessible_pins"])
        return {
            "plugin": self.name,
            "findings": findings,
            "summary": (
                f"Detected {len(findings)} MCU(s) with known boot mode pins, "
                f"{accessible} with accessible test points"
            ),
        }
