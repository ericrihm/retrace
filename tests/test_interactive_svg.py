"""Tests for interactive layered SVG (Google Maps-style layer toggles)."""

from __future__ import annotations

from pathlib import Path

import pytest

from retrace.core.pipeline import AnalysisResult, Component, Trace
from retrace.export.svg import (
    generate_interactive_svg,
    save_interactive_svg,
    _render_interactive_controls,
    _render_interactive_script,
    _render_grid_reference,
    _render_net_labels,
    _LAYER_DEFS,
    _PRESET_DEFS,
)


def _make_result(**kwargs) -> AnalysisResult:
    defaults = dict(
        image_path="/tmp/test_board.jpg",
        components=[
            Component(id="U1", label="ic", confidence=0.95,
                      bbox=(100, 100, 80, 80), marking="STM32F407"),
            Component(id="J5", label="header", confidence=0.9,
                      bbox=(200, 150, 60, 140), marking="JTAG"),
            Component(id="R1", label="resistor", confidence=0.85,
                      bbox=(300, 200, 20, 10), marking="10K"),
            Component(id="C1", label="capacitor", confidence=0.88,
                      bbox=(350, 250, 15, 8), marking="100nF"),
        ],
        traces=[
            Trace(id="T1", points=[(140, 140), (230, 220)],
                  from_component="U1", to_component="J5", width_px=2.0),
            Trace(id="T2", points=[(310, 205), (357, 254)],
                  from_component="R1", to_component="C1", width_px=1.5),
        ],
        board_dimensions=(800, 600),
    )
    defaults.update(kwargs)
    return AnalysisResult(**defaults)


class TestLayerDefinitions:
    def test_all_layers_have_ids(self):
        for layer_id, label, default_on in _LAYER_DEFS:
            assert layer_id
            assert label
            assert isinstance(default_on, bool)

    def test_preset_layers_reference_valid_layer_ids(self):
        valid_ids = {ld[0] for ld in _LAYER_DEFS}
        for preset_id, preset in _PRESET_DEFS.items():
            for layer_id in preset["layers"]:
                assert layer_id in valid_ids, \
                    f"Preset {preset_id!r} references unknown layer {layer_id!r}"

    def test_all_presets_exist(self):
        expected = {"analysis", "attack", "zones", "debug", "clean", "all"}
        assert set(_PRESET_DEFS.keys()) == expected

    def test_analysis_preset_is_default(self):
        default_on = {ld[0] for ld in _LAYER_DEFS if ld[2]}
        analysis_layers = set(_PRESET_DEFS["analysis"]["layers"])
        assert default_on == analysis_layers

    def test_all_preset_includes_everything(self):
        all_ids = {ld[0] for ld in _LAYER_DEFS}
        assert set(_PRESET_DEFS["all"]["layers"]) == all_ids


