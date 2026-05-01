"""Sigrok / PulseView session metadata export.

Generates a Sigrok session file (.sr) metadata that pre-labels logic
analyzer channels based on detected debug interfaces and probe advisor
recommendations. Users can import this into PulseView to start capturing
with channels already named and protocol decoders pre-configured.

The .sr format is a ZIP archive containing:
  - metadata   (INI-style session config)
  - header     (version info)

This module generates the metadata content. Actual .sr ZIP creation
requires the sigrok session format.
"""

from __future__ import annotations

import configparser
import io
import zipfile
from typing import Any

_PROTOCOL_DECODERS: dict[str, dict[str, Any]] = {
    "UART": {
        "decoder": "uart",
        "channels": {"RX": 0, "TX": 1},
        "options": {"baudrate": 115200, "data_bits": 8, "parity": "none", "stop_bits": 1},
    },
    "SPI": {
        "decoder": "spi",
        "channels": {"CLK": 0, "MISO": 1, "MOSI": 2, "CS#": 3},
        "options": {"cs_polarity": "active-low", "bitorder": "msb-first", "cpol": 0, "cpha": 0},
    },
    "I2C": {
        "decoder": "i2c",
        "channels": {"SCL": 0, "SDA": 1},
        "options": {"address_format": "shifted"},
    },
    "JTAG": {
        "decoder": "jtag",
        "channels": {"TDI": 0, "TDO": 1, "TCK": 2, "TMS": 3},
        "options": {},
    },
    "SWD": {
        "decoder": "swd",
        "channels": {"SWDIO": 0, "SWCLK": 1},
        "options": {},
    },
}


def generate_sigrok_metadata(
    interfaces: list[dict[str, Any]],
    sample_rate: int = 1_000_000,
    board_name: str = "",
) -> str:
    """Generate Sigrok session metadata INI content.

    Args:
        interfaces: List of detected interface dicts (from debug_interfaces plugin).
        sample_rate: Capture sample rate in Hz.
        board_name: Optional board name for the session label.

    Returns:
        INI-formatted metadata string for a .sr session file.
    """
    config = configparser.ConfigParser()
    config.optionxform = str  # type: ignore[assignment]

    config["global"] = {
        "sigrok version": "0.5.2",
        "retrace version": "0.3.0",
    }

    label = board_name or "retrace_capture"
    config["device 1"] = {
        "name": label,
        "capturefile": "logic-1",
        "total probes": "0",
        "samplerate": f"{sample_rate} Hz",
        "total analog": "0",
    }

    channel_idx = 0
    for iface in interfaces:
        iface_type = iface.get("interface", "")
        proto = _PROTOCOL_DECODERS.get(iface_type)
        if not proto:
            continue

        for pin_name in proto["channels"]:
            config["device 1"][f"probe{channel_idx + 1}"] = (
                f"{iface_type}_{pin_name}"
            )
            channel_idx += 1

    config["device 1"]["total probes"] = str(channel_idx)

    output = io.StringIO()
    config.write(output)
    return output.getvalue()


def generate_sigrok_session(
    interfaces: list[dict[str, Any]],
    sample_rate: int = 1_000_000,
    board_name: str = "",
) -> bytes:
    """Generate a complete .sr ZIP archive with metadata.

    Returns:
        Bytes of a ZIP archive in .sr format.
    """
    metadata = generate_sigrok_metadata(interfaces, sample_rate, board_name)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("version", "2")
        zf.writestr("metadata", metadata)
    return buf.getvalue()


def get_decoder_config(interface_type: str) -> dict[str, Any] | None:
    """Get the protocol decoder config for an interface type."""
    return _PROTOCOL_DECODERS.get(interface_type)


def format_sigrok_summary(interfaces: list[dict[str, Any]]) -> str:
    """Format a human-readable summary of the Sigrok session."""
    if not interfaces:
        return "No interfaces to map to Sigrok channels."

    lines = ["Sigrok / PulseView Channel Map", ""]
    total_ch = 0

    for iface in interfaces:
        iface_type = iface.get("interface", "")
        proto = _PROTOCOL_DECODERS.get(iface_type)
        if not proto:
            continue

        lines.append(f"  {iface_type} — decoder: {proto['decoder']}")
        for pin_name, ch_offset in proto["channels"].items():
            ch = total_ch + ch_offset
            lines.append(f"    CH{ch}: {iface_type}_{pin_name}")
        total_ch += len(proto["channels"])

        if proto["options"]:
            opts = ", ".join(f"{k}={v}" for k, v in proto["options"].items())
            lines.append(f"    Options: {opts}")
        lines.append("")

    lines.append(f"Total channels: {total_ch}")
    lines.append("Import: PulseView → File → Import → Sigrok session (.sr)")
    return "\n".join(lines)
