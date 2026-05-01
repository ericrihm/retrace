"""Protocol topology inference — detect pull-ups, transceivers, and bus characteristics.

Infers I2C, SPI, UART, CAN, and 1-Wire bus topology from static analysis of
component placement and trace connectivity in a PCB photo.  No live probing
required; all inference is from bounding-box proximity and marking/part-number
matching.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import NamedTuple

from retrace.core.pipeline import AnalysisResult, Component

# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class BusTopology:
    """Describes a single inferred protocol bus."""

    protocol: str           # "I2C", "SPI", "UART", "CAN", "1-Wire"
    confidence: float       # 0.0–1.0
    nodes: list[str]        # component IDs participating in this bus
    characteristics: dict   # protocol-specific detail dict
    security_notes: list[str]  # security implications


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _Pt(NamedTuple):
    x: float
    y: float


def _center(comp: Component) -> _Pt:
    x, y, w, h = comp.bbox
    return _Pt(x + w / 2.0, y + h / 2.0)


def _distance(a: Component, b: Component) -> float:
    pa, pb = _center(a), _center(b)
    return math.hypot(pa.x - pb.x, pa.y - pb.y)


def _proximity_threshold(board_dim: tuple[int, int]) -> float:
    """Return the max centre-to-centre distance (px) that counts as 'near'."""
    board_diag = math.hypot(board_dim[0], board_dim[1])
    return max(200.0, board_diag * 0.25)


def _norm(s: str) -> str:
    """Lower-case, strip whitespace."""
    return s.strip().lower()


# ---------------------------------------------------------------------------
# Resistor value parsing
# ---------------------------------------------------------------------------

# Matches: "4.7k", "4k7", "4700", "10k", "10K", "2.2k", "120", "121"
_RESISTOR_RE = re.compile(
    r"""^
    (?P<val>
        (?:\d+\.?\d*|\.\d+)   # leading digits
        (?:[kKrR](?:\d+)?)?   # optional kΩ / R multiplier
        |\d+[kKrR]            # forms like 4k7
    )
    \s*(?:Ω|ohm|ohms)?
    $""",
    re.VERBOSE | re.IGNORECASE,
)


def _parse_ohms(value_str: str) -> float | None:
    """Return resistance in ohms, or None if unparseable.

    Handles the full range of real-world resistor markings found on PCBs:

    * Plain integers / decimals: "120", "470", "4700"  → literal Ω value
    * k-suffix forms: "4.7k", "4K", "10k", "2.2k", "10K"
    * Embedded-letter forms (IEC 60062): "4k7", "4K7", "2R2", "4R7"
    * 3-digit EIA multiplier codes (SMD marking): "121" → 12×10¹ = 120 Ω,
      "471" → 47×10¹ = 470 Ω.  To distinguish from plain integers the EIA
      code path only fires when the exponent digit (third) is ≥ 1, which
      avoids misreading plain values like "120" (120 Ω) or "100" (100 Ω) as
      EIA codes (which would give 12 Ω and 10 Ω respectively).
    """
    s = value_str.strip()

    # Embedded-letter IEC forms first: "4k7", "4K7", "2R2", "4r7"
    m_iec = re.fullmatch(
        r"(\d+)\s*([kKrR])\s*(\d+)",
        s,
        re.IGNORECASE,
    )
    if m_iec:
        base = float(f"{m_iec.group(1)}.{m_iec.group(3)}")
        mult = m_iec.group(2).lower()
        return base * 1_000 if mult == "k" else base

    # k/M/R suffix forms: "4.7k", "10K", "1M", "4.7R"
    m_suffix = re.fullmatch(
        r"(\d+\.?\d*)\s*([kKmMrR])",
        s.replace(" ", ""),
        re.IGNORECASE,
    )
    if m_suffix:
        num = float(m_suffix.group(1))
        suf = m_suffix.group(2).lower()
        if suf == "k":
            return num * 1_000
        if suf == "m":
            return num * 1_000_000
        return num  # "r" = ohms

    # 3-digit EIA SMD code where exponent ≥ 1: "121"→120Ω, "471"→470Ω
    # Skip when exponent == 0 to avoid ambiguity with plain integers like "120"
    if re.fullmatch(r"\d{3}", s) and int(s[2]) >= 1:
        sig = int(s[:2])
        exp = int(s[2])
        return sig * (10 ** exp)

    # Plain integer or decimal with no suffix: literal ohms
    m_plain = re.fullmatch(r"\d+\.?\d*", s)
    if m_plain:
        return float(s)

    return None


# ---------------------------------------------------------------------------
# Component classifiers
# ---------------------------------------------------------------------------

# Parts that speak I2C as their primary bus (checked via marking/part_number)
_I2C_PART_PREFIXES: frozenset[str] = frozenset({
    "at24c", "at24lc",           # EEPROM
    "bme280", "bmp280", "bmp180",  # environmental sensors
    "mpu6050", "mpu9250",         # IMU
    "ina219", "ina226",           # current sensors
    "pcf8574", "pcf8591",         # I/O expanders
    "ds1307", "ds3231", "rv3028",  # RTCs
    "pca9685", "pca9548",         # PWM / mux
    "lm75", "tmp102",             # temp sensors
    "ssd1306",                    # OLED displays
    "hmc5883", "qmc5883",         # magnetometers
    "max17043",                   # fuel gauge
})

_SPI_FLASH_PREFIXES: frozenset[str] = frozenset({
    "w25q", "w25x",              # Winbond
    "mx25l", "mx25r",            # Macronix
    "at25", "at45",              # Microchip/Atmel
    "sst25", "sst26",            # SST
    "is25", "is65",              # ISSI
    "n25q", "n25s",              # Micron
    "gd25",                      # GigaDevice
    "s25fl",                     # Cypress/Infineon
    "pm25lq",                    # PMC/Chingis
})

_CAN_TRANSCEIVER_PREFIXES: frozenset[str] = frozenset({
    "mcp2551", "mcp2561", "mcp25625",   # Microchip
    "sn65hvd", "sn65lbc",               # Texas Instruments
    "tja1040", "tja1041", "tja1050", "tja1051", "tja1055",  # NXP
    "iso1050", "iso1042",               # TI isolated
    "l9616", "l9615",                   # STMicro
    "max3050", "max3051", "max33012",   # Maxim/ADI
    "au5790",                           # On Semi
})

_UART_LEVEL_SHIFTER_PREFIXES: frozenset[str] = frozenset({
    "max232", "max3232", "max202",      # Maxim RS-232
    "sp3232", "sp3221", "sp3223",       # Sipex
    "st3232", "st232",                  # STMicro
    "ch340", "ch341", "ch342",          # WCH USB-UART
    "cp2102", "cp2104", "cp2105",       # Silicon Labs
    "ft232", "ft231", "ft234",          # FTDI
    "pl2303", "pl2303hx",              # Prolific
    "mcp2221",                          # Microchip USB-UART/I2C
    "bl5372",                           # custom
})

_ONE_WIRE_PART_PREFIXES: frozenset[str] = frozenset({
    "ds18b20", "ds18s20", "ds18b22",   # temperature
    "ds2401", "ds2411",                 # serial number
    "ds2431", "ds2433",                 # EEPROM
    "ds2413", "ds2423",                 # GPIO, counter
    "ds1990",                           # iButton
})

# MCU categories that have I2C/SPI/UART buses (broad fallback)
_MCU_CATEGORIES: frozenset[str] = frozenset({"mcu", "soc", "fpga"})


def _has_prefix(text: str, prefixes: frozenset[str]) -> bool:
    t = _norm(text)
    return any(t.startswith(p) or p in t for p in prefixes)


def _is_mcu(comp: Component) -> bool:
    return comp.label == "ic" and (
        comp.label in _MCU_CATEGORIES
        or _norm(comp.marking).startswith(("stm32", "esp", "nrf", "pic", "avr", "atm", "sam"))
        or _norm(comp.part_number or "").startswith(
            ("stm32", "esp", "nrf", "pic", "avr", "atm", "sam", "lpc", "mk", "mimxrt")
        )
    )


def _is_i2c_peripheral(comp: Component) -> bool:
    if comp.label != "ic":
        return False
    return _has_prefix(comp.marking, _I2C_PART_PREFIXES) or _has_prefix(
        comp.part_number or "", _I2C_PART_PREFIXES
    )


def _is_spi_flash(comp: Component) -> bool:
    if comp.label != "ic":
        return False
    return _has_prefix(comp.marking, _SPI_FLASH_PREFIXES) or _has_prefix(
        comp.part_number or "", _SPI_FLASH_PREFIXES
    )


def _is_can_transceiver(comp: Component) -> bool:
    if comp.label != "ic":
        return False
    return _has_prefix(comp.marking, _CAN_TRANSCEIVER_PREFIXES) or _has_prefix(
        comp.part_number or "", _CAN_TRANSCEIVER_PREFIXES
    )


def _is_uart_shifter(comp: Component) -> bool:
    if comp.label != "ic":
        return False
    return _has_prefix(comp.marking, _UART_LEVEL_SHIFTER_PREFIXES) or _has_prefix(
        comp.part_number or "", _UART_LEVEL_SHIFTER_PREFIXES
    )


def _is_one_wire_device(comp: Component) -> bool:
    if comp.label != "ic":
        return False
    return _has_prefix(comp.marking, _ONE_WIRE_PART_PREFIXES) or _has_prefix(
        comp.part_number or "", _ONE_WIRE_PART_PREFIXES
    )


def _is_resistor(comp: Component) -> bool:
    return comp.label == "resistor"


def _is_connector(comp: Component) -> bool:
    return comp.label in {"connector", "header", "test_point"}


def _security_intel_interfaces(comp: Component) -> list[str]:
    """Return list of protocol strings from component's security_intel if loaded."""
    # security_intel is not on the Component dataclass directly — it lives in
    # the matcher DB.  Callers pass pre-enriched components where the attribute
    # may have been attached at identification time.  Guard gracefully.
    si = getattr(comp, "security_intel", None)
    if not si:
        return []
    return list(si.get("debug_interfaces", []))


