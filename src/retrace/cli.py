"""re:trace CLI — the FCC won't let me be, so let me see what's on this PCB."""

import json
import logging
from pathlib import Path

import click

from retrace import __version__


@click.group()
@click.version_option(__version__, prog_name="retrace")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("-q", "--quiet", is_flag=True, help="Suppress non-data output")
@click.pass_context
def main(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """re:trace -- AI-powered PCB reverse engineering toolkit."""
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


@main.command()
@click.argument("image", type=click.Path(exists=True))
@click.option("--bom", is_flag=True, help="Generate bill of materials")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option("--format", "fmt", type=click.Choice(["json", "csv", "svg"]), default="json")
@click.pass_context
def scan(ctx: click.Context, image: str, bom: bool, output: str, fmt: str) -> None:
    """Scan a PCB photo — detect components, extract traces, identify chips."""
    from retrace.core.pipeline import Pipeline

    pipeline = Pipeline()
    result = pipeline.run(image)

    if output:
        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
        result.save(out_dir, fmt=fmt)
        if not ctx.obj.get("quiet"):
            click.echo(f"Results saved to {out_dir}")
    else:
        click.echo(json.dumps(result.summary(), indent=2))

    if bom:
        from retrace.export.bom import generate_bom
        bom_data = generate_bom(result)
        if not ctx.obj.get("quiet"):
            click.echo(f"\nBOM: {len(bom_data['components'])} components identified")


@main.command()
@click.argument("query")
@click.option("--download", is_flag=True, help="Download found images")
@click.option("--limit", type=int, default=5, help="Max results")
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON")
@click.pass_context
def search(ctx: click.Context, query: str, download: bool, limit: int, as_json: bool) -> None:
    """Search FCC filings and iFixit for board images."""
    from retrace.sources.fcc import search_fcc
    from retrace.sources.ifixit import search_ifixit

    fcc_results = search_fcc(query)
    ifixit_results = search_ifixit(query)

    if as_json:
        click.echo(json.dumps({
            "query": query,
            "fcc": fcc_results[:limit],
            "ifixit": ifixit_results[:limit],
        }, indent=2))
        return

    click.echo(f"\nSearching for: {query}\n")
    for r in fcc_results[:limit]:
        click.echo(f"  FCC: {r['fcc_id']} — {r.get('description', '')}")
    for r in ifixit_results[:limit]:
        click.echo(f"  iFixit #{r['guideid']}: {r['title']}")
    click.echo(f"\n  Found {len(fcc_results) + len(ifixit_results)} results")

    if download and (fcc_results or ifixit_results):
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
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--output", "-o", type=click.Path(), help="Save findings to a .txt file")
def advise(image: str, as_json: bool, output: str) -> None:
    """Bayesian probe point advisor — where to measure next."""
    from retrace.analysis.probe_advisor import ProbeAdvisor

    advisor = ProbeAdvisor()
    recommendations = advisor.recommend(image)

    if as_json:
        text = json.dumps(recommendations[:10], indent=2)
        click.echo(text)
        if output:
            Path(output).write_text(text)
        return

    lines = ["\nRecommended probe points (by information gain):\n"]
    for i, rec in enumerate(recommendations[:5], 1):
        lines.append(f"  {i}. {rec['location']} — {rec['reason']}")
        lines.append(f"     Expected info gain: {rec['entropy_reduction']:.2f} bits")
    out_text = "\n".join(lines)
    click.echo(out_text)

    if output:
        Path(output).write_text(out_text)


@main.command()
def ui() -> None:
    """Launch the web UI (Gradio)."""
    from retrace.web import launch
    launch()


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def report(as_json: bool) -> None:
    """Show learning engine status and knowledge report."""
    from retrace.learning.engine import generate_report
    text = generate_report()
    if as_json:
        click.echo(json.dumps({"report": text}))
    else:
        click.echo(text)


@main.command("identify")
@click.argument("marking")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def identify(marking: str, as_json: bool) -> None:
    """Look up a component by marking or part number."""
    from retrace.identification.matcher import lookup_part

    result = lookup_part(marking)
    if result is None:
        if as_json:
            click.echo(json.dumps({"match": None, "query": marking}))
        else:
            click.echo(f"No match found for '{marking}'", err=True)
        raise SystemExit(1)

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    click.echo(f"{result['part']} ({result.get('manufacturer', 'Unknown')}) — {result.get('description', '')}")
    if result.get("package"):
        click.echo(f"Package: {result['package']}")
    if result.get("category"):
        click.echo(f"Category: {result['category']}")
    if result.get("datasheet"):
        click.echo(f"Datasheet: {result['datasheet']}")


@main.command("debug")
@click.argument("image", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--output", "-o", type=click.Path(), help="Save findings to a .txt file")
def debug(image: str, as_json: bool, output: str) -> None:
    """Detect exposed debug interfaces (JTAG, SWD, UART, SPI) in a PCB photo."""
    from retrace.core.pipeline import Pipeline
    from retrace.plugins.builtin.debug_interfaces import DebugInterfaceAnalyzer

    pipeline = Pipeline()
    result = pipeline.run(image)

    analyzer = DebugInterfaceAnalyzer()
    analyzer_output = analyzer.analyze(result)

    if as_json:
        text = json.dumps(analyzer_output, indent=2)
        click.echo(text)
        if output:
            Path(output).write_text(text)
        return

    lines = [analyzer_output["summary"]]
    findings = analyzer_output.get("findings", [])
    if not findings:
        lines.append("  No debug interfaces detected.")
        click.echo("\n".join(lines))
        if output:
            Path(output).write_text("\n".join(lines))
        return

    lines.append("")
    severity_order = {"high": 0, "medium": 1, "low": 2}
    for f in sorted(findings, key=lambda x: severity_order.get(x["severity"], 9)):
        sev = f["severity"].upper()
        cvss = f.get("cvss_base")
        cvss_str = f"  CVSS {cvss}" if cvss else ""
        lines.append(f"  [{sev}]{cvss_str} {f['interface']} — {f['description']}")
        lines.append(f"         Component: {f['component_label']} (marking: {f['component_marking']})")
        if f.get("cve_reference"):
            lines.append(f"         CWE: {f['cve_reference']}")
        if f.get("mitre_attack"):
            lines.append(f"         ATT&CK: {', '.join(f['mitre_attack'])}")
    out_text = "\n".join(lines)
    click.echo(out_text)

    if output:
        Path(output).write_text(out_text)


@main.command("solve")
@click.argument("image", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Save results to a .txt file")
def solve(image: str, output: str) -> None:
    """Run the constraint solver on a PCB photo — infer net assignments and connections."""
    from retrace.analysis.constraint_solver import ComponentSpec, ConstraintSolver, Trace, Pin
    from retrace.core.pipeline import Pipeline

    pipeline = Pipeline()
    result = pipeline.run(image)

    # Map pipeline components to solver ComponentSpec
    components = [
        ComponentSpec(
            ref=c.id,
            kind=c.label,
            pins=[c.marking or "PIN"] if not hasattr(c, "pins") or not getattr(c, "pins", None) else list(c.pins),
            location=(float(c.bbox[0]), float(c.bbox[1])),
        )
        for c in result.components
    ]

    # Map pipeline traces to solver Trace objects
    traces = []
    for t in result.traces:
        if t.from_component and t.to_component:
            # Use generic pin names since pipeline traces connect components, not specific pins
            traces.append(Trace(
                pin_a=Pin(t.from_component, "OUT"),
                pin_b=Pin(t.to_component, "IN"),
                confidence=getattr(t, "confidence", 1.0),
            ))

    solver = ConstraintSolver()
    solver_result = solver.solve(components, traces)

    lines = [
        f"Constraint solver — {solver_result.iterations} iteration(s)",
        f"  {len(solver_result.net_assignment)} nodes, "
        f"{len(solver_result.inferred_traces)} inferred connection(s), "
        f"{len(solver_result.ambiguous_nodes)} ambiguous, "
        f"{len(solver_result.conflicts)} conflict(s)",
        "",
        "Net assignments:",
    ]
    for nid, net in sorted(solver_result.net_assignment.items()):
        lines.append(f"  {nid:30s} -> {net}")

    if solver_result.inferred_traces:
        lines.append(f"\nInferred connections ({len(solver_result.inferred_traces)}):")
        for a, b in solver_result.inferred_traces:
            lines.append(f"  {a} <-> {b}")

    if solver_result.ambiguous_nodes:
        lines.append(f"\nAmbiguous nodes ({len(solver_result.ambiguous_nodes)}):")
        for nid in solver_result.ambiguous_nodes:
            lines.append(f"  {nid}")

    if solver_result.conflicts:
        lines.append("\nConflicts:")
        for c in solver_result.conflicts:
            lines.append(f"  {c}")

    out_text = "\n".join(lines)
    click.echo(out_text)

    if output:
        Path(output).write_text(out_text)
        click.echo(f"\nResults saved to {output}")


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
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cross_board(image: str, threshold: float, as_json: bool) -> None:
    """Run cross-board subcircuit pattern analysis on a PCB photo."""
    from retrace.core.pipeline import Pipeline
    from retrace.analysis.cross_board import (
        BoardComponent,
        BoardTrace,
        CrossBoardEngine,
    )

    pipeline = Pipeline()
    result = pipeline.run(image)

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

    if as_json:
        click.echo(json.dumps({
            "components": len(result.components),
            "matches": [
                {
                    "pattern": m.pattern_name,
                    "score": m.score,
                    "partial": m.is_partial,
                    "description": m.description,
                    "roles": m.component_roles,
                }
                for m in analysis.matches
            ],
            "coverage": analysis.coverage,
            "novel_components": analysis.novel_components,
        }, indent=2))
        return

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


@main.command("compare")
@click.argument("image_a", type=click.Path(exists=True))
@click.argument("image_b", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output diff as JSON")
def compare(image_a: str, image_b: str, as_json: bool) -> None:
    """Compare two PCB photos — diff components, traces, and debug interfaces."""
    from retrace.core.pipeline import Pipeline

    pipeline = Pipeline()
    result_a = pipeline.run(image_a)
    result_b = pipeline.run(image_b)

    comps_a = {c.id: c for c in result_a.components}
    comps_b = {c.id: c for c in result_b.components}

    added = sorted(set(comps_b) - set(comps_a))
    removed = sorted(set(comps_a) - set(comps_b))
    common = sorted(set(comps_a) & set(comps_b))
    changed = []
    for cid in common:
        a, b = comps_a[cid], comps_b[cid]
        diffs = {}
        if a.label != b.label:
            diffs["label"] = {"a": a.label, "b": b.label}
        if a.part_number != b.part_number:
            diffs["part_number"] = {"a": a.part_number, "b": b.part_number}
        if a.marking != b.marking:
            diffs["marking"] = {"a": a.marking, "b": b.marking}
        if diffs:
            changed.append({"id": cid, "changes": diffs})

    diff = {
        "board_a": image_a,
        "board_b": image_b,
        "components_a": len(comps_a),
        "components_b": len(comps_b),
        "traces_a": len(result_a.traces),
        "traces_b": len(result_b.traces),
        "added": added,
        "removed": removed,
        "changed": changed,
    }

    if as_json:
        click.echo(json.dumps(diff, indent=2))
        return

    click.echo(f"\nBoard A: {image_a} — {len(comps_a)} components, {len(result_a.traces)} traces")
    click.echo(f"Board B: {image_b} — {len(comps_b)} components, {len(result_b.traces)} traces")
    click.echo()

    if added:
        click.echo(f"  Added ({len(added)}):")
        for cid in added:
            c = comps_b[cid]
            click.echo(f"    + {cid} ({c.label}) {c.marking or c.part_number or ''}")

    if removed:
        click.echo(f"  Removed ({len(removed)}):")
        for cid in removed:
            c = comps_a[cid]
            click.echo(f"    - {cid} ({c.label}) {c.marking or c.part_number or ''}")

    if changed:
        click.echo(f"  Changed ({len(changed)}):")
        for ch in changed:
            click.echo(f"    ~ {ch['id']}:")
            for field, vals in ch["changes"].items():
                click.echo(f"        {field}: {vals['a']!r} → {vals['b']!r}")

    if not added and not removed and not changed:
        click.echo("  No differences found.")


@main.command("report-html")
@click.argument("image", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output file (default: <image stem>_report.html)")
@click.option("--title", default="", help="Report title / board name")
def report_html(image: str, output: str, title: str) -> None:
    """Generate a self-contained HTML assessment report with datasheet links."""
    from retrace.core.pipeline import Pipeline
    from retrace.export.html_report import save_html_report

    pipeline = Pipeline()
    result = pipeline.run(image)

    if not output:
        output = Path(image).stem + "_report.html"

    save_html_report(result, output, title=title or Path(image).stem)
    click.echo(f"Report saved to {output}")


@main.command("export-kicad")
@click.argument("image", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output file (default: <image stem>.net)")
@click.option("--title", default="", help="Board name for netlist metadata")
def export_kicad(image: str, output: str, title: str) -> None:
    """Export reverse-engineered netlist as KiCad .net file."""
    from retrace.core.pipeline import Pipeline
    from retrace.export.kicad import save_kicad_netlist

    pipeline = Pipeline()
    result = pipeline.run(image)

    if not output:
        output = Path(image).stem + ".net"

    save_kicad_netlist(result, output, title=title or Path(image).stem)

    net_count = sum(1 for t in result.traces if t.from_component and t.to_component)
    click.echo(
        f"KiCad netlist saved to {output} — "
        f"{len(result.components)} components, {net_count} nets"
    )


@main.command("batch")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--output", "-o", type=click.Path(), help="Output directory (default: <directory>_results)")
@click.option("--format", "fmt", type=click.Choice(["json", "csv", "svg"]), default="json", show_default=True)
@click.option("--report", is_flag=True, help="Generate HTML assessment report per board")
@click.option("--kicad", is_flag=True, help="Generate KiCad netlist per board")
@click.option("--pinout", is_flag=True, help="Generate pinout diagrams for detected debug interfaces")
@click.pass_context
def batch(ctx: click.Context, directory: str, output: str, fmt: str, report: bool, kicad: bool, pinout: bool) -> None:
    """Scan all images in a directory — bulk analysis for multi-board assessments."""
    from retrace.core.pipeline import Pipeline

    src = Path(directory)
    out = Path(output) if output else Path(f"{src.name}_results")
    out.mkdir(parents=True, exist_ok=True)

    exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
    images = sorted(p for p in src.iterdir() if p.suffix.lower() in exts)

    if not images:
        click.echo(f"No images found in {directory}")
        raise SystemExit(1)

    quiet = ctx.obj.get("quiet", False)
    pipeline = Pipeline()
    total_components = 0
    total_traces = 0

    for i, img_path in enumerate(images, 1):
        stem = img_path.stem
        if not quiet:
            click.echo(f"[{i}/{len(images)}] {img_path.name}")

        result = pipeline.run(str(img_path))
        total_components += len(result.components)
        total_traces += len(result.traces)

        board_out = out / stem
        board_out.mkdir(parents=True, exist_ok=True)
        result.save(board_out, fmt=fmt)

        if report:
            from retrace.export.html_report import save_html_report
            save_html_report(result, str(board_out / f"{stem}_report.html"), title=stem)

        if kicad:
            from retrace.export.kicad import save_kicad_netlist
            save_kicad_netlist(result, str(board_out / f"{stem}.net"), title=stem)

        if pinout:
            from retrace.export.pinout_diagram import save_pinout_svg
            from retrace.plugins.builtin.debug_interfaces import detect_debug_interfaces
            debug_findings = detect_debug_interfaces(result)
            for df in debug_findings:
                iface = df["interface"]
                save_pinout_svg(result, df, str(board_out / f"{iface.lower()}_pinout.svg"))

        if not quiet:
            click.echo(f"    {len(result.components)} components, {len(result.traces)} traces → {board_out}/")

    click.echo(
        f"\nBatch complete: {len(images)} board{'s' if len(images) != 1 else ''}, "
        f"{total_components} total components, {total_traces} total traces → {out}/"
    )


@main.command("pinout")
@click.argument("image", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output directory (default: <image stem>_pinouts/)")
@click.option("--interface", type=click.Choice(["JTAG", "SWD", "UART", "SPI", "I2C"]),
              help="Generate for specific interface only")
@click.option("--json", "as_json", is_flag=True, help="Output finding data as JSON")
@click.pass_context
def pinout(ctx: click.Context, image: str, output: str, interface: str, as_json: bool) -> None:
    """Generate annotated pinout diagrams for detected debug interfaces."""
    from retrace.core.pipeline import Pipeline
    from retrace.export.pinout_diagram import generate_all_pinout_svgs, save_pinout_svg
    from retrace.plugins.builtin.debug_interfaces import detect_debug_interfaces

    pipeline = Pipeline()
    result = pipeline.run(image)
    findings = detect_debug_interfaces(result)

    if interface:
        findings = [f for f in findings if f["interface"] == interface]

    if not findings:
        click.echo("No debug interfaces detected.")
        raise SystemExit(0)

    if as_json:
        click.echo(json.dumps(findings, indent=2))
        return

    out_dir = Path(output) if output else Path(f"{Path(image).stem}_pinouts")
    out_dir.mkdir(parents=True, exist_ok=True)

    quiet = ctx.obj.get("quiet", False)
    for finding in findings:
        iface = finding["interface"]
        out_path = out_dir / f"{iface.lower()}_pinout.svg"
        save_pinout_svg(result, finding, str(out_path))
        if not quiet:
            click.echo(f"  {iface} pinout → {out_path}")

    click.echo(f"\n{len(findings)} pinout diagram{'s' if len(findings) != 1 else ''} → {out_dir}/")


if __name__ == "__main__":
    main()
