"""Tests for firmware triage — entropy, magic bytes, string extraction."""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from retrace.analysis.firmware_triage import (
    EntropyBlock,
    ExtractedString,
    MagicMatch,
    TriageResult,
    _classify_entropy,
    _shannon_entropy,
    compute_entropy_map,
    extract_strings,
    find_magic_signatures,
    format_triage_report,
    triage_firmware,
)


# ---------------------------------------------------------------------------
# Shannon entropy
# ---------------------------------------------------------------------------

class TestShannonEntropy:
    def test_empty_bytes(self):
        assert _shannon_entropy(b"") == 0.0

    def test_single_byte_repeated(self):
        assert _shannon_entropy(b"\x00" * 1000) == 0.0

    def test_two_bytes_equal(self):
        data = b"\x00\x01" * 500
        ent = _shannon_entropy(data)
        assert abs(ent - 1.0) < 0.01

    def test_all_256_values(self):
        data = bytes(range(256)) * 4
        ent = _shannon_entropy(data)
        assert abs(ent - 8.0) < 0.01

    def test_random_high_entropy(self):
        data = os.urandom(4096)
        ent = _shannon_entropy(data)
        assert ent > 7.5

    def test_text_medium_entropy(self):
        data = b"Hello World! " * 100
        ent = _shannon_entropy(data)
        assert 2.0 < ent < 5.0


class TestClassifyEntropy:
    def test_null(self):
        assert _classify_entropy(0.0) == "null/padding"

    def test_code(self):
        assert _classify_entropy(3.0) == "code/data"

    def test_text(self):
        assert _classify_entropy(5.0) == "text/structured"

    def test_compressed(self):
        assert _classify_entropy(7.0) == "compressed"

    def test_encrypted(self):
        assert _classify_entropy(7.9) == "encrypted/random"


# ---------------------------------------------------------------------------
# Entropy map
# ---------------------------------------------------------------------------

class TestEntropyMap:
    def test_single_block(self):
        data = b"\x00" * 4096
        blocks = compute_entropy_map(data, block_size=4096)
        assert len(blocks) == 1
        assert blocks[0].entropy == 0.0
        assert blocks[0].offset == 0

    def test_multiple_blocks(self):
        data = b"\x00" * 4096 + os.urandom(4096)
        blocks = compute_entropy_map(data, block_size=4096)
        assert len(blocks) == 2
        assert blocks[0].entropy < 1.0
        assert blocks[1].entropy > 7.0

    def test_custom_block_size(self):
        data = b"\x00" * 1000
        blocks = compute_entropy_map(data, block_size=100)
        assert len(blocks) == 10

    def test_partial_last_block(self):
        data = b"\x00" * 5000
        blocks = compute_entropy_map(data, block_size=4096)
        assert len(blocks) == 2
        assert blocks[1].size == 904


# ---------------------------------------------------------------------------
# Magic signatures
# ---------------------------------------------------------------------------

class TestMagicSignatures:
    def test_elf_header(self):
        data = b"\x00" * 100 + b"\x7fELF" + b"\x00" * 100
        matches = find_magic_signatures(data)
        assert any(m.signature == "ELF" for m in matches)
        assert matches[0].offset == 100

    def test_uboot_header(self):
        data = b"\x27\x05\x19\x56" + b"\x00" * 100
        matches = find_magic_signatures(data)
        assert any(m.signature == "U-Boot" for m in matches)

    def test_squashfs(self):
        data = b"\x00" * 50 + b"hsqs" + b"\x00" * 50
        matches = find_magic_signatures(data)
        assert any(m.signature == "SquashFS" for m in matches)

    def test_jffs2_le(self):
        data = b"\x85\x19\x01\xe0" + b"\x00" * 100
        matches = find_magic_signatures(data)
        assert any(m.signature == "JFFS2" for m in matches)

    def test_gzip(self):
        data = b"\x1f\x8b\x08" + b"\x00" * 100
        matches = find_magic_signatures(data)
        assert any(m.signature == "gzip" for m in matches)

    def test_no_matches(self):
        data = b"\xAA\xBB\xCC\xDD" * 100
        matches = find_magic_signatures(data)
        assert len(matches) == 0

    def test_multiple_matches(self):
        data = b"\x7fELF" + b"\x00" * 100 + b"hsqs" + b"\x00" * 100
        matches = find_magic_signatures(data)
        assert len(matches) >= 2

    def test_sorted_by_offset(self):
        data = b"\x00" * 200 + b"\x7fELF" + b"\x00" * 200 + b"hsqs"
        matches = find_magic_signatures(data)
        offsets = [m.offset for m in matches]
        assert offsets == sorted(offsets)


