"""SBOM export — SPDX 2.3 and CycloneDX 1.5 formats from BOM data."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _retrace_version() -> str:
    from retrace import __version__
    return __version__


def _component_type_cyclonedx(label: str) -> str:
    """Map retrace component label to a CycloneDX component type."""
    _MAP = {
        "ic": "device",
        "connector": "framework",
        "header": "framework",
        "capacitor": "framework",
        "resistor": "framework",
        "inductor": "framework",
        "crystal": "device",
        "test_point": "framework",
    }
    return _MAP.get(label, "device")


def _name_for(comp: dict[str, Any]) -> str:
    """Resolve the best display name for a component (part_number > marking > id)."""
    return comp.get("part_number") or comp.get("marking") or comp.get("id") or "unknown"


# ---------------------------------------------------------------------------
# SPDX 2.3
# ---------------------------------------------------------------------------

def bom_to_spdx(bom: dict[str, Any], namespace: str = "") -> str:
    """Generate an SPDX 2.3 JSON document from a BOM dict.

    Args:
        bom: Dict produced by :func:`retrace.export.bom.generate_bom`.
        namespace: SPDX document namespace URI.  If empty, one is generated
            from the image path.

    Returns:
        SPDX 2.3 JSON as a formatted string.
    """
    version = _retrace_version()
    metadata = bom.get("metadata", {})
    components = bom.get("components", [])

    image_path = metadata.get("image_path", "unknown")
    timestamp = metadata.get("timestamp", "")
    stem = Path(image_path).stem

    if not namespace:
        safe_stem = stem.replace(" ", "_")
        namespace = f"https://retrace.tools/sbom/{safe_stem}-{uuid.uuid4()}"

    packages = []
    for comp in components:
        comp_id = comp.get("id", "UNKNOWN")
        name = _name_for(comp)

        pkg: dict[str, Any] = {
            "SPDXID": f"SPDXRef-{comp_id}",
            "name": name,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
        }

        value = comp.get("value") or ""
        if value:
            pkg["versionInfo"] = value

        # Supplier from security_intel if available
        intel = comp.get("security_intel")
        if isinstance(intel, dict):
            mfr = intel.get("manufacturer") or intel.get("vendor")
            if mfr:
                if isinstance(mfr, list):
                    mfr = mfr[0]
                pkg["supplier"] = f"Organization: {mfr}"

        # External reference for datasheet
        datasheet = comp.get("datasheet_url") or ""
        if datasheet:
            pkg["externalRefs"] = [
                {
                    "referenceCategory": "OTHER",
                    "referenceType": "url",
                    "referenceLocator": datasheet,
                    "comment": "Datasheet",
                }
            ]

        packages.append(pkg)

    doc: dict[str, Any] = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": stem,
        "documentNamespace": namespace,
        "creationInfo": {
            "created": timestamp,
            "creators": [f"Tool: retrace-{version}"],
        },
        "packages": packages,
    }

    return json.dumps(doc, indent=2)


# ---------------------------------------------------------------------------
# CycloneDX 1.5
# ---------------------------------------------------------------------------

def bom_to_cyclonedx(bom: dict[str, Any]) -> str:
    """Generate a CycloneDX 1.5 JSON document from a BOM dict.

    Args:
        bom: Dict produced by :func:`retrace.export.bom.generate_bom`.

    Returns:
        CycloneDX 1.5 JSON as a formatted string.
    """
    version = _retrace_version()
    metadata = bom.get("metadata", {})
    components = bom.get("components", [])

    image_path = metadata.get("image_path", "unknown")
    timestamp = metadata.get("timestamp", "")
    stem = Path(image_path).stem
    board_dims = metadata.get("board_dimensions", [])

    # Board-level component (the PCB itself)
    board_component: dict[str, Any] = {
        "type": "device",
        "name": stem,
        "description": "PCB analysed by retrace",
    }
    if board_dims:
        board_component["properties"] = [
            {"name": "retrace:board_width", "value": str(board_dims[0])},
            {"name": "retrace:board_height", "value": str(board_dims[1])},
        ]

    cdx_components: list[dict[str, Any]] = []
    for comp in components:
        label = comp.get("label", "unknown")
        comp_type = _component_type_cyclonedx(label)
        name = _name_for(comp)
        value = comp.get("value") or ""
        description_parts = [label]
        if value:
            description_parts.append(value)
        description = " ".join(description_parts)

        props: list[dict[str, str]] = [
            {"name": "retrace:id", "value": str(comp.get("id", ""))},
            {"name": "retrace:label", "value": label},
            {"name": "retrace:confidence", "value": str(comp.get("confidence", 0.0))},
            {"name": "retrace:bbox", "value": str(comp.get("bbox", []))},
        ]
        pkg = comp.get("package") or ""
        if pkg:
            props.append({"name": "retrace:package", "value": pkg})

        cdx_comp: dict[str, Any] = {
            "type": comp_type,
            "name": name,
            "description": description,
            "properties": props,
        }

        datasheet = comp.get("datasheet_url") or ""
        if datasheet:
            cdx_comp["externalReferences"] = [
                {
                    "type": "documentation",
                    "url": datasheet,
                    "comment": "Datasheet",
                }
            ]

        cdx_components.append(cdx_comp)

    doc: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "metadata": {
            "timestamp": timestamp,
            "tools": [
                {
                    "vendor": "retrace",
                    "name": "retrace",
                    "version": version,
                }
            ],
            "component": board_component,
        },
        "components": cdx_components,
    }

    return json.dumps(doc, indent=2)
