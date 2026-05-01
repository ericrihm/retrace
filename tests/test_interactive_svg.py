"""Tests for interactive layered SVG (Google Maps-style layer toggles)."""

from __future__ import annotations

from retrace.core.pipeline import AnalysisResult, Component, Trace
from retrace.export.svg import (
    _LAYER_DEFS,
    _PRESET_DEFS,
    _render_grid_reference,
    _render_interactive_controls,
    _render_interactive_script,
    _render_net_labels,
    _render_power_rails,
    generate_interactive_svg,
    save_interactive_svg,
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
        expected = {"satellite", "analysis", "schematic", "xray", "attack",
                    "recon", "power", "zones", "debug", "all"}
        assert set(_PRESET_DEFS.keys()) == expected

    def test_analysis_preset_is_default(self):
        default_on = {ld[0] for ld in _LAYER_DEFS if ld[2]}
        analysis_layers = set(_PRESET_DEFS["analysis"]["layers"])
        assert default_on == analysis_layers

    def test_preset_style_modes(self):
        for pid, pdef in _PRESET_DEFS.items():
            assert "style" in pdef, f"Preset {pid!r} missing 'style' key"
            assert pdef["style"] in ("photo", "schematic", "xray"), \
                f"Preset {pid!r} has unknown style {pdef['style']!r}"

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
        assert "function setStyle" in script

    def test_contains_presets(self):
        script = _render_interactive_script()
        for preset_id in _PRESET_DEFS:
            assert f'"{preset_id}"' in script

    def test_contains_layer_ids(self):
        script = _render_interactive_script()
        for layer_id, _, _ in _LAYER_DEFS:
            assert f'"{layer_id}"' in script

    def test_preset_style_in_script(self):
        script = _render_interactive_script()
        assert '"style"' in script or "'style'" in script


class TestStyleModes:
    def test_style_defs_rendered(self):
        from retrace.export.svg import _render_style_defs
        css = _render_style_defs()
        assert ".style-photo" in css
        assert ".style-schematic" in css
        assert ".style-xray" in css

    def test_svg_has_default_style_class(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        assert 'class="style-photo"' in svg

    def test_style_defs_in_output(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        assert ".style-schematic" in svg
        assert ".style-xray" in svg

    def test_schematic_preset_hides_board_image(self):
        preset = _PRESET_DEFS["schematic"]
        assert "board-image" not in preset["layers"]
        assert preset["style"] == "schematic"

    def test_xray_preset_includes_all_overlays(self):
        preset = _PRESET_DEFS["xray"]
        assert "board-image" in preset["layers"]
        assert "components" in preset["layers"]
        assert "traces" in preset["layers"]
        assert preset["style"] == "xray"

    def test_satellite_preset_board_only(self):
        preset = _PRESET_DEFS["satellite"]
        assert preset["layers"] == ["board-image"]


class TestPowerRails:
    def test_power_rails_layer_exists(self):
        result = _make_result()
        svg = generate_interactive_svg(result)
        assert 'id="layer-power-rails"' in svg

    def test_power_components_highlighted(self):
        comps = [
            Component("U10", "ic", 0.9, (100, 100, 60, 40),
                      marking="TPS54331", part_number="TPS54331"),
            Component("L1", "inductor", 0.85, (170, 100, 30, 20),
                      marking="4.7uH"),
            Component("C1", "capacitor", 0.9, (210, 100, 12, 8),
                      value="10uF"),
        ]
        _make_result(components=comps)
        comp_map = {c.id: c for c in comps}
        html = _render_power_rails(comps, [], comp_map)
        assert "U10" not in html or "f59e0b" in html
        assert "f59e0b" in html

    def test_power_preset_includes_layer(self):
        preset = _PRESET_DEFS["power"]
        assert "power-rails" in preset["layers"]


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


# ---------------------------------------------------------------------------
# _render_net_labels missing component paths (lines 1373, 1381)
# ---------------------------------------------------------------------------

class TestNetLabelsMissingComponents:
    def test_trace_no_points_no_components_skipped(self):
        # Trace has no points AND no from/to component -> should be skipped
        traces = [Trace(id="T1", points=[], width_px=1.0)]
        labels = _render_net_labels(traces, {})
        assert labels == ""

    def test_trace_no_points_missing_to_component_skipped(self):
        # has from_component but to_component is missing from comp_map
        comp_map = {
            "U1": Component(id="U1", label="ic", confidence=0.9,
                            bbox=(100, 100, 80, 80)),
        }
        traces = [
            Trace(id="T1", points=[], from_component="U1", to_component="MISSING",
                  width_px=1.0),
        ]
        # to_c will be None -> skipped
        labels = _render_net_labels(traces, comp_map)
        assert labels == ""

    def test_trace_no_points_both_components_missing_skipped(self):
        traces = [
            Trace(id="T1", points=[], from_component="X", to_component="Y",
                  width_px=1.0),
        ]
        labels = _render_net_labels(traces, {})
        assert labels == ""


# ---------------------------------------------------------------------------
# _render_power_rails trace connecting power components (lines 1444-1450)
# ---------------------------------------------------------------------------

class TestPowerRailsTraceLines:
    def test_power_trace_line_rendered(self):
        vrm = Component(id="U10", label="ic", confidence=0.9,
                        bbox=(100, 100, 60, 40), marking="VRM buck")
        cap = Component(id="C1", label="capacitor", confidence=0.9,
                        bbox=(200, 110, 15, 8), value="10uF")
        comp_map = {"U10": vrm, "C1": cap}
        trace = Trace(id="T1", points=[], from_component="U10", to_component="C1",
                      width_px=2.0)
        html = _render_power_rails([vrm, cap], [trace], comp_map)
        # Dashed connecting line between power components should appear
        assert 'stroke-dasharray="6,3"' in html
        assert "f59e0b" in html

    def test_power_trace_skipped_if_one_component_missing(self):
        vrm = Component(id="U10", label="ic", confidence=0.9,
                        bbox=(100, 100, 60, 40), marking="VRM buck")
        comp_map = {"U10": vrm}
        trace = Trace(id="T1", points=[], from_component="U10", to_component="MISSING",
                      width_px=2.0)
        html = _render_power_rails([vrm], [trace], comp_map)
        # VRM highlight rect still present (f59e0b color)
        assert "f59e0b" in html
        # Connecting line (stroke-dasharray="6,3") should NOT appear when to_c is missing
        assert 'stroke-dasharray="6,3"' not in html


# ---------------------------------------------------------------------------
# interactive SVG with local image file (line 1498)
# ---------------------------------------------------------------------------

class TestInteractiveSvgWithLocalImage:
    def test_local_image_embedded_as_data_uri(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        result = _make_result()
        svg = generate_interactive_svg(result, image_href=str(img))
        assert "<image" in svg
        assert "data:image/png;base64," in svg

    def test_nonexistent_local_image_omitted(self):
        result = _make_result()
        svg = generate_interactive_svg(result, image_href="/no/such/file.png")
        assert "/no/such/file.png" not in svg


# ---------------------------------------------------------------------------
# interactive SVG attack path with missing component (line 1550)
# ---------------------------------------------------------------------------

class TestInteractiveSvgAttackPathMissing:
    def test_attack_path_with_missing_to_component_skipped(self):
        result = _make_result()
        # "GHOST" doesn't exist in result.components
        attack_paths = [("U1", "GHOST", "phantom path")]
        svg = generate_interactive_svg(result, attack_paths=attack_paths,
                                       security_refs=["U1"])
        # Should not crash; phantom path label should not appear
        assert "phantom path" not in svg
        assert "<svg" in svg

    def test_attack_path_with_both_missing_skipped(self):
        result = _make_result()
        attack_paths = [("GHOST1", "GHOST2", "double phantom")]
        svg = generate_interactive_svg(result, attack_paths=attack_paths,
                                       security_refs=[])
        assert "double phantom" not in svg
        assert "<svg" in svg
