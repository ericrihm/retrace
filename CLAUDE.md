# re:trace — AI-Powered PCB Reverse Engineering Toolkit

## Build & Test

```bash
pip install -e ".[dev]"
pytest                    # full suite
retrace --help            # CLI entry point
retrace scan tests/fixtures/sample.jpg  # quick smoke test
```

## Architecture

Python package (`src/retrace/`) with Click CLI. Pipeline-based: ingest -> detect -> OCR -> trace -> identify -> analyze -> export.

### Core Modules

- `cli.py` — Click CLI: scan, search, trace, advise, ui, report
- `core/pipeline.py` — Main orchestrator: loads image, runs all phases, returns AnalysisResult
- `core/config.py` — TOML config, model paths, cache dirs
- `detection/detector.py` — YOLO v8 component detection (graceful fallback to OpenCV contours)
- `detection/trace_extractor.py` — OpenCV copper trace pipeline (HSV/LAB segmentation, skeletonization, BFS)
- `detection/ocr.py` — EasyOCR chip marking extraction
- `identification/matcher.py` — Fuzzy part number matching against local component DB
- `analysis/probe_advisor.py` — Bayesian optimal probe selection via Shannon entropy
- `analysis/constraint_solver.py` — Arc-consistency constraint propagation for missing connections
- `analysis/cross_board.py` — Cross-board pattern recognition and knowledge transfer
- `sources/fcc.py` — FCC filing scraper (fcc.report, public domain)
- `sources/ifixit.py` — iFixit API v2.0 client (CC BY-NC-SA images)
- `learning/engine.py` — Cross-board knowledge flywheel
- `plugins/base.py` — Plugin protocol + entry-point discovery
- `plugins/builtin/debug_interfaces.py` — JTAG/UART/SWD/SPI header detection
- `export/bom.py` — BOM generator (JSON, CSV)
- `export/svg.py` — SVG annotated image output

### Key Data Types

- `Component` — detected component with bbox, label, marking, part_number
- `Trace` — extracted copper trace with point list and connectivity
- `AnalysisResult` — full pipeline output with components, traces, and metadata

## Key Constraints

- Optional ML deps: ultralytics, easyocr, gradio are all optional — core works with just numpy + opencv
- FCC/iFixit requests must include 1s delay between calls
- No firmware files, exploit code, or vulnerability research in this repo
- Models auto-download on first use to ~/.cache/retrace/
- Plugin system uses Python entry points for discovery
