"""Firmware extraction cheat sheet generator.

Given an AnalysisResult with identified flash chips, generates ready-to-run
commands for flashrom, openocd, and manual SPI extraction.
"""

from __future__ import annotations

from typing import Any

from retrace.core.pipeline import AnalysisResult

_FLASH_KEYWORDS = frozenset({
    "flash", "w25q", "mx25", "at25", "is25", "sst25", "s25fl",
    "mt25q", "n25q", "gd25", "en25", "pm25", "xt25",
})

_EMMC_KEYWORDS = frozenset({
    "emmc", "mtfc", "klmag", "thgbm", "h26m", "sdin",
})

_EEPROM_KEYWORDS = frozenset({
    "eeprom", "at24", "24c", "93c", "m24",
})


def _comp_text(comp: Any) -> str:
    marking = getattr(comp, "marking", "") or ""
    part = getattr(comp, "part_number", "") or ""
    label = getattr(comp, "label", "") or ""
    return f"{marking} {part} {label}".lower()


def _classify_storage(comp: Any) -> str | None:
    text = _comp_text(comp)
    if any(kw in text for kw in _FLASH_KEYWORDS):
        return "spi_flash"
    if any(kw in text for kw in _EMMC_KEYWORDS):
        return "emmc"
    if any(kw in text for kw in _EEPROM_KEYWORDS):
        return "eeprom"
    return None


def _get_intel(comp: Any, key: str) -> str:
    intel = getattr(comp, "_security_intel", None)
    if intel and isinstance(intel, dict):
        return intel.get(key, "")
    return ""


def generate_extraction_guide(result: AnalysisResult) -> list[dict[str, Any]]:
    """Generate firmware extraction cheat sheets for detected storage chips."""
    guides: list[dict[str, Any]] = []

    for comp in result.components:
        storage_type = _classify_storage(comp)
        if not storage_type:
            continue

        marking = getattr(comp, "marking", "") or comp.id
        part_number = getattr(comp, "part_number", "") or ""

        guide: dict[str, Any] = {
            "component_id": comp.id,
            "marking": marking,
            "part_number": part_number,
            "storage_type": storage_type,
            "commands": [],
        }

        if storage_type == "spi_flash":
            jedec_id = _get_intel(comp, "jedec_id")
            flashrom_cmd = _get_intel(comp, "flashrom_support")
            read_cmd = _get_intel(comp, "read_cmd")
            capacity = _get_intel(comp, "capacity")

            if capacity:
                guide["capacity"] = capacity
            if jedec_id:
                guide["jedec_id"] = jedec_id

            chip_name = part_number.split("-")[0] if part_number else marking
            guide["commands"].append({
                "tool": "flashrom",
                "description": "Read flash via SPI programmer",
                "command": flashrom_cmd or f"flashrom -p ch341a_spi -c {chip_name} -r firmware.bin",
            })
            guide["commands"].append({
                "tool": "flashrom",
                "description": "Verify read integrity (read twice, compare)",
                "command": (
                    f"flashrom -p ch341a_spi -c {chip_name} -r fw1.bin && "
                    f"flashrom -p ch341a_spi -c {chip_name} -r fw2.bin && "
                    "diff fw1.bin fw2.bin"
                ),
            })
            if jedec_id:
                guide["commands"].append({
                    "tool": "spi_manual",
                    "description": "Manual JEDEC ID probe (confirm chip identity)",
                    "command": f"# Send 0x9F via SPI — expect JEDEC ID: {jedec_id}",
                })
            if read_cmd:
                guide["commands"].append({
                    "tool": "spi_manual",
                    "description": "Manual read command",
                    "command": f"# SPI read: {read_cmd}",
                })

            guide["wiring"] = {
                "VCC": "3.3V (check datasheet — some chips are 1.8V)",
                "GND": "Ground",
                "CS#": "Chip select (active low)",
                "CLK": "SPI clock",
                "DI/MOSI": "Data in (Master Out Slave In)",
                "DO/MISO": "Data out (Master In Slave Out)",
                "WP#": "Write protect (tie high to disable protection)",
                "HOLD#": "Hold (tie high)",
            }

        elif storage_type == "emmc":
            guide["commands"].append({
                "tool": "emmc_reader",
                "description": "Read eMMC via SD adapter or UFI box",
                "command": "# Use eMMC reader (e.g., Allsocket, UFI Box) — set to 3.3V",
            })
            guide["commands"].append({
                "tool": "dd",
                "description": "Dump eMMC when mounted as block device",
                "command": "dd if=/dev/sdX of=emmc_dump.bin bs=4M status=progress",
            })

        elif storage_type == "eeprom":
            guide["commands"].append({
                "tool": "i2c",
                "description": "Read I2C EEPROM via Bus Pirate or logic analyzer",
                "command": "# I2C address typically 0x50-0x57 depending on A0-A2 pins",
            })
            guide["commands"].append({
                "tool": "flashrom",
                "description": "Read via flashrom I2C support",
                "command": "flashrom -p buspirate_spi:dev=/dev/ttyUSB0 -r eeprom.bin",
            })

        guides.append(guide)

    return guides


def format_extraction_guide(guides: list[dict[str, Any]]) -> str:
    """Render extraction guides as a human-readable cheat sheet."""
    if not guides:
        return "No extractable storage chips detected."

    lines = [f"Firmware Extraction Cheat Sheet — {len(guides)} storage chip(s)", ""]

    for i, g in enumerate(guides, 1):
        lines.append(f"{'='*60}")
        lines.append(f"  #{i}  {g['marking']}")
        if g.get("part_number"):
            lines.append(f"       Part: {g['part_number']}")
        lines.append(f"       Type: {g['storage_type'].replace('_', ' ').upper()}")
        if g.get("capacity"):
            lines.append(f"       Capacity: {g['capacity']}")
        if g.get("jedec_id"):
            lines.append(f"       JEDEC ID: {g['jedec_id']}")
        lines.append("")

        for cmd in g.get("commands", []):
            lines.append(f"  [{cmd['tool']}] {cmd['description']}")
            lines.append(f"    $ {cmd['command']}")
            lines.append("")

        wiring = g.get("wiring")
        if wiring:
            lines.append("  Wiring:")
            for pin, desc in wiring.items():
                lines.append(f"    {pin:10s}  {desc}")
            lines.append("")

    return "\n".join(lines)