# ---------------------------------------------------------------------------
# I2C pull-up resistor value ranges (in ohms)
# ---------------------------------------------------------------------------

def _pullup_speed(ohms: float) -> str:
    """Estimate I2C max speed from pull-up resistance value."""
    if ohms <= 1_000:
        return "Fast-mode+ (1 MHz)"
    if ohms <= 3_300:
        return "Fast-mode (400 kHz)"
    return "Standard-mode (100 kHz)"


def _is_i2c_pullup(ohms: float) -> bool:
    """Typical I2C pull-up range: 1 kΩ – 10 kΩ."""
    return 1_000 <= ohms <= 10_000


# ---------------------------------------------------------------------------
# CAN termination: 120 Ω (or close — EIA code 121 = 120 Ω)
# ---------------------------------------------------------------------------

def _is_can_termination(ohms: float) -> bool:
    return 100 <= ohms <= 130


# ---------------------------------------------------------------------------
# 1-Wire pull-up: typically 4.7 kΩ
# ---------------------------------------------------------------------------

def _is_1wire_pullup(ohms: float) -> bool:
    return 3_000 <= ohms <= 10_000


# ---------------------------------------------------------------------------
# Core inference routines
# ---------------------------------------------------------------------------


def _infer_i2c(
    result: AnalysisResult,
    threshold: float,
) -> BusTopology | None:
    """Infer I2C bus topology."""
    ics = [c for c in result.components if c.label == "ic"]
    resistors = [c for c in result.components if _is_resistor(c)]

    # Collect I2C-capable ICs: MCUs and known I2C peripherals
    i2c_ics: list[Component] = []
    for ic in ics:
        ifaces = _security_intel_interfaces(ic)
        if (
            "I2C" in ifaces
            or _is_mcu(ic)
            or _is_i2c_peripheral(ic)
        ):
            i2c_ics.append(ic)

    if not i2c_ics:
        return None

    # Find pull-up resistors near any I2C IC
    pullup_resistors: list[Component] = []
    pullup_ohms_list: list[float] = []
    for r in resistors:
        ohms = _parse_ohms(r.value or r.marking or "")
        if ohms is None:
            continue
        if not _is_i2c_pullup(ohms):
            continue
        for ic in i2c_ics:
            if _distance(r, ic) <= threshold:
                pullup_resistors.append(r)
                pullup_ohms_list.append(ohms)
                break

    # Require at least one pull-up to be confident there is an I2C bus
    if not pullup_resistors:
        # Low-confidence: MCU + I2C peripheral but no visible pull-up
        if len(i2c_ics) >= 2:
            node_ids = [c.id for c in i2c_ics]
            return BusTopology(
                protocol="I2C",
                confidence=0.35,
                nodes=node_ids,
                characteristics={
                    "pull_ups_found": False,
                    "bus_speed": "unknown (no pull-ups detected)",
                    "device_count": len(i2c_ics),
                },
                security_notes=[
                    "I2C has no authentication — all devices can be enumerated at the bus level.",
                    "EEPROM contents are readable without credentials via I2C.",
                ],
            )
        return None

    # Determine bus speed from the smallest (strongest) pull-up found
    min_ohms = min(pullup_ohms_list)
    speed = _pullup_speed(min_ohms)

    # Count addressable devices (I2C peripherals, excluding MCU as master)
    peripheral_count = sum(1 for c in i2c_ics if _is_i2c_peripheral(c))

    nodes = list({c.id for c in i2c_ics} | {r.id for r in pullup_resistors})

    confidence = min(1.0, 0.5 + 0.2 * len(pullup_resistors) + 0.1 * peripheral_count)

    security_notes = [
        "I2C has no authentication — all devices can be enumerated at the bus level.",
        "EEPROM contents are readable without credentials via I2C.",
    ]
    if peripheral_count > 0:
        security_notes.append(
            f"{peripheral_count} addressable I2C device(s) detected; "
            "attacker can enumerate all addresses (0x00–0x7F)."
        )

    return BusTopology(
        protocol="I2C",
        confidence=confidence,
        nodes=nodes,
        characteristics={
            "pull_ups_found": True,
            "pull_up_count": len(pullup_resistors),
            "pull_up_min_ohms": min_ohms,
            "bus_speed": speed,
            "device_count": len(i2c_ics),
            "addressable_peripherals": peripheral_count,
        },
        security_notes=security_notes,
    )


