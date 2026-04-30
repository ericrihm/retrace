"""re:trace CLI — the FCC won't let me be, so let me see what's on this PCB."""

import json
import logging
from pathlib import Path

import click

from retrace import __version__


@click.group()
@click.version_option(__version__, prog_name="retrace")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def main(verbose: bool) -> None:
    """re:trace -- AI-powered PCB reverse engineering toolkit."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


@main.command()
@click.argument("image", type=click.Path(exists=True))
@click.option("--bom", is_flag=True, help="Generate bill of materials")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option("--format", "fmt", type=click.Choice(["json", "csv", "svg"]), default="json")
def scan(image: str, bom: bool, output: str, fmt: str) -> None:
    """Scan a PCB photo — detect components, extract traces, identify chips."""
    from retrace.core.pipeline import Pipeline

    pipeline = Pipeline()
    result = pipeline.run(image)

    if output:
        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
        result.save(out_dir, fmt=fmt)
        click.echo(f"Results saved to {out_dir}")
    else:
        click.echo(json.dumps(result.summary(), indent=2))

    if bom:
        from retrace.export.bom import generate_bom
        bom_data = generate_bom(result)
        click.echo(f"\nBOM: {len(bom_data['components'])} components identified")


@main.command()
@click.argument("query")
@click.option("--download", is_flag=True, help="Download found images")
@click.option("--limit", type=int, default=5, help="Max results")
def search(query: str, download: bool, limit: int) -> None:
    """Search FCC filings and iFixit for board images."""
    from retrace.sources.fcc import search_fcc
    from retrace.sources.ifixit import search_ifixit

    click.echo(f"\nSearching for: {query}\n")

    fcc_results = search_fcc(query)
    for r in fcc_results[:limit]:
        click.echo(f"  FCC: {r['fcc_id']} — {r.get('description', '')}")

    ifixit_results = search_ifixit(query)
    for r in ifixit_results[:limit]:
        click.echo(f"  iFixit #{r['guideid']}: {r['title']}")

    total = len(fcc_results) + len(ifixit_results)
    click.echo(f"\n  Found {total} results")

    if download and total > 0:
        from retrace.sources.board_sourcer import download_all
        downloaded = download_all(query, fcc_results[:limit], ifixit_results[:limit])
        click.echo(f"  Downloaded {downloaded} images")


@main.command()
@click.argument("image", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="traces.svg")
def trace(image: str, output: str) -> None:
    """Extract copper traces from a PCB photo."""
    from retrace.detection.trace_extractor import extract_traces

    result = extract_traces(image)
    click.echo(f"Extracted {result['trace_count']} traces, {result['junction_count']} junctions")

    if output:
        result["save"](output)
        click.echo(f"Saved to {output}")


@main.command()
@click.argument("image", type=click.Path(exists=True))
def advise(image: str) -> None:
    """Bayesian probe point advisor — where to measure next."""
    from retrace.analysis.probe_advisor import ProbeAdvisor

    advisor = ProbeAdvisor()
    recommendations = advisor.recommend(image)

    click.echo("\nRecommended probe points (by information gain):\n")
    for i, rec in enumerate(recommendations[:5], 1):
        click.echo(f"  {i}. {rec['location']} — {rec['reason']}")
        click.echo(f"     Expected info gain: {rec['entropy_reduction']:.2f} bits")


@main.command()
def ui() -> None:
    """Launch the web UI (Gradio)."""
    from retrace.web import launch
    launch()


@main.command()
def report() -> None:
    """Show learning engine status and knowledge report."""
    from retrace.learning.engine import generate_report
    click.echo(generate_report())


@main.command("identify")
@click.argument("marking")
def identify(marking: str) -> None:
    """Look up a component by marking or part number."""
    from retrace.identification.matcher import lookup_part

    result = lookup_part(marking)
    if result is None:
        click.echo(f"No match found for '{marking}'", err=True)
        raise SystemExit(1)

    click.echo(f"{result['part']} ({result.get('manufacturer', 'Unknown')}) — {result.get('description', '')}")
    if result.get("package"):
        click.echo(f"Package: {result['package']}")
    if result.get("category"):
        click.echo(f"Category: {result['category']}")
    if result.get("datasheet"):
        click.echo(f"Datasheet: {result['datasheet']}")


@main.command("debug")
@click.argument("image", type=click.Path(exists=True))
def debug(image: str) -> None:
    """Detect exposed debug interfaces (JTAG, SWD, UART, SPI) in a PCB photo."""
    from retrace.core.pipeline import Pipeline
    from retrace.plugins.builtin.debug_interfaces import DebugInterfaceAnalyzer

    pipeline = Pipeline()
    result = pipeline.run(image)

    analyzer = DebugInterfaceAnalyzer()
    output = analyzer.analyze(result)

    click.echo(output["summary"])
    findings = output.get("findings", [])
    if not findings:
        click.echo("  No debug interfaces detected.")
        return

    click.echo()
    severity_order = {"high": 0, "medium": 1, "low": 2}
    for f in sorted(findings, key=lambda x: severity_order.get(x["severity"], 9)):
        sev = f["severity"].upper()
        click.echo(f"  [{sev}] {f['interface']} — {f['description']}")
        click.echo(f"         Component: {f['component_label']} (marking: {f['component_marking']})")
        if f.get("cve_reference"):
            click.echo(f"         Reference: {f['cve_reference']}")


@main.command("learn")
@click.argument("part_number")
@click.option("--aliases", default="", help="Comma-separated list of aliases")
@click.option("--category", default="", help="Component category (e.g. IC, mcu, sensor)")
@click.option("--manufacturer", default="", help="Manufacturer name")
@click.option("--package", default="", help="Package type (e.g. LQFP-48, SOT-23)")
@click.option("--datasheet", default="", help="Datasheet URL")
@click.option("--description", default="", help="Short description of the component")
def learn(
    part_number: str,
    aliases: str,
    category: str,
    manufacturer: str,
    package: str,
    datasheet: str,
    description: str,
) -> None:
    """Add a component to the persistent learned component database."""
    from retrace.identification.matcher import learn_component

    entry: dict = {"part": part_number}
    if aliases:
        entry["aliases"] = [a.strip() for a in aliases.split(",") if a.strip()]
    if category:
        entry["category"] = category
    if manufacturer:
        entry["manufacturer"] = manufacturer
    if package:
        entry["package"] = package
    if datasheet:
        entry["datasheet"] = datasheet
    if description:
        entry["description"] = description

    try:
        learn_component(entry)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)

    click.echo(f"Learned: {part_number}")
    if entry.get("aliases"):
        click.echo(f"  Aliases: {', '.join(entry['aliases'])}")
    if manufacturer:
        click.echo(f"  Manufacturer: {manufacturer}")
    if package:
        click.echo(f"  Package: {package}")


@main.command("cross-board")
@click.argument("image", type=click.Path(exists=True))
@click.option("--threshold", default=0.5, show_default=True, help="Minimum match score (0–1)")
def cross_board(image: str, threshold: float) -> None:
    """Run cross-board subcircuit pattern analysis on a PCB photo."""
    from retrace.core.pipeline import Pipeline
    from retrace.analysis.cross_board import (
        BoardComponent,
        BoardTrace,
        CrossBoardEngine,
    )

    pipeline = Pipeline()
    result = pipeline.run(image)

    # Convert pipeline components/traces into cross-board data structures
    cb_components = [
        BoardComponent(
            ref=c.id,
            kind=c.label,
            pins=[],
            location=(float(c.bbox[0]), float(c.bbox[1])),
            attributes={"marking": c.marking, "part_number": c.part_number},
        )
        for c in result.components
    ]
    cb_traces = [
        BoardTrace(
            ref_a=t.from_component,
            pin_a="",
            ref_b=t.to_component,
            pin_b="",
            confidence=1.0,
        )
        for t in result.traces
        if t.from_component and t.to_component
    ]

    engine = CrossBoardEngine(match_threshold=threshold)
    analysis = engine.analyse(cb_components, cb_traces)

    click.echo(
        f"Analysed {len(result.components)} components — "
        f"{len(analysis.matches)} pattern match(es), "
        f"coverage {analysis.coverage:.0%}"
    )

    if not analysis.matches:
        click.echo("  No known subcircuit patterns matched.")
    else:
        click.echo()
        for m in analysis.matches:
            partial_tag = " [partial]" if m.is_partial else ""
            click.echo(f"  [{m.score:.2f}] {m.pattern_name}{partial_tag} — {m.description}")
            roles_str = ", ".join(f"{role}={ref}" for role, ref in m.component_roles.items())
            click.echo(f"         {roles_str}")

    if analysis.novel_components:
        click.echo(f"\n  Novel (unmatched) components: {', '.join(analysis.novel_components)}")


@main.command("export")
@click.argument("image", type=click.Path(exists=True))
@click.option("--format", "fmt", type=click.Choice(["json", "csv", "svg"]), default="json", show_default=True)
@click.option("--output", "-o", type=click.Path(), help="Output directory (default: <image stem>_export)")
def export(image: str, fmt: str, output: str) -> None:
    """Scan a PCB photo and export results in the chosen format."""
    from retrace.core.pipeline import Pipeline

    pipeline = Pipeline()
    result = pipeline.run(image)

    if output:
        out_dir = Path(output)
    else:
        stem = Path(image).stem
        out_dir = Path(f"{stem}_export")

    out_dir.mkdir(parents=True, exist_ok=True)
    result.save(out_dir, fmt=fmt)

    summary = result.summary()
    click.echo(
        f"Exported {summary['components']} component(s), "
        f"{summary['traces']} trace(s) to {out_dir}/ [{fmt}]"
    )


if __name__ == "__main__":
    main()
