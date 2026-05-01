"""Tests for attack path ranking module."""

from __future__ import annotations

from dataclasses import dataclass, field

from retrace.analysis.attack_path import (
    AttackEdge,
    AttackPath,
    format_attack_paths,
    rank_attack_paths,
)


@dataclass
class _Comp:
    id: str
    label: str = "ic"
    marking: str = ""
    part_number: str = ""
    confidence: float = 0.9


@dataclass
class _Trace:
    id: str = "T1"
    from_component: str = ""
    to_component: str = ""
    points: list = field(default_factory=list)


@dataclass
class _Result:
    components: list = field(default_factory=list)
    traces: list = field(default_factory=list)


class TestRankAttackPaths:
    def test_empty_result(self):
        result = _Result()
        assert rank_attack_paths(result) == []

    def test_no_traces(self):
        result = _Result(components=[_Comp(id="U1")])
        assert rank_attack_paths(result) == []

    def test_no_entry_points(self):
        result = _Result(
            components=[
                _Comp(id="U1", label="ic", marking="STM32"),
                _Comp(id="U2", label="ic", marking="W25Q128 flash"),
            ],
            traces=[_Trace(from_component="U1", to_component="U2")],
        )
        assert rank_attack_paths(result) == []

    def test_no_high_value_targets(self):
        result = _Result(
            components=[
                _Comp(id="J1", label="connector", marking="JTAG debug"),
                _Comp(id="R1", label="resistor", marking="10K"),
            ],
            traces=[_Trace(from_component="J1", to_component="R1")],
        )
        assert rank_attack_paths(result) == []

    def test_single_jtag_to_mcu(self):
        result = _Result(
            components=[
                _Comp(id="J1", label="connector", marking="JTAG"),
                _Comp(id="U1", label="ic", marking="STM32F103"),
            ],
            traces=[_Trace(from_component="J1", to_component="U1")],
        )
        paths = rank_attack_paths(result)
        assert len(paths) >= 1
        top = paths[0]
        assert top.entry_point == "J1"
        assert top.target == "U1"
        assert top.total_score > 0

    def test_spi_flash_path_ranks_high(self):
        result = _Result(
            components=[
                _Comp(id="J1", label="connector", marking="JTAG"),
                _Comp(id="U1", label="ic", marking="CPU SoC"),
                _Comp(id="U2", label="ic", marking="W25Q128 flash"),
            ],
            traces=[
                _Trace(id="T1", from_component="J1", to_component="U1"),
                _Trace(id="T2", from_component="U1", to_component="U2"),
            ],
        )
        paths = rank_attack_paths(result)
        flash_paths = [p for p in paths if p.target == "U2"]
        assert len(flash_paths) >= 1

    def test_multi_hop_score_is_product(self):
        result = _Result(
            components=[
                _Comp(id="J1", label="connector", marking="JTAG"),
                _Comp(id="U1", label="ic", marking="CPU"),
                _Comp(id="U2", label="ic", marking="FPGA spartan"),
            ],
            traces=[
                _Trace(id="T1", from_component="J1", to_component="U1"),
                _Trace(id="T2", from_component="U1", to_component="U2"),
            ],
        )
        paths = rank_attack_paths(result)
        for p in paths:
            if len(p.edges) > 1:
                product = 1.0
                for e in p.edges:
                    product *= e.score
                target_score = 0.85  # fpga
                assert abs(p.total_score - product * target_score) < 0.01

    def test_top_k_limits_results(self):
        result = _Result(
            components=[
                _Comp(id="J1", label="connector", marking="JTAG"),
                _Comp(id="U1", label="ic", marking="STM32 mcu"),
                _Comp(id="U2", label="ic", marking="W25Q128 flash"),
                _Comp(id="U3", label="ic", marking="FPGA spartan"),
            ],
            traces=[
                _Trace(id="T1", from_component="J1", to_component="U1"),
                _Trace(id="T2", from_component="U1", to_component="U2"),
                _Trace(id="T3", from_component="U1", to_component="U3"),
            ],
        )
        paths = rank_attack_paths(result, top_k=2)
        assert len(paths) <= 2

    def test_entry_point_must_be_connector_or_header(self):
        result = _Result(
            components=[
                _Comp(id="J1", label="connector", marking="JTAG"),
                _Comp(id="U1", label="ic", marking="STM32 mcu"),
            ],
            traces=[_Trace(from_component="J1", to_component="U1")],
        )
        paths = rank_attack_paths(result)
        for p in paths:
            assert p.entry_point == "J1"

    def test_test_point_is_valid_entry(self):
        result = _Result(
            components=[
                _Comp(id="TP1", label="test_point", marking="UART TX"),
                _Comp(id="U1", label="ic", marking="STM32 mcu"),
            ],
            traces=[_Trace(from_component="TP1", to_component="U1")],
        )
        paths = rank_attack_paths(result)
        assert len(paths) >= 1
        assert paths[0].entry_point == "TP1"


class TestFormatAttackPaths:
    def test_empty_paths(self):
        assert "No exploitable" in format_attack_paths([])

    def test_format_produces_readable_output(self):
        paths = [
            AttackPath(
                edges=[AttackEdge("J1", "U1", "JTAG", 1.0, "JTAG bus")],
                total_score=0.8,
                entry_point="J1",
                target="U1",
                description="J1 → U1 via JTAG",
            )
        ]
        output = format_attack_paths(paths)
        assert "#1" in output
        assert "0.800" in output
        assert "JTAG" in output
        assert "J1" in output

    def test_format_multiple_paths(self):
        paths = [
            AttackPath(
                edges=[AttackEdge("J1", "U1", "JTAG", 1.0, "JTAG bus")],
                total_score=0.9,
                entry_point="J1",
                target="U1",
                description="J1 → U1",
            ),
            AttackPath(
                edges=[AttackEdge("J2", "U2", "UART", 0.8, "UART bus")],
                total_score=0.6,
                entry_point="J2",
                target="U2",
                description="J2 → U2",
            ),
        ]
        output = format_attack_paths(paths)
        assert "#1" in output
        assert "#2" in output