def _infer_spi(
    result: AnalysisResult,
    threshold: float,
) -> BusTopology | None:
    """Infer SPI bus topology."""
    ics = [c for c in result.components if c.label == "ic"]

    flash_ics: list[Component] = [ic for ic in ics if _is_spi_flash(ic)]
    mcu_ics: list[Component] = [ic for ic in ics if _is_mcu(ic)]

    if not flash_ics:
        return None

    # Associate flash chips with MCUs by proximity
    nodes: list[str] = []
    paired_mcus: set[str] = set()
    for flash in flash_ics:
        nodes.append(flash.id)
        for mcu in mcu_ics:
            if _distance(flash, mcu) <= threshold and mcu.id not in paired_mcus:
                nodes.append(mcu.id)
                paired_mcus.add(mcu.id)

    slave_count = len(flash_ics)
    has_mcu = bool(paired_mcus)

    confidence = min(1.0, 0.55 + 0.15 * slave_count + (0.15 if has_mcu else 0.0))

    security_notes = [
        "SPI flash typically stores device firmware — readable and writable with a test clip (e.g. SOIC8 clip + Bus Pirate / flashrom).",
        "Unprotected SPI flash allows full firmware extraction or persistent implant injection.",
    ]
    if slave_count > 1:
        security_notes.append(
            f"{slave_count} SPI flash chips found; each is an independent firmware extraction surface."
        )

    return BusTopology(
        protocol="SPI",
        confidence=confidence,
        nodes=list(dict.fromkeys(nodes)),  # preserve order, deduplicate
        characteristics={
            "flash_chip_count": slave_count,
            "cs_lines": slave_count,
            "mcu_paired": has_mcu,
            "bus_type": "4-wire SPI (MOSI/MISO/SCK/CS)",
        },
        security_notes=security_notes,
    )


