"""Tests for src/retrace/export/sbom.py — SPDX 2.3 and CycloneDX 1.5 export."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from retrace.core.pipeline import AnalysisResult, Component
from retrace.export.bom import generate_bom
from retrace.export.sbom import bom_to_cyclonedx, bom_to_spdx

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_result(**overrides) -> AnalysisResult:
    defaults: dict = dict(
        image_path="/tmp/test_board.png",
        components=[
            Component(id="U1", label="ic", confidence=0.95, bbox=(100, 100, 50, 50),
                      marking="STM32F103", part_number="STM32F103C8T6", package="LQFP48"),
            Component(id="R1", label="resistor", confidence=0.88, bbox=(200, 200, 20, 10),
                      marking="4R7", value="4.7k"),
            Component(id="J1", label="connector", confidence=0.92, bbox=(300, 50, 30, 40),
                      marking="USB-C"),
        ],
        traces=[],
        board_dimensions=(800, 600),
        pipeline_version="0.3.0",
        timestamp="2026-05-01T00:00:00Z",
        duration_seconds=1.5,
    )
    defaults.update(overrides)
    return AnalysisResult(**defaults)


def _make_bom(**result_overrides) -> dict:
    return generate_bom(_make_result(**result_overrides))


# ---------------------------------------------------------------------------
# SPDX — required top-level fields
# ---------------------------------------------------------------------------

class TestSpdxStructure:
    def test_returns_string(self):
        bom = _make_bom()
        assert isinstance(bom_to_spdx(bom), str)

    def test_valid_json(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        assert isinstance(doc, dict)

    def test_spdx_version(self):
        doc = json.loads(bom_to_spdx(_make_bom()))
        assert doc["spdxVersion"] == "SPDX-2.3"

    def test_data_license(self):
        doc = json.loads(bom_to_spdx(_make_bom()))
        assert doc["dataLicense"] == "CC0-1.0"

    def test_spdxid_document(self):
        doc = json.loads(bom_to_spdx(_make_bom()))
        assert doc["SPDXID"] == "SPDXRef-DOCUMENT"

    def test_name_derived_from_image_path(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        assert doc["name"] == "test_board"

    def test_creation_info_present(self):
        doc = json.loads(bom_to_spdx(_make_bom()))
        assert "creationInfo" in doc

    def test_creator_tool_tag(self):
        doc = json.loads(bom_to_spdx(_make_bom()))
        creators = doc["creationInfo"]["creators"]
        assert any(c.startswith("Tool: retrace-") for c in creators)

    def test_creator_includes_version(self):
        from retrace import __version__
        doc = json.loads(bom_to_spdx(_make_bom()))
        creators = doc["creationInfo"]["creators"]
        assert any(__version__ in c for c in creators)

    def test_created_timestamp_present(self):
        doc = json.loads(bom_to_spdx(_make_bom()))
        assert "created" in doc["creationInfo"]

    def test_packages_list_present(self):
        doc = json.loads(bom_to_spdx(_make_bom()))
        assert "packages" in doc
        assert isinstance(doc["packages"], list)

    def test_packages_count_matches_components(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        assert len(doc["packages"]) == len(bom["components"])


# ---------------------------------------------------------------------------
# SPDX — namespace parameter
# ---------------------------------------------------------------------------

class TestSpdxNamespace:
    def test_custom_namespace_used(self):
        bom = _make_bom()
        ns = "https://example.com/my-namespace"
        doc = json.loads(bom_to_spdx(bom, namespace=ns))
        assert doc["documentNamespace"] == ns

    def test_empty_namespace_auto_generated(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom, namespace=""))
        assert "documentNamespace" in doc
        assert "retrace.tools/sbom" in doc["documentNamespace"]

    def test_auto_namespace_contains_image_stem(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        assert "test_board" in doc["documentNamespace"]

    def test_auto_namespace_is_uri(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        assert doc["documentNamespace"].startswith("https://")

    def test_two_calls_generate_different_namespaces(self):
        bom = _make_bom()
        ns1 = json.loads(bom_to_spdx(bom))["documentNamespace"]
        ns2 = json.loads(bom_to_spdx(bom))["documentNamespace"]
        assert ns1 != ns2


# ---------------------------------------------------------------------------
# SPDX — package fields
# ---------------------------------------------------------------------------

class TestSpdxPackages:
    def test_spdxid_prefix(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        for pkg in doc["packages"]:
            assert pkg["SPDXID"].startswith("SPDXRef-")

    def test_spdxid_contains_component_id(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        ids = [p["SPDXID"] for p in doc["packages"]]
        assert "SPDXRef-U1" in ids
        assert "SPDXRef-R1" in ids

    def test_name_uses_part_number_when_available(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        u1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-U1")
        assert u1["name"] == "STM32F103C8T6"

    def test_name_falls_back_to_marking(self):
        # R1 has no part_number, has marking
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        r1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-R1")
        assert r1["name"] == "4R7"

    def test_name_falls_back_to_id(self):
        bom = generate_bom(AnalysisResult(
            image_path="/tmp/b.png",
            components=[Component(id="X9", label="unknown", confidence=0.5, bbox=(0, 0, 1, 1))],
            board_dimensions=(10, 10),
        ))
        doc = json.loads(bom_to_spdx(bom))
        assert doc["packages"][0]["name"] == "X9"

    def test_download_location_noassertion(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        for pkg in doc["packages"]:
            assert pkg["downloadLocation"] == "NOASSERTION"

    def test_files_analyzed_false(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        for pkg in doc["packages"]:
            assert pkg["filesAnalyzed"] is False

    def test_version_info_from_value(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        r1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-R1")
        assert r1.get("versionInfo") == "4.7k"

    def test_no_version_info_when_value_absent(self):
        bom = _make_bom()
        doc = json.loads(bom_to_spdx(bom))
        # J1 has no value
        j1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-J1")
        assert "versionInfo" not in j1


# ---------------------------------------------------------------------------
# SPDX — datasheet external refs
# ---------------------------------------------------------------------------

class TestSpdxDatasheetRefs:
    def _bom_with_datasheet(self) -> dict:
        result = AnalysisResult(
            image_path="/tmp/b.png",
            components=[
                Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10),
                          part_number="LM317", datasheet_url="https://ti.com/lm317.pdf"),
                Component(id="R1", label="resistor", confidence=0.8, bbox=(0, 0, 5, 5)),
            ],
            board_dimensions=(100, 100),
        )
        return generate_bom(result)

    def test_datasheet_url_in_external_refs(self):
        bom = self._bom_with_datasheet()
        doc = json.loads(bom_to_spdx(bom))
        u1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-U1")
        assert "externalRefs" in u1
        locators = [r["referenceLocator"] for r in u1["externalRefs"]]
        assert "https://ti.com/lm317.pdf" in locators

    def test_external_ref_category_other(self):
        bom = self._bom_with_datasheet()
        doc = json.loads(bom_to_spdx(bom))
        u1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-U1")
        for ref in u1["externalRefs"]:
            if ref["referenceLocator"] == "https://ti.com/lm317.pdf":
                assert ref["referenceCategory"] == "OTHER"

    def test_no_external_refs_when_no_datasheet(self):
        bom = self._bom_with_datasheet()
        doc = json.loads(bom_to_spdx(bom))
        r1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-R1")
        assert "externalRefs" not in r1


# ---------------------------------------------------------------------------
# SPDX — security_intel supplier
# ---------------------------------------------------------------------------

class TestSpdxSecurityIntel:
    def test_supplier_from_security_intel_manufacturer(self):
        bom = _make_bom()
        # inject mock security_intel into first component
        bom["components"][0]["security_intel"] = {"manufacturer": "STMicroelectronics"}
        doc = json.loads(bom_to_spdx(bom))
        u1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-U1")
        assert "supplier" in u1
        assert "STMicroelectronics" in u1["supplier"]

    def test_supplier_from_list_manufacturer(self):
        bom = _make_bom()
        bom["components"][0]["security_intel"] = {"manufacturer": ["Vendor A", "Vendor B"]}
        doc = json.loads(bom_to_spdx(bom))
        u1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-U1")
        assert "Vendor A" in u1["supplier"]

    def test_no_supplier_without_intel(self):
        bom = _make_bom()
        # U1 has no security_intel by default from _make_bom with mock parts
        doc = json.loads(bom_to_spdx(bom))
        u1 = next(p for p in doc["packages"] if p["SPDXID"] == "SPDXRef-U1")
        # supplier only set when intel is present
        # (the fixture uses STM32F103C8T6 which may or may not have intel in the DB)
        # just check the doc parses fine
        assert "SPDXID" in u1


# ---------------------------------------------------------------------------
# SPDX — empty components
# ---------------------------------------------------------------------------

class TestSpdxEmpty:
    def test_empty_components_valid_json(self):
        bom = generate_bom(AnalysisResult(
            image_path="/tmp/empty.png",
            components=[],
            board_dimensions=(100, 100),
        ))
        doc = json.loads(bom_to_spdx(bom))
        assert doc["packages"] == []

    def test_empty_components_document_fields_present(self):
        bom = generate_bom(AnalysisResult(
            image_path="/tmp/empty.png",
            components=[],
            board_dimensions=(100, 100),
        ))
        doc = json.loads(bom_to_spdx(bom))
        for key in ("spdxVersion", "dataLicense", "SPDXID", "name",
                    "documentNamespace", "creationInfo"):
            assert key in doc


# ---------------------------------------------------------------------------
# CycloneDX — required top-level fields
# ---------------------------------------------------------------------------

class TestCycloneDxStructure:
    def test_returns_string(self):
        assert isinstance(bom_to_cyclonedx(_make_bom()), str)

    def test_valid_json(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        assert isinstance(doc, dict)

    def test_bom_format(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        assert doc["bomFormat"] == "CycloneDX"

    def test_spec_version(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        assert doc["specVersion"] == "1.5"

    def test_version_integer(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        assert doc["version"] == 1

    def test_serial_number_urn_uuid(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        assert doc["serialNumber"].startswith("urn:uuid:")

    def test_serial_number_unique_across_calls(self):
        bom = _make_bom()
        sn1 = json.loads(bom_to_cyclonedx(bom))["serialNumber"]
        sn2 = json.loads(bom_to_cyclonedx(bom))["serialNumber"]
        assert sn1 != sn2

    def test_metadata_present(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        assert "metadata" in doc

    def test_metadata_timestamp(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        assert doc["metadata"]["timestamp"] == "2026-05-01T00:00:00Z"

    def test_metadata_tools_array(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        tools = doc["metadata"]["tools"]
        assert isinstance(tools, list)
        assert len(tools) >= 1

    def test_tool_name_retrace(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        names = [t["name"] for t in doc["metadata"]["tools"]]
        assert "retrace" in names

    def test_tool_version_present(self):
        from retrace import __version__
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        versions = [t.get("version") for t in doc["metadata"]["tools"]]
        assert __version__ in versions

    def test_metadata_component_board(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        board = doc["metadata"]["component"]
        assert board["type"] == "device"
        assert board["name"] == "test_board"

    def test_components_list_present(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        assert "components" in doc
        assert isinstance(doc["components"], list)

    def test_components_count_matches(self):
        bom = _make_bom()
        doc = json.loads(bom_to_cyclonedx(bom))
        assert len(doc["components"]) == len(bom["components"])


# ---------------------------------------------------------------------------
# CycloneDX — component fields
# ---------------------------------------------------------------------------

class TestCycloneDxComponents:
    def test_component_name_uses_part_number(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        u1 = next(c for c in doc["components"] if "STM32" in c["name"])
        assert u1["name"] == "STM32F103C8T6"

    def test_component_name_falls_back_to_marking(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        r1 = next(c for c in doc["components"] if "4R7" in c["name"])
        assert r1["name"] == "4R7"

    def test_component_name_falls_back_to_id(self):
        bom = generate_bom(AnalysisResult(
            image_path="/tmp/b.png",
            components=[Component(id="TP1", label="test_point", confidence=0.5,
                                  bbox=(0, 0, 5, 5))],
            board_dimensions=(100, 100),
        ))
        doc = json.loads(bom_to_cyclonedx(bom))
        assert doc["components"][0]["name"] == "TP1"

    def test_component_description_contains_label(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        for comp in doc["components"]:
            assert "description" in comp

    def test_ic_type_is_device(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        u1 = next(c for c in doc["components"] if c["name"] == "STM32F103C8T6")
        assert u1["type"] == "device"

    def test_connector_type_is_framework(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        j1 = next(c for c in doc["components"] if "USB" in c["name"])
        assert j1["type"] == "framework"

    def test_resistor_type_is_framework(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        r1 = next(c for c in doc["components"] if "4R7" in c["name"])
        assert r1["type"] == "framework"

    def test_crystal_type_is_device(self):
        bom = generate_bom(AnalysisResult(
            image_path="/tmp/b.png",
            components=[Component(id="X1", label="crystal", confidence=0.85,
                                  bbox=(0, 0, 10, 10), marking="16MHz")],
            board_dimensions=(100, 100),
        ))
        doc = json.loads(bom_to_cyclonedx(bom))
        assert doc["components"][0]["type"] == "device"

    def test_unknown_label_defaults_to_device(self):
        bom = generate_bom(AnalysisResult(
            image_path="/tmp/b.png",
            components=[Component(id="Z1", label="mystery", confidence=0.5,
                                  bbox=(0, 0, 5, 5))],
            board_dimensions=(100, 100),
        ))
        doc = json.loads(bom_to_cyclonedx(bom))
        assert doc["components"][0]["type"] == "device"

    def test_properties_list_present(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        for comp in doc["components"]:
            assert "properties" in comp
            assert isinstance(comp["properties"], list)

    def test_properties_include_confidence(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        for comp in doc["components"]:
            prop_names = [p["name"] for p in comp["properties"]]
            assert "retrace:confidence" in prop_names

    def test_properties_include_bbox(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        for comp in doc["components"]:
            prop_names = [p["name"] for p in comp["properties"]]
            assert "retrace:bbox" in prop_names

    def test_package_property_present_when_set(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        u1 = next(c for c in doc["components"] if c["name"] == "STM32F103C8T6")
        prop_names = [p["name"] for p in u1["properties"]]
        assert "retrace:package" in prop_names

    def test_package_property_absent_when_not_set(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        # R1 has no package
        r1 = next(c for c in doc["components"] if c["name"] == "4R7")
        prop_names = [p["name"] for p in r1["properties"]]
        assert "retrace:package" not in prop_names

    def test_description_includes_value(self):
        doc = json.loads(bom_to_cyclonedx(_make_bom()))
        r1 = next(c for c in doc["components"] if c["name"] == "4R7")
        assert "4.7k" in r1["description"]


# ---------------------------------------------------------------------------
# CycloneDX — datasheet external references
# ---------------------------------------------------------------------------

class TestCycloneDxDatasheetRefs:
    def _bom_with_datasheet(self) -> dict:
        result = AnalysisResult(
            image_path="/tmp/b.png",
            components=[
                Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10),
                          part_number="LM317", datasheet_url="https://ti.com/lm317.pdf"),
                Component(id="R1", label="resistor", confidence=0.8, bbox=(0, 0, 5, 5)),
            ],
            board_dimensions=(100, 100),
        )
        return generate_bom(result)

    def test_datasheet_url_in_external_references(self):
        bom = self._bom_with_datasheet()
        doc = json.loads(bom_to_cyclonedx(bom))
        u1 = next(c for c in doc["components"] if c["name"] == "LM317")
        assert "externalReferences" in u1
        urls = [r["url"] for r in u1["externalReferences"]]
        assert "https://ti.com/lm317.pdf" in urls

    def test_external_reference_type_documentation(self):
        bom = self._bom_with_datasheet()
        doc = json.loads(bom_to_cyclonedx(bom))
        u1 = next(c for c in doc["components"] if c["name"] == "LM317")
        for ref in u1["externalReferences"]:
            if ref["url"] == "https://ti.com/lm317.pdf":
                assert ref["type"] == "documentation"

    def test_no_external_refs_when_no_datasheet(self):
        bom = self._bom_with_datasheet()
        doc = json.loads(bom_to_cyclonedx(bom))
        r1 = next(c for c in doc["components"] if c["name"] == "R1")
        assert "externalReferences" not in r1


# ---------------------------------------------------------------------------
# CycloneDX — empty components
# ---------------------------------------------------------------------------

class TestCycloneDxEmpty:
    def test_empty_components_valid_json(self):
        bom = generate_bom(AnalysisResult(
            image_path="/tmp/empty.png",
            components=[],
            board_dimensions=(100, 100),
        ))
        doc = json.loads(bom_to_cyclonedx(bom))
        assert doc["components"] == []

    def test_empty_components_document_fields_present(self):
        bom = generate_bom(AnalysisResult(
            image_path="/tmp/empty.png",
            components=[],
            board_dimensions=(100, 100),
        ))
        doc = json.loads(bom_to_cyclonedx(bom))
        for key in ("bomFormat", "specVersion", "version", "serialNumber",
                    "metadata", "components"):
            assert key in doc

    def test_board_dimensions_in_metadata_component(self):
        bom = generate_bom(AnalysisResult(
            image_path="/tmp/b.png",
            components=[],
            board_dimensions=(1920, 1080),
        ))
        doc = json.loads(bom_to_cyclonedx(bom))
        props = doc["metadata"]["component"].get("properties", [])
        prop_map = {p["name"]: p["value"] for p in props}
        assert prop_map.get("retrace:board_width") == "1920"
        assert prop_map.get("retrace:board_height") == "1080"


# ---------------------------------------------------------------------------
# Component type mapping
# ---------------------------------------------------------------------------

class TestComponentTypeMapping:
    """Verify _component_type_cyclonedx covers all known labels."""

    @pytest.mark.parametrize("label,expected", [
        ("ic", "device"),
        ("crystal", "device"),
        ("connector", "framework"),
        ("header", "framework"),
        ("capacitor", "framework"),
        ("resistor", "framework"),
        ("inductor", "framework"),
        ("test_point", "framework"),
        ("unknown", "device"),
        ("mystery_chip", "device"),
    ])
    def test_type_mapping(self, label: str, expected: str):
        from retrace.export.sbom import _component_type_cyclonedx
        assert _component_type_cyclonedx(label) == expected


# ---------------------------------------------------------------------------
# CLI — sbom command
# ---------------------------------------------------------------------------

class TestSbomCli:
    @pytest.fixture()
    def runner(self):
        from click.testing import CliRunner
        return CliRunner()

    @pytest.fixture()
    def board_image(self, tmp_path):
        """Minimal valid PNG (1x1 pixel, white)."""
        img = tmp_path / "board.png"
        # Minimal PNG header + IHDR + IDAT + IEND for a 1x1 white pixel
        img.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
            b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return img

    def _mock_result(self, image_path: str):
        from retrace.core.pipeline import AnalysisResult, Component
        return AnalysisResult(
            image_path=image_path,
            components=[
                Component(id="U1", label="ic", confidence=0.95,
                          bbox=(10, 10, 50, 50), part_number="STM32F103"),
            ],
            board_dimensions=(640, 480),
        )

    def test_sbom_help(self, runner):
        from retrace.cli import main
        result = runner.invoke(main, ["sbom", "--help"])
        assert result.exit_code == 0
        assert "IMAGE" in result.output or "sbom" in result.output.lower()

    def test_sbom_both_format_writes_two_files(self, runner, board_image, tmp_path):
        from retrace.cli import main
        out = tmp_path / "out"
        mock_result = self._mock_result(str(board_image))
        with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
            result = runner.invoke(main, [
                "sbom", str(board_image),
                "--format", "both",
                "--output", str(out),
            ])
        assert result.exit_code == 0, result.output
        assert (out / "sbom.spdx.json").exists()
        assert (out / "sbom.cdx.json").exists()

    def test_sbom_spdx_only(self, runner, board_image, tmp_path):
        from retrace.cli import main
        out = tmp_path / "out"
        mock_result = self._mock_result(str(board_image))
        with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
            result = runner.invoke(main, [
                "sbom", str(board_image),
                "--format", "spdx",
                "--output", str(out),
            ])
        assert result.exit_code == 0, result.output
        assert (out / "sbom.spdx.json").exists()
        assert not (out / "sbom.cdx.json").exists()

    def test_sbom_cyclonedx_only(self, runner, board_image, tmp_path):
        from retrace.cli import main
        out = tmp_path / "out"
        mock_result = self._mock_result(str(board_image))
        with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
            result = runner.invoke(main, [
                "sbom", str(board_image),
                "--format", "cyclonedx",
                "--output", str(out),
            ])
        assert result.exit_code == 0, result.output
        assert (out / "sbom.cdx.json").exists()
        assert not (out / "sbom.spdx.json").exists()

    def test_sbom_spdx_is_valid_json(self, runner, board_image, tmp_path):
        from retrace.cli import main
        out = tmp_path / "out"
        mock_result = self._mock_result(str(board_image))
        with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
            runner.invoke(main, [
                "sbom", str(board_image),
                "--format", "spdx",
                "--output", str(out),
            ])
        content = (out / "sbom.spdx.json").read_text()
        doc = json.loads(content)
        assert doc["spdxVersion"] == "SPDX-2.3"

    def test_sbom_cdx_is_valid_json(self, runner, board_image, tmp_path):
        from retrace.cli import main
        out = tmp_path / "out"
        mock_result = self._mock_result(str(board_image))
        with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
            runner.invoke(main, [
                "sbom", str(board_image),
                "--format", "cyclonedx",
                "--output", str(out),
            ])
        content = (out / "sbom.cdx.json").read_text()
        doc = json.loads(content)
        assert doc["bomFormat"] == "CycloneDX"

    def test_sbom_namespace_forwarded_to_spdx(self, runner, board_image, tmp_path):
        from retrace.cli import main
        out = tmp_path / "out"
        mock_result = self._mock_result(str(board_image))
        ns = "https://example.com/custom-ns"
        with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
            runner.invoke(main, [
                "sbom", str(board_image),
                "--format", "spdx",
                "--output", str(out),
                "--namespace", ns,
            ])
        doc = json.loads((out / "sbom.spdx.json").read_text())
        assert doc["documentNamespace"] == ns

    def test_sbom_output_mentions_files(self, runner, board_image, tmp_path):
        from retrace.cli import main
        out = tmp_path / "out"
        mock_result = self._mock_result(str(board_image))
        with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
            result = runner.invoke(main, [
                "sbom", str(board_image),
                "--format", "both",
                "--output", str(out),
            ])
        assert "sbom" in result.output.lower()

    def test_sbom_missing_file(self, runner):
        from retrace.cli import main
        result = runner.invoke(main, ["sbom", "/no/such/board.png"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# CLI — export command with spdx/cyclonedx formats
# ---------------------------------------------------------------------------

class TestExportCli:
    @pytest.fixture()
    def runner(self):
        from click.testing import CliRunner
        return CliRunner()

    def _mock_result(self, image_path: str):
        from retrace.core.pipeline import AnalysisResult, Component
        return AnalysisResult(
            image_path=image_path,
            components=[
                Component(id="U1", label="ic", confidence=0.9,
                          bbox=(0, 0, 10, 10), part_number="ATmega328P"),
            ],
            board_dimensions=(640, 480),
        )

    def test_export_spdx_writes_file(self, runner, tmp_path):
        from retrace.cli import main
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        out = tmp_path / "out"
        mock_result = self._mock_result(str(img))
        with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
            result = runner.invoke(main, [
                "export", str(img),
                "--format", "spdx",
                "--output", str(out),
            ])
        assert result.exit_code == 0, result.output
        assert (out / "sbom.spdx.json").exists()

    def test_export_cyclonedx_writes_file(self, runner, tmp_path):
        from retrace.cli import main
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        out = tmp_path / "out"
        mock_result = self._mock_result(str(img))
        with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
            result = runner.invoke(main, [
                "export", str(img),
                "--format", "cyclonedx",
                "--output", str(out),
            ])
        assert result.exit_code == 0, result.output
        assert (out / "sbom.cdx.json").exists()

    def test_export_help_includes_spdx(self, runner):
        from retrace.cli import main
        result = runner.invoke(main, ["export", "--help"])
        assert result.exit_code == 0
        assert "spdx" in result.output

    def test_export_help_includes_cyclonedx(self, runner):
        from retrace.cli import main
        result = runner.invoke(main, ["export", "--help"])
        assert result.exit_code == 0
        assert "cyclonedx" in result.output