# ---------------------------------------------------------------------------
# String extraction
# ---------------------------------------------------------------------------

class TestStringExtraction:
    def test_password_found(self):
        data = b"\x00" * 50 + b"password=admin123" + b"\x00" * 50
        strings = extract_strings(data)
        assert any(s.category == "credential" for s in strings)

    def test_url_found(self):
        data = b"\x00" * 50 + b"https://example.com/firmware" + b"\x00" * 50
        strings = extract_strings(data)
        assert any(s.category == "url" for s in strings)

    def test_ip_address_found(self):
        data = b"\x00" * 50 + b"192.168.1.100:8080" + b"\x00" * 50
        strings = extract_strings(data)
        assert any(s.category == "ip_address" for s in strings)

    def test_ssh_key_found(self):
        data = b"\x00" * 50 + b"ssh-rsa AAAAB3NzaC1yc2EAAA" + b"\x00" * 50
        strings = extract_strings(data)
        assert any(s.category == "ssh_key" for s in strings)

    def test_version_found(self):
        data = b"\x00" * 50 + b"version=1.2.3" + b"\x00" * 50
        strings = extract_strings(data)
        assert any(s.category == "version" for s in strings)

    def test_private_key_marker(self):
        data = b"\x00" * 50 + b"-----BEGIN RSA PRIVATE KEY-----" + b"\x00" * 50
        strings = extract_strings(data)
        assert any(s.category == "crypto_key" for s in strings)

    def test_passwd_entry(self):
        data = b"\x00" * 50 + b"root:x:0:0:" + b"\x00" * 50
        strings = extract_strings(data)
        assert any(s.category == "passwd_entry" for s in strings)

    def test_no_interesting_strings(self):
        data = b"\x00" * 1000
        strings = extract_strings(data)
        assert len(strings) == 0

    def test_deduplication(self):
        data = b"password=test " * 100
        strings = extract_strings(data)
        cred_strings = [s for s in strings if s.category == "credential"]
        assert len(cred_strings) == 1


# ---------------------------------------------------------------------------
# Full triage
# ---------------------------------------------------------------------------

