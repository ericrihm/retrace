"""Component identification via fuzzy matching against a local component database."""

from __future__ import annotations

import difflib
from typing import Optional

from retrace.core.pipeline import Component

# ---------------------------------------------------------------------------
# Hardcoded component database — extends at runtime via learn()
# ---------------------------------------------------------------------------

_COMPONENT_DB: list[dict] = [
    # Microcontrollers
    {
        "part": "STM32F103C8T6",
        "aliases": ["STM32F103", "STM32", "103C8"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "LQFP48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f103c8.pdf",
        "description": "ARM Cortex-M3 32-bit MCU, 72MHz, 64KB Flash",
    },
    {
        "part": "STM32F411CEU6",
        "aliases": ["STM32F411", "F411CEU"],
        "category": "mcu",
        "manufacturer": "STMicroelectronics",
        "package": "UFQFPN48",
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32f411ce.pdf",
        "description": "ARM Cortex-M4 84MHz, 512KB Flash",
    },
    {
        "part": "ESP32-WROOM-32",
        "aliases": ["ESP32", "ESP-WROOM", "WROOM32"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "Module",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf",
        "description": "Dual-core Xtensa 240MHz, WiFi+BT, 4MB Flash",
    },
    {
        "part": "ESP8266EX",
        "aliases": ["ESP8266", "ESP-12", "ESP-07"],
        "category": "mcu",
        "manufacturer": "Espressif",
        "package": "QFN32",
        "datasheet": "https://www.espressif.com/sites/default/files/documentation/0a-esp8266ex_datasheet_en.pdf",
        "description": "WiFi SoC, 80/160MHz, 802.11 b/g/n",
    },
    {
        "part": "ATmega328P",
        "aliases": ["ATmega328", "ATMEGA328P", "328P"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP32",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATmega48A-PA-88A-PA-168A-PA-328-P-DS-DS40002061B.pdf",
        "description": "8-bit AVR, 20MHz, 32KB Flash",
    },
    {
        "part": "ATmega2560",
        "aliases": ["ATMEGA2560", "2560"],
        "category": "mcu",
        "manufacturer": "Microchip",
        "package": "TQFP100",
        "datasheet": "https://ww1.microchip.com/downloads/en/DeviceDoc/ATmega640-1280-1281-2560-2561-Datasheet-DS40002211A.pdf",
        "description": "8-bit AVR, 16MHz, 256KB Flash",
    },
    {
        "part": "RP2040",
        "aliases": ["RP2040", "RASPBERRY PI"],
        "category": "mcu",
        "manufacturer": "Raspberry Pi",
        "package": "QFN56",
        "datasheet": "https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf",
        "description": "Dual Cortex-M0+, 133MHz, 264KB SRAM",
    },
    # Voltage regulators
    {
        "part": "LM1117-3.3",
        "aliases": ["LM1117", "LM1117T", "LD1117"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "SOT-223",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm1117.pdf",
        "description": "800mA LDO, 3.3V output",
    },
    {
        "part": "AMS1117-3.3",
        "aliases": ["AMS1117", "AMS1117-3.3", "AMS117"],
        "category": "regulator",
        "manufacturer": "Advanced Monolithic Systems",
        "package": "SOT-223",
        "datasheet": "http://www.advanced-monolithic.com/pdf/ds1117.pdf",
        "description": "1A LDO, adjustable/fixed 1.5V–5V",
    },
    {
        "part": "LM7805",
        "aliases": ["7805", "L7805", "LM7805CT"],
        "category": "regulator",
        "manufacturer": "Texas Instruments",
        "package": "TO-220",
        "datasheet": "https://www.ti.com/lit/ds/symlink/lm7805.pdf",
        "description": "1A linear regulator, 5V fixed output",
    },
    {
        "part": "MP2315",
        "aliases": ["MP2315", "MP2315GJ"],
        "category": "regulator",
        "manufacturer": "Monolithic Power Systems",
        "package": "TSOT23-8",
        "datasheet": "https://www.monolithicpower.com/pub/media/document/MP2315_r1.0.pdf",
        "description": "3A high-efficiency buck converter",
    },
    # Memory
    {
        "part": "W25Q128JV",
        "aliases": ["W25Q128", "25Q128", "WINBOND"],
        "category": "flash",
        "manufacturer": "Winbond",
        "package": "SOP8",
        "datasheet": "https://www.winbond.com/resource-files/w25q128jv%20revf%2003272018%20plus.pdf",
        "description": "128Mbit SPI NOR Flash",
    },
    {
        "part": "GD25Q64",
        "aliases": ["GD25Q64", "25Q64"],
        "category": "flash",
        "manufacturer": "GigaDevice",
        "package": "SOP8",
        "datasheet": "https://www.gigadevice.com/datasheet/gd25q64c/",
        "description": "64Mbit SPI NOR Flash",
    },
    # Interface
    {
        "part": "CH340G",
        "aliases": ["CH340", "CH340G"],
        "category": "usb-uart",
        "manufacturer": "WCH",
        "package": "SOP16",
        "datasheet": "https://www.wch-ic.com/downloads/CH340DS1_PDF.html",
        "description": "USB-to-UART bridge",
    },
    {
        "part": "CP2102",
        "aliases": ["CP2102", "CP210X"],
        "category": "usb-uart",
        "manufacturer": "Silicon Labs",
        "package": "QFN28",
        "datasheet": "https://www.silabs.com/documents/public/data-sheets/CP2102-9.pdf",
        "description": "USB-to-UART single chip bridge",
    },
    {
        "part": "FT232RL",
        "aliases": ["FT232", "FT232R", "FTDI"],
        "category": "usb-uart",
        "manufacturer": "FTDI",
        "package": "SSOP28",
        "datasheet": "https://ftdichip.com/wp-content/uploads/2020/08/DS_FT232R.pdf",
        "description": "USB-to-UART/FIFO, 3Mbaud",
    },
    # Wireless
    {
        "part": "nRF24L01",
        "aliases": ["NRF24L01", "NRF24", "24L01"],
        "category": "rf",
        "manufacturer": "Nordic Semiconductor",
        "package": "QFN20",
        "datasheet": "https://infocenter.nordicsemi.com/pdf/nRF24L01P_PS_v1.0.pdf",
        "description": "2.4GHz RF transceiver, -6dBm to 0dBm",
    },
    {
        "part": "CC2530",
        "aliases": ["CC2530", "CC2530F256"],
        "category": "rf",
        "manufacturer": "Texas Instruments",
        "package": "QFN40",
        "datasheet": "https://www.ti.com/lit/ds/symlink/cc2530.pdf",
        "description": "ZigBee/IEEE 802.15.4 SoC",
    },
]


def _build_lookup() -> dict[str, dict]:
    """Build a fast lookup table from all part numbers and aliases."""
    lookup: dict[str, dict] = {}
    for entry in _COMPONENT_DB:
        lookup[entry["part"].upper()] = entry
        for alias in entry.get("aliases", []):
            lookup[alias.upper()] = entry
    return lookup


_LOOKUP = _build_lookup()


def _best_fuzzy_match(marking: str, threshold: float = 0.55) -> Optional[dict]:
    """Return the best DB entry matching the marking via SequenceMatcher, or None."""
    if not marking:
        return None

    upper = marking.upper().strip()

    # Exact match first
    if upper in _LOOKUP:
        return _LOOKUP[upper]

    # Fuzzy search against all keys
    best_score = 0.0
    best_entry: Optional[dict] = None

    for key, entry in _LOOKUP.items():
        score = difflib.SequenceMatcher(None, upper, key).ratio()
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_score >= threshold:
        return best_entry
    return None


def identify_components(components: list[Component]) -> list[Component]:
    """Fuzzy-match component markings against the local DB and annotate in-place.

    Each component with a non-empty marking is looked up against the component
    database. On a match the ``part_number``, ``datasheet_url``, ``package``,
    and ``value`` fields are populated.

    Args:
        components: List of Component dataclass instances (mutated in-place and
            also returned for chaining).

    Returns:
        The same list with identified fields filled in where matches were found.
    """
    for comp in components:
        if not comp.marking:
            continue
        match = _best_fuzzy_match(comp.marking)
        if match:
            comp.part_number = comp.part_number or match["part"]
            comp.datasheet_url = comp.datasheet_url or match.get("datasheet", "")
            comp.package = comp.package or match.get("package", "")
            comp.value = comp.value or match.get("description", "")
    return components


def lookup_part(marking: str) -> Optional[dict]:
    """Public single-part lookup used by tests and CLI helpers.

    Args:
        marking: Raw marking string read from the PCB.

    Returns:
        Dict with part, category, manufacturer, package, datasheet, description
        keys — or None if no match above threshold.
    """
    return _best_fuzzy_match(marking)
