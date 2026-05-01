"""Firmware triage — quick binary analysis of dumped firmware images.

Performs first-pass triage on firmware dumps extracted via the retrace
workflow: entropy profiling (detect encrypted/compressed regions),
magic byte identification (ELF, PE, U-Boot, squashfs, JFFS2, cramfs),
string extraction for keys/credentials/version info, and section mapping.

This closes the kill chain: board photo → probe → dump → triage.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EntropyBlock:
    """Entropy measurement for a firmware region."""
    offset: int
    size: int
    entropy: float
    classification: str


@dataclass
class MagicMatch:
    """A recognized file signature within the firmware."""
    offset: int
    signature: str
    description: str
    size_hint: int = 0


@dataclass
class ExtractedString:
    """An interesting string found in the firmware."""
    offset: int
    value: str
    category: str


@dataclass
class TriageResult:
    """Complete firmware triage output."""
    file_path: str
    file_size: int
    sha256: str
    entropy_map: list[EntropyBlock] = field(default_factory=list)
    magic_matches: list[MagicMatch] = field(default_factory=list)
    interesting_strings: list[ExtractedString] = field(default_factory=list)
    overall_entropy: float = 0.0
    is_encrypted: bool = False
    has_filesystem: bool = False
    has_bootloader: bool = False


_MAGIC_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"\x7fELF", "ELF", "ELF executable"),
    (b"MZ", "PE/COFF", "Windows PE executable"),
    (b"\x27\x05\x19\x56", "U-Boot", "U-Boot image header"),
    (b"hsqs", "SquashFS", "SquashFS filesystem (little-endian)"),
    (b"sqsh", "SquashFS", "SquashFS filesystem (big-endian)"),
    (b"\x85\x19\x01\xe0", "JFFS2", "JFFS2 filesystem (little-endian)"),
    (b"\xe0\x01\x19\x85", "JFFS2", "JFFS2 filesystem (big-endian)"),
    (b"\x28\xcd\x3d\x45", "CramFS", "CramFS compressed filesystem"),
    (b"\x1f\x8b\x08", "gzip", "gzip compressed data"),
    (b"\xfd\x37\x7a\x58\x5a\x00", "xz", "xz compressed data"),
    (b"BZ", "bzip2", "bzip2 compressed data"),
    (b"\x89PNG", "PNG", "PNG image"),
    (b"\xd0\x0d\xfe\xed", "FDT", "Device Tree Blob (flattened)"),
    (b"UBI#", "UBI", "UBI erase count header"),
    (b"\xde\xad\xc0\xde", "Firmware header", "Vendor firmware header marker"),
    (b"LZMA", "LZMA", "LZMA compressed data"),
    (b"\x5d\x00\x00", "LZMA-raw", "LZMA compressed stream"),
]

_INTERESTING_PATTERNS: list[tuple[str, str]] = [
    (r"(?:password|passwd|pwd)\s*[:=]\s*\S+", "credential"),
    (r"(?:api[_-]?key|secret[_-]?key|token)\s*[:=]\s*\S+", "api_key"),
    (r"(?:ssh-rsa|ssh-ed25519|ecdsa-sha2)\s+\S+", "ssh_key"),
    (r"-----BEGIN (?:RSA |EC |DSA )?(?:PRIVATE|PUBLIC) KEY-----", "crypto_key"),
    (r"https?://\S+", "url"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b", "ip_address"),
    (r"(?:root|admin|user):[x*]?:\d+:\d+:", "passwd_entry"),
    (r"(?:v|version)\s*[:=]?\s*\d+\.\d+\.\d+", "version"),
    (r"/etc/(?:passwd|shadow|hosts|resolv\.conf)", "config_path"),
    (r"(?:BOOT|boot)(?:_MODE|_SEL|0|1|_CFG)", "boot_config"),
]


def _shannon_entropy(data: bytes) -> float:
    """Calculate Shannon entropy of a byte sequence (0.0 - 8.0 bits)."""
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    length = len(data)
    entropy = 0.0
    for count in counts:
        if count > 0:
            p = count / length
            entropy -= p * math.log2(p)
    return entropy


def _classify_entropy(entropy: float) -> str:
    """Classify an entropy value into a human-readable category."""
    if entropy < 1.0:
        return "null/padding"
    if entropy < 4.0:
        return "code/data"
    if entropy < 6.0:
        return "text/structured"
    if entropy < 7.5:
        return "compressed"
    return "encrypted/random"


def compute_entropy_map(data: bytes, block_size: int = 4096) -> list[EntropyBlock]:
    """Compute block-wise entropy across the firmware image."""
    blocks: list[EntropyBlock] = []
    for offset in range(0, len(data), block_size):
        chunk = data[offset:offset + block_size]
        ent = _shannon_entropy(chunk)
        blocks.append(EntropyBlock(
            offset=offset,
            size=len(chunk),
            entropy=round(ent, 3),
            classification=_classify_entropy(ent),
        ))
    return blocks


def find_magic_signatures(data: bytes) -> list[MagicMatch]:
    """Scan for known file format signatures."""
    matches: list[MagicMatch] = []
    for magic, sig_name, description in _MAGIC_SIGNATURES:
        start = 0
        while True:
            idx = data.find(magic, start)
            if idx == -1:
                break
            matches.append(MagicMatch(
                offset=idx,
                signature=sig_name,
                description=description,
            ))
            start = idx + 1
            if len(matches) > 500:
                break
    matches.sort(key=lambda m: m.offset)
    return matches


def extract_strings(data: bytes, min_length: int = 8) -> list[ExtractedString]:
    """Extract interesting strings from firmware binary."""
    try:
        text = data.decode("ascii", errors="ignore")
    except Exception:
        text = ""

    results: list[ExtractedString] = []
    seen: set[str] = set()

    for pattern_str, category in _INTERESTING_PATTERNS:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        for match in pattern.finditer(text):
            value = match.group(0)[:200]
            if value not in seen:
                seen.add(value)
                byte_offset = match.start()
                results.append(ExtractedString(
                    offset=byte_offset,
                    value=value,
                    category=category,
                ))
                if len(results) > 200:
                    break

    return results


def triage_firmware(file_path: str | Path, block_size: int = 4096) -> TriageResult:
    """Perform full first-pass triage on a firmware dump."""
    import hashlib

    path = Path(file_path)
    data = path.read_bytes()

    sha256 = hashlib.sha256(data).hexdigest()
    entropy_map = compute_entropy_map(data, block_size)
    magic_matches = find_magic_signatures(data)
    interesting_strings = extract_strings(data)
    overall_entropy = _shannon_entropy(data)

    fs_sigs = {"SquashFS", "JFFS2", "CramFS", "UBI"}
    has_filesystem = any(m.signature in fs_sigs for m in magic_matches)
    has_bootloader = any(m.signature == "U-Boot" for m in magic_matches)

    high_entropy_blocks = sum(1 for b in entropy_map if b.entropy > 7.5)
    is_encrypted = (
        len(entropy_map) > 0
        and high_entropy_blocks / len(entropy_map) > 0.8
    )

    return TriageResult(
        file_path=str(path),
        file_size=len(data),
        sha256=sha256,
        entropy_map=entropy_map,
        magic_matches=magic_matches,
        interesting_strings=interesting_strings,
        overall_entropy=round(overall_entropy, 3),
        is_encrypted=is_encrypted,
        has_filesystem=has_filesystem,
        has_bootloader=has_bootloader,
    )


def format_triage_report(result: TriageResult) -> str:
    """Format triage results as a human-readable report."""
    lines = [
        "Firmware Triage Report",
        f"{'=' * 60}",
        f"  File: {result.file_path}",
        f"  Size: {result.file_size:,} bytes ({result.file_size / 1024:.1f} KB)",
        f"  SHA-256: {result.sha256}",
        f"  Overall entropy: {result.overall_entropy:.3f} bits/byte",
        "",
    ]

    if result.is_encrypted:
        lines.append("  [!] HIGH ENTROPY — firmware appears encrypted or fully compressed")
    if result.has_bootloader:
        lines.append("  [*] U-Boot bootloader detected")
    if result.has_filesystem:
        lines.append("  [*] Filesystem signature detected")
    lines.append("")

    if result.magic_matches:
        lines.append(f"  Signatures ({len(result.magic_matches)}):")
        for m in result.magic_matches[:20]:
            lines.append(f"    0x{m.offset:08X}  {m.signature:12s}  {m.description}")
        if len(result.magic_matches) > 20:
            lines.append(f"    ... and {len(result.magic_matches) - 20} more")
        lines.append("")

    if result.interesting_strings:
        lines.append(f"  Interesting strings ({len(result.interesting_strings)}):")
        for s in result.interesting_strings[:20]:
            lines.append(f"    0x{s.offset:08X}  [{s.category}]  {s.value}")
        if len(result.interesting_strings) > 20:
            lines.append(f"    ... and {len(result.interesting_strings) - 20} more")
        lines.append("")

    ent_classes: dict[str, int] = {}
    for b in result.entropy_map:
        ent_classes[b.classification] = ent_classes.get(b.classification, 0) + 1
    if ent_classes:
        lines.append("  Entropy profile:")
        for cls, count in sorted(ent_classes.items(), key=lambda x: -x[1]):
            pct = count / len(result.entropy_map) * 100
            lines.append(f"    {cls:20s}  {count:4d} blocks  ({pct:.0f}%)")

    return "\n".join(lines)
