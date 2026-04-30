"""re:trace CLI — the FCC won't let me be, so let me see what's on this PCB."""

import json
import logging
from pathlib import Path

import click

from retrace import __version__


@click.group()
@click.version_option(__version__, prog_name="retrace")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def main(verbose: bool):
    """re:trace -- AI-powered PCB reverse engineering toolkit."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


@main.command()
@click.argument("image", type=click.Path(exists=True))
@click.option("--bom", is_flag=True, help="Generate bill of materials")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option("--format", "fmt", type=click.Choice(["json", "csv", "svg"]), default="json")
def scan(image: str, bom: bool, output: str, fmt: str):
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
def search(query: str, download: bool, limit: int):
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
def trace(image: str, output: str):
    """Extract copper traces from a PCB photo."""
    from retrace.detection.trace_extractor import extract_traces

    result = extract_traces(image)
    click.echo(f"Extracted {result['trace_count']} traces, {result['junction_count']} junctions")

    if output:
        result["save"](output)
        click.echo(f"Saved to {output}")


@main.command()
@click.argument("image", type=click.Path(exists=True))
def advise(image: str):
    """Bayesian probe point advisor — where to measure next."""
    from retrace.analysis.probe_advisor import ProbeAdvisor

    advisor = ProbeAdvisor()
    recommendations = advisor.recommend(image)

    click.echo("\nRecommended probe points (by information gain):\n")
    for i, rec in enumerate(recommendations[:5], 1):
        click.echo(f"  {i}. {rec['location']} — {rec['reason']}")
        click.echo(f"     Expected info gain: {rec['entropy_reduction']:.2f} bits")


@main.command()
def ui():
    """Launch the web UI (Gradio)."""
    from retrace.web import launch
    launch()


@main.command()
def report():
    """Show learning engine status and knowledge report."""
    from retrace.learning.engine import generate_report
    click.echo(generate_report())


if __name__ == "__main__":
    main()
