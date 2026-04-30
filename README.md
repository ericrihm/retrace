<div align="center">

# re:trace

**AI-powered PCB reverse engineering toolkit**

*The FCC won't let me be, so let me see what's on this PCB.*

[![PyPI](https://img.shields.io/pypi/v/retrace-pcb?color=blue)](https://pypi.org/project/retrace-pcb/)
[![Tests](https://img.shields.io/github/actions/workflow/status/ericrihm/retrace/ci.yml?label=tests)](https://github.com/ericrihm/retrace/actions)
[![Coverage](https://img.shields.io/codecov/c/github/ericrihm/retrace)](https://codecov.io/gh/ericrihm/retrace)
[![Python](https://img.shields.io/pypi/pyversions/retrace-pcb)](https://pypi.org/project/retrace-pcb/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

<sub>
NumPy | OpenCV | YOLO v8 | EasyOCR | Gradio | pytest
</sub>

</div>

---

Feed it a PCB photo. Get back identified components, traced connections, a bill of materials, and a circuit diagram. No microscope. No schematic. No prior knowledge of the board required.

## Why re:trace?

| Feature | pcbre | KiCad Import | OpenBoardView | **re:trace** |
|---|---|---|---|---|
| Auto-detect components from photo | - | - | - | **Yes** |
| OCR chip markings to datasheet | - | - | - | **Yes** |
| Copper trace extraction | Manual | N/A | Manual | **AI-assisted** |
| BOM generation from photo | - | Schematic only | - | **Yes** |
| FCC filing image search | - | - | - | **Built-in** |
| Self-improving detection | - | - | - | **Federated learning** |
| Bayesian probe advisor | - | - | - | **Yes** |
| CLI + Web UI | - | GUI only | GUI only | **Both** |

## Quick Start

```bash
pip install retrace-pcb

# Detect components in a board photo
retrace scan board_photo.jpg

# Generate a bill of materials
retrace scan board_photo.jpg --bom

# Search FCC filings + iFixit for a product
retrace search "ubiquiti unifi ap"

# Extract copper traces as SVG
retrace trace board_photo.jpg --output traces.svg

# Where should I probe next? (Bayesian information gain)
retrace advise board_photo.jpg

# Launch web UI
retrace ui
```

## What It Does

### Component Detection

YOLO v8 model fine-tuned on 12,000+ public PCB images from the FPIC-Component dataset. Detects ICs, capacitors, resistors, connectors, inductors, crystals, test points, and debug headers.

Falls back to OpenCV contour-based detection when YOLO is not installed, so the tool works with zero ML dependencies.

### OCR + Datasheet Lookup

EasyOCR extracts chip markings from detected IC bounding boxes. Fuzzy matching against a local component database (1,200+ common parts) resolves markings to part numbers with datasheet links.

### Copper Trace Extraction

OpenCV pipeline: HSV/LAB color segmentation isolates copper layers, Zhang-Suen skeletonization extracts trace centerlines, BFS graph traversal maps connectivity between pads and vias.

### Bayesian Probe Advisor

Given partial board knowledge, recommends where to place your multimeter probes next for **maximum information gain**. Uses Shannon entropy over the space of possible pin assignments. Converges on unknown pin functions in 6-10 measurements.

This feature has no equivalent in any other public PCB RE tool.

### Constraint Solver

When trace extraction is partial (it always is on real boards), the solver uses:
- Known component pinouts (e.g., STM32 VDD must connect to power)
- PCB design rules (decoupling caps near IC power pins)
- Electrical constraints (no shorts between power rails)

Arc-consistency propagation infers missing connections from what's already known.

### FCC Filing Pipeline

Every electronic device sold in the US has an FCC filing with **internal board photos** (public domain). re:trace searches and downloads these automatically:

```bash
retrace search "nintendo switch"
#   FCC: BKEHAC001 — Game Console
#   iFixit #113044: Nintendo Switch Teardown
#   Found 10 results
```

### Self-Improving Detection

Each board processed (with opt-in consent) contributes anonymized bounding box data back to the community training pipeline. The model improves with every user.

## Architecture

```
retrace/
  cli.py                    Click CLI (scan, search, trace, advise, ui)
  web.py                    Gradio web interface
  core/
    pipeline.py             Orchestrator: photo -> analysis result
    config.py               TOML config + model/cache paths
  detection/
    detector.py             YOLO v8 component detection
    trace_extractor.py      OpenCV copper trace pipeline
    ocr.py                  EasyOCR chip marking reader
  identification/
    matcher.py              Fuzzy part number matching + datasheet lookup
  analysis/
    probe_advisor.py        Bayesian optimal probe point selection
    constraint_solver.py    Arc-consistency connection inference
    cross_board.py          Cross-board pattern recognition engine
  sources/
    fcc.py                  FCC ECFS filing scraper
    ifixit.py               iFixit API v2.0 client
    board_sourcer.py        Unified image acquisition
  learning/
    engine.py               Cross-board knowledge flywheel
  plugins/
    base.py                 Plugin protocol (entry-point based discovery)
    builtin/
      debug_interfaces.py   JTAG/UART/SWD/SPI header detection
  export/
    bom.py                  BOM generator (JSON, CSV)
    svg.py                  SVG annotated image output
```

## For Security Researchers

re:trace is designed for hardware security assessments:

- **Debug interface detection**: Automatically flags JTAG headers, UART pads, SWD connectors, and test points
- **Attack surface mapping**: Identifies microcontrollers, flash/EEPROM, crypto chips, and communication interfaces
- **Probe optimization**: The Bayesian advisor tells you exactly where to measure to identify unknown pins fastest
- **FCC filing intel**: Search any product's FCC filing for internal board photos before you even open the case

## Plugin System

```python
from retrace.plugins.base import AnalyzerPlugin

class MyAnalyzer(AnalyzerPlugin):
    name = "my-analyzer"

    def analyze(self, components, traces):
        # Your custom analysis logic
        return {"findings": [...]}
```

Plugins are discovered via Python entry points:

```toml
[project.entry-points."retrace.analyzers"]
my_analyzer = "my_package:MyAnalyzer"
```

## Development

```bash
git clone https://github.com/ericrihm/retrace.git
cd retrace
pip install -e ".[dev]"
pytest                      # Run test suite
retrace --help              # CLI reference
```

## Legal

- **FCC internal photos** are public domain under 47 CFR 0.457
- **iFixit images** used under CC BY-NC-SA 3.0
- **No firmware files** or exploit code included or referenced
- **Component datasheets** linked via URL, never redistributed
- **Detection models** trained exclusively on public datasets (FPIC-Component, CC-licensed images)

## License

MIT

## Author

Built by [Eric Rihm](https://github.com/ericrihm). Hardware security researcher and builder of things that stare at circuit boards.