class TestInteractiveSvg:
    def test_basic_structure(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        assert svg.startswith("<svg")
        assert "</svg>" in svg
        assert "re:trace" in svg

    def test_contains_all_layer_groups(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        for layer_id, _, _ in _LAYER_DEFS:
            assert f'id="layer-{layer_id}"' in svg

    def test_default_visibility(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        for layer_id, _, default_on in _LAYER_DEFS:
            expected = "visible" if default_on else "hidden"
            assert f'id="layer-{layer_id}" visibility="{expected}"' in svg

    def test_contains_javascript(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        assert "<script" in svg
        assert "toggleLayer" in svg
        assert "setPreset" in svg

    def test_contains_preset_buttons(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        for preset_id, preset in _PRESET_DEFS.items():
            assert f'data-preset="{preset_id}"' in svg
            assert preset["label"] in svg

    def test_contains_layer_checkboxes(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        for layer_id, label, _ in _LAYER_DEFS:
            assert f'id="chk-{layer_id}"' in svg
            assert f'id="tick-{layer_id}"' in svg

    def test_components_rendered(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        assert "STM32F407" in svg
        assert "JTAG" in svg
        assert "10K" in svg

    def test_traces_rendered(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        assert 'class="traces"' in svg

    def test_with_zones(self):
        result = _make_result()
        zones = [
            ("CPU Core", "cpu", ["U1"]),
            ("Debug", "debug", ["J5"]),
        ]
        svg = generate_interactive_svg(result, zones=zones)
        assert "CPU CORE" in svg
        assert "DEBUG" in svg

    def test_with_attack_paths(self):
        result = _make_result()
        attack_paths = [("J5", "U1", "JTAG → CPU")]
        security_refs = ["J5", "U1"]
        svg = generate_interactive_svg(
            result, attack_paths=attack_paths, security_refs=security_refs,
        )
        assert "JTAG" in svg
        assert "attack-paths" in svg

    def test_with_security_refs(self):
        result = _make_result()
        svg = generate_interactive_svg(result, security_refs=["J5"])
        assert "security-highlights" in svg

    def test_custom_dimensions(self):
        result = _make_result()
        svg = generate_interactive_svg(result, width=1024, height=768)
        assert 'width="1024"' in svg
        assert 'height="768"' in svg

    def test_custom_title(self):
        result = _make_result()
        svg = generate_interactive_svg(result, title="Cisco ASA 5506-X")
        assert "Cisco ASA 5506-X" in svg

    def test_bom_panel_rendered(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        assert "Bill of Materials" in svg

    def test_footer_rendered(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        assert "components" in svg
        assert "traces" in svg

    def test_grid_reference_in_hidden_layer(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        idx_grid = svg.index('id="layer-grid-ref"')
        assert 'visibility="hidden"' in svg[idx_grid:idx_grid + 100]

    def test_net_labels_in_hidden_layer(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        idx_net = svg.index('id="layer-net-labels"')
        assert 'visibility="hidden"' in svg[idx_net:idx_net + 100]

    def test_no_xss_in_title(self):
        result = _make_result()
        svg = generate_interactive_svg(result, title='<script>alert("xss")</script>')
        assert "<script>alert" not in svg
        assert "&lt;script&gt;" in svg

    def test_empty_result(self):
        result = AnalysisResult(image_path="/tmp/empty.jpg", board_dimensions=(800, 600))
        svg = generate_interactive_svg(result)
        assert "<svg" in svg
        assert "</svg>" in svg
        assert "toggleLayer" in svg


class TestGridReference:
    def test_renders_lines(self):
        grid = _render_grid_reference(800, 600)
        assert "line" in grid

    def test_renders_labels(self):
        grid = _render_grid_reference(800, 600)
        assert "100" in grid or "50" in grid


class TestNetLabels:
    def test_renders_labels_for_traces(self):
        comp_map = {
            "U1": Component(id="U1", label="ic", confidence=0.9,
                            bbox=(100, 100, 80, 80), marking="STM32"),
            "J5": Component(id="J5", label="header", confidence=0.9,
                            bbox=(200, 150, 60, 140), marking="JTAG"),
        }
        traces = [
            Trace(id="T1", points=[(140, 140), (230, 220)],
                  from_component="U1", to_component="J5"),
        ]
        labels = _render_net_labels(traces, comp_map)
        assert labels

    def test_handles_empty_traces(self):
        labels = _render_net_labels([], {})
        assert labels == ""

    def test_handles_traces_without_points(self):
        comp_map = {
            "U1": Component(id="U1", label="ic", confidence=0.9,
                            bbox=(100, 100, 80, 80), marking="VCC"),
            "R1": Component(id="R1", label="resistor", confidence=0.9,
                            bbox=(200, 200, 20, 10), marking="10K"),
        }
        traces = [
            Trace(id="T1", points=[], from_component="U1", to_component="R1"),
        ]
        labels = _render_net_labels(traces, comp_map)
        assert labels


class TestControlPanel:
    def test_renders_preset_buttons(self):
        controls = _render_interactive_controls(800)
        assert "VIEW PRESETS" in controls
        assert "LAYERS" in controls

    def test_renders_all_presets(self):
        controls = _render_interactive_controls(800)
        for preset in _PRESET_DEFS.values():
            assert preset["label"] in controls

    def test_renders_all_layer_toggles(self):
        controls = _render_interactive_controls(800)
        for layer_id, label, _ in _LAYER_DEFS:
            assert f'chk-{layer_id}' in controls
            assert label in controls


class TestScript:
    def test_contains_functions(self):
        script = _render_interactive_script()
        assert "function toggleLayer" in script
        assert "function setPreset" in script

    def test_contains_presets(self):
        script = _render_interactive_script()
        for preset_id in _PRESET_DEFS:
            assert f'"{preset_id}"' in script

    def test_contains_layer_ids(self):
        script = _render_interactive_script()
        for layer_id, _, _ in _LAYER_DEFS:
            assert f'"{layer_id}"' in script


class TestSaveToDisk:
    def test_save_creates_file(self, tmp_path):
        result = _make_result()
        out = tmp_path / "interactive.svg"
        save_interactive_svg(result, str(out))
        assert out.exists()
        content = out.read_text()
        assert "<svg" in content
        assert "toggleLayer" in content

    def test_save_with_all_features(self, tmp_path):
        result = _make_result()
        zones = [("CPU", "cpu", ["U1"])]
        attack_paths = [("J5", "U1", "JTAG")]
        out = tmp_path / "full.svg"
        save_interactive_svg(
            result, str(out),
            zones=zones, attack_paths=attack_paths,
            security_refs=["J5"],
        )
        assert out.exists()
        content = out.read_text()
        assert "CPU" in content
        assert "JTAG" in content


class TestSvgFormatSave:
    """Test that AnalysisResult.save(fmt='svg') produces interactive SVG."""

    def test_save_svg_format(self, tmp_path):
        result = _make_result()
        result.save(tmp_path, fmt="svg")
        svg_path = tmp_path / "annotated.svg"
        assert svg_path.exists()
        content = svg_path.read_text()
        assert "toggleLayer" in content
        assert "setPreset" in content