def _infer_uart(
    result: AnalysisResult,
    threshold: float,
) -> BusTopology | None:
    """Infer UART/serial topology."""
    ics = [c for c in result.components if c.label == "ic"]
    connectors = [c for c in result.components if _is_connector(c)]

    shifters: list[Component] = [ic for ic in ics if _is_uart_shifter(ic)]
    mcu_ics: list[Component] = [ic for ic in ics if _is_mcu(ic)]

    if not shifters:
        return None

    nodes: list[str] = [s.id for s in shifters]

    # Check RS-232 (MAX232 family) vs. USB-UART bridge (CP2102, CH340, FT232)
    rs232_prefixes = {"max232", "max3232", "sp3232", "st3232", "st232", "max202"}
    usb_uart_prefixes = {"ch340", "ch341", "ch342", "cp2102", "cp2104", "cp2105", "ft232", "ft231", "ft234", "pl2303", "mcp2221"}

    level_type = "unknown"
    for s in shifters:
        text = _norm(s.marking + " " + (s.part_number or ""))
        if any(p in text for p in rs232_prefixes):
            level_type = "RS-232 (±12 V)"
            break
        if any(p in text for p in usb_uart_prefixes):
            level_type = "USB-UART bridge (TTL/3.3 V)"
            break

    # Associate MCUs near shifters
    paired_mcus: set[str] = set()
    for shifter in shifters:
        for mcu in mcu_ics:
            if _distance(shifter, mcu) <= threshold:
                paired_mcus.add(mcu.id)
    nodes.extend(paired_mcus)

    # Connectors near shifters suggest external access point
    near_connectors: list[str] = []
    for shifter in shifters:
        for conn in connectors:
            if _distance(shifter, conn) <= threshold:
                near_connectors.append(conn.id)
    nodes.extend(near_connectors)

    has_connector = bool(near_connectors)
    confidence = min(1.0, 0.55 + 0.15 * len(shifters) + (0.2 if has_connector else 0.0))

    security_notes = [
        "UART debug consoles frequently expose bootloader prompts or root shell access.",
        "No authentication is mandated by the UART protocol.",
    ]
    if has_connector:
        security_notes.append(
            "Level shifter connects to an external connector — debug UART is physically accessible."
        )
    if level_type.startswith("USB"):
        security_notes.append(
            "USB-UART bridge allows direct host-side access via any USB port; "
            "no additional hardware adapter required."
        )

    return BusTopology(
        protocol="UART",
        confidence=confidence,
        nodes=list(dict.fromkeys(nodes)),
        characteristics={
            "level_type": level_type,
            "shifter_count": len(shifters),
            "external_connector": has_connector,
            "likely_debug_console": True,
        },
        security_notes=security_notes,
    )