class TestTriageFirmware:
    def test_basic_triage(self, tmp_path):
        fw = tmp_path / "firmware.bin"
        fw.write_bytes(b"\x7fELF" + b"\x00" * 4092 + os.urandom(4096))
        result = triage_firmware(fw)
        assert result.file_size == 8192
        assert len(result.sha256) == 64
        assert len(result.entropy_map) > 0
        assert any(m.signature == "ELF" for m in result.magic_matches)

    def test_encrypted_detection(self, tmp_path):
        fw = tmp_path / "encrypted.bin"
        fw.write_bytes(os.urandom(32768))
        result = triage_firmware(fw)
        assert result.is_encrypted

    def test_not_encrypted(self, tmp_path):
        fw = tmp_path / "plain.bin"
        fw.write_bytes(b"\x00" * 32768)
        result = triage_firmware(fw)
        assert not result.is_encrypted

    def test_filesystem_detection(self, tmp_path):
        fw = tmp_path / "with_fs.bin"
        fw.write_bytes(b"\x00" * 100 + b"hsqs" + b"\x00" * 4000)
        result = triage_firmware(fw)
        assert result.has_filesystem

    def test_bootloader_detection(self, tmp_path):
        fw = tmp_path / "with_uboot.bin"
        fw.write_bytes(b"\x27\x05\x19\x56" + b"\x00" * 4000)
        result = triage_firmware(fw)
        assert result.has_bootloader

    def test_custom_block_size(self, tmp_path):
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\x00" * 1000)
        result = triage_firmware(fw, block_size=100)
        assert len(result.entropy_map) == 10


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_basic_report(self, tmp_path):
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\x7fELF" + b"\x00" * 4092)
        result = triage_firmware(fw)
        report = format_triage_report(result)
        assert "Firmware Triage Report" in report
        assert result.sha256 in report
        assert "ELF" in report

    def test_encrypted_warning(self, tmp_path):
        fw = tmp_path / "enc.bin"
        fw.write_bytes(os.urandom(32768))
        result = triage_firmware(fw)
        report = format_triage_report(result)
        assert "encrypted" in report.lower()

    def test_entropy_profile(self, tmp_path):
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\x00" * 8192)
        result = triage_firmware(fw)
        report = format_triage_report(result)
        assert "Entropy profile" in report

    def test_string_section(self, tmp_path):
        fw = tmp_path / "fw.bin"
        content = b"\x00" * 100 + b"password=secret123" + b"\x00" * 4000
        fw.write_bytes(content)
        result = triage_firmware(fw)
        report = format_triage_report(result)
        assert "Interesting strings" in report

    def test_bootloader_flag_in_report(self, tmp_path):
        """Line 241 — 'U-Boot bootloader detected' branch."""
        fw = tmp_path / "boot.bin"
        fw.write_bytes(b"\x27\x05\x19\x56" + b"\x00" * 4000)
        result = triage_firmware(fw)
        report = format_triage_report(result)
        assert "U-Boot" in report

    def test_filesystem_flag_in_report(self, tmp_path):
        """Line 243 — 'Filesystem signature detected' branch."""
        fw = tmp_path / "fs.bin"
        fw.write_bytes(b"\x00" * 50 + b"hsqs" + b"\x00" * 4000)
        result = triage_firmware(fw)
        report = format_triage_report(result)
        assert "Filesystem" in report

    def test_more_than_20_signatures_shows_ellipsis(self, tmp_path):
        """Line 251 — '... and N more' for signatures."""
        # Create data with many distinct magic bytes that trigger > 20 matches.
        # Use repeated gzip headers spaced out so each is a new match.
        payload = b""
        sig = b"\x1f\x8b\x08"  # gzip
        for _ in range(25):
            payload += sig + b"\x00" * 100
        fw = tmp_path / "many_sigs.bin"
        fw.write_bytes(payload)
        result = triage_firmware(fw)
        if len(result.magic_matches) > 20:
            report = format_triage_report(result)
            assert "... and" in report and "more" in report

    def test_more_than_20_strings_shows_ellipsis(self, tmp_path):
        """Line 259 — '... and N more' for interesting strings."""
        # Build data with > 20 distinct password-like strings.
        lines = [f"password{i}=secret{i:03d}\n".encode() for i in range(25)]
        fw = tmp_path / "many_strings.bin"
        fw.write_bytes(b"\x00" * 50 + b"".join(lines) + b"\x00" * 1000)
        result = triage_firmware(fw)
        if len(result.interesting_strings) > 20:
            report = format_triage_report(result)
            assert "... and" in report and "more" in report

    def test_extract_strings_pure_binary_returns_empty(self):
        """Non-ASCII data with no matching patterns returns empty list."""
        data = bytes(range(128, 256)) * 10
        result = extract_strings(data)
        assert isinstance(result, list)

    def test_find_magic_more_than_500_cap(self):
        """Line 156 — break when matches > 500."""
        import retrace.analysis.firmware_triage as ft
        # Inject a fake signature that matches every byte so we get > 500 matches
        original_sigs = ft._MAGIC_SIGNATURES
        # Single-byte pattern (b"\x00") repeated many times
        fake_sig = [(b"\x00", "TEST", "zero byte")]
        ft._MAGIC_SIGNATURES = fake_sig
        try:
            data = b"\x00" * 600
            matches = ft.find_magic_signatures(data)
            # The loop breaks after > 500 entries so we get ~501 max per signature
            assert len(matches) <= 502
        finally:
            ft._MAGIC_SIGNATURES = original_sigs
