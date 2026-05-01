# Changelog

All notable changes to re:trace are documented here.

## [0.3.0] - 2026-05-01

### Added
- **Firmware triage module** — Shannon entropy profiling, 17 magic byte signatures, credential/key string extraction
- **Fault injection surface detection** — voltage glitch, clock glitch, EMFI proximity analysis plugin
- **Boot mode pin detection** — 9 MCU families, accessible test point matching, CVSS scoring
- **Sigrok/PulseView session export** — pre-labeled channels, protocol decoder configuration
- **Firmware extraction guide** — flashrom commands, SPI wiring diagrams, JEDEC ID verification
- **Pipeline architecture diagram** — SVG visualization of the full analysis flow
- **Technical Depth section** on website — CV, graph algorithms, constraint solving, information theory
- **py.typed marker** for PEP 561 type checking support
- Plugin architecture with setuptools entry-points (3 built-in analyzers)
- GitHub issue templates, PR template, pre-commit configuration

### Changed
- Version bump from 0.1.0 to 0.3.0
- Expanded pyproject.toml classifiers and keywords for security domain
- Development status upgraded from Alpha to Beta

### Fixed
- 22 mypy type errors across 6 modules
- Coverage restored from 98% to 99% (1703 tests)

## [0.2.0] - 2026-04-30

### Added
- **JTAGulator/OpenOCD export** — pin configs and connection snippets
- **KiCad PCB placement export** — .kicad_pcb with component coordinates
- **Attack path ranker** — chip-to-chip exploitability scoring with CVSS 3.1
- **Board diff/compare** — side-by-side PCB comparison with SVG overlay
- **Cross-board pattern analysis** — subcircuit recognition across multiple boards
- **Constraint solver** — pin assignment under electrical rules
- **Bayesian probe advisor** — information-gain-maximizing measurement recommendations
- **Flywheel intelligence layer** — cross-board learning, pattern extraction
- **Prometheus metrics export** — coverage, quality, effectiveness tracking
- Component DB expanded from 143 to 196 entries
- Professional HTML assessment reports with CVSS gauges, risk matrices, MITRE ATT&CK links
- Terminal demo SVG for README

### Fixed
- SVG coordinate precision and font-family consistency
- Unicode glyph compatibility replaced with SVG primitives

## [0.1.0] - 2026-04-28

### Added
- Core pipeline: image loading, component detection (contour + YOLO), trace extraction
- HSV+LAB dual-colorspace copper trace detection
- Component identification via 143-entry database with fuzzy matching
- Debug interface detection (JTAG, SWD, UART, SPI, I2C)
- SVG export: annotated board, pinout diagrams, bus topology, attack surface
- KiCad netlist export (.net format)
- BOM export (JSON, CSV)
- FCC filing and iFixit search integration
- CLI with 15 commands
- Gradio web UI
- 800+ tests, 95% coverage