def _infer_can(
    result: AnalysisResult,
    threshold: float,
) -> BusTopology | None:
    """Infer CAN bus topology."""
    ics = [c for c in result.components if c.label == "ic"]
    resistors = [c for c in result.components if _is_resistor(c)]

    transceivers: list[Component] = [ic for ic in ics if _is_can_transceiver(ic)]
    if not transceivers:
        return None

    # Look for 120 Ω termination resistors near transceivers
    term_resistors: list[Component] = []
    for r in resistors:
        ohms = _parse_ohms(r.value or r.marking or "")
        if ohms is None:
            continue
        if not _is_can_termination(ohms):
            continue
        for txcvr in transceivers:
            if _distance(r, txcvr) <= threshold:
                term_resistors.append(r)
                break

    has_termination = bool(term_resistors)
    nodes = [t.id for t in transceivers] + [r.id for r in term_resistors]

    confidence = min(1.0, 0.55 + 0.15 * len(transceivers) + (0.2 if has_termination else 0.0))

    characteristics: dict = {
        "bus_type": "2-wire differential (CAN-H / CAN-L)",
        "transceiver_count": len(transceivers),
        "termination_found": has_termination,
    }
    if has_termination:
        characteristics["termination_note"] = "120 Ω termination detected — bus end or star topology node"
    else:
        characteristics["termination_note"] = (
            "No 120 Ω termination visible — may be on opposite board end or split across boards"
        )

    security_notes = [
        "CAN bus has no authentication or message integrity by default.",
        "An attacker with physical bus access can inject arbitrary CAN frames.",
    ]
    if transceivers:
        security_notes.append(
            "Automotive/industrial CAN transceiver detected — high relevance for vehicle security assessments."
        )

    return BusTopology(
        protocol="CAN",
        confidence=confidence,
        nodes=list(dict.fromkeys(nodes)),
        characteristics=characteristics,
        security_notes=security_notes,
    )


def _infer_1wire(
    result: AnalysisResult,
    threshold: float,
) -> BusTopology | None:
    """Infer 1-Wire topology."""
    ics = [c for c in result.components if c.label == "ic"]
    resistors = [c for c in result.components if _is_resistor(c)]

    ow_devices: list[Component] = [ic for ic in ics if _is_one_wire_device(ic)]
    if not ow_devices:
        return None

    # Look for a single pull-up resistor near 1-Wire devices
    pullup_resistors: list[Component] = []
    for r in resistors:
        ohms = _parse_ohms(r.value or r.marking or "")
        if ohms is None:
            continue
        if not _is_1wire_pullup(ohms):
            continue
        for dev in ow_devices:
            if _distance(r, dev) <= threshold:
                pullup_resistors.append(r)
                break

    nodes = [d.id for d in ow_devices] + [r.id for r in pullup_resistors]
    has_pullup = bool(pullup_resistors)

    confidence = min(1.0, 0.5 + 0.2 * len(ow_devices) + (0.15 if has_pullup else 0.0))

    # Check if any device might be used for key storage
    key_storage_parts = {"ds2431", "ds2433", "ds2413"}
    has_key_storage = any(
        any(p in _norm(d.marking + " " + (d.part_number or "")) for p in key_storage_parts)
        for d in ow_devices
    )

    security_notes = [
        "1-Wire devices can be enumerated by reading 64-bit ROM codes.",
        "DS18B20 and similar sensors have no authentication — data can be spoofed.",
    ]
    if has_key_storage:
        security_notes.append(
            "1-Wire EEPROM detected — may be used for license/key storage; "
            "contents accessible with a 1-Wire master."
        )

    return BusTopology(
        protocol="1-Wire",
        confidence=confidence,
        nodes=list(dict.fromkeys(nodes)),
        characteristics={
            "device_count": len(ow_devices),
            "pull_up_found": has_pullup,
            "bus_type": "single-wire, open-drain with pull-up",
        },
        security_notes=security_notes,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def infer_topology(result: AnalysisResult) -> list[BusTopology]:
    """Infer protocol bus topology from a completed AnalysisResult.

    Analyses component bounding boxes, markings, and part numbers to identify
    I2C, SPI, UART, CAN, and 1-Wire buses present on the board.

    Args:
        result: AnalysisResult populated by the Pipeline (components required;
                traces are used when present but not mandatory).

    Returns:
        List of BusTopology objects, one per detected bus, sorted by
        confidence descending.
    """
    if not result.components:
        return []

    board_dim = result.board_dimensions if result.board_dimensions != (0, 0) else (800, 600)
    threshold = _proximity_threshold(board_dim)

    buses: list[BusTopology] = []

    for fn in (_infer_i2c, _infer_spi, _infer_uart, _infer_can, _infer_1wire):
        topo = fn(result, threshold)
        if topo is not None:
            buses.append(topo)

    buses.sort(key=lambda b: b.confidence, reverse=True)
    return buses


# ---------------------------------------------------------------------------
# Formatting helper (used by CLI)
# ---------------------------------------------------------------------------


def format_topology(buses: list[BusTopology]) -> str:
    """Render topology findings as a human-readable string."""
    if not buses:
        return "No protocol bus topology detected."

    lines: list[str] = [
        f"Protocol Topology Analysis — {len(buses)} bus(es) detected",
        "",
    ]
    for bus in buses:
        lines.append(f"  {bus.protocol}  (confidence: {bus.confidence:.0%})")
        lines.append(f"    Nodes: {', '.join(bus.nodes)}")
        for k, v in bus.characteristics.items():
            lines.append(f"    {k}: {v}")
        for note in bus.security_notes:
            lines.append(f"    [!] {note}")
        lines.append("")

    return "\n".join(lines)
