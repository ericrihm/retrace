"""Gradio web UI stub for re:trace."""

from __future__ import annotations


def launch(share: bool = False, port: int = 7860) -> None:
    """Launch the Gradio web interface.

    Prints an informational message if Gradio is not installed. When Gradio is
    available a minimal scan-and-display interface is started.

    Args:
        share: If True, create a public Gradio share link.
        port: Local port to bind the server to (default 7860).
    """
    try:
        import gradio as gr  # type: ignore[import]
    except ImportError:
        print(
            "Gradio is not installed. Install it with:\n"
            "  pip install 'retrace-pcb[web]'\n"
            "  # or: pip install gradio"
        )
        return

    from retrace.core.pipeline import Pipeline

    def _scan(image):
        if image is None:
            return "No image provided.", None, ""
        pipeline = Pipeline()
        import os
        import tempfile

        from PIL import Image as PILImage

        # Save the numpy array Gradio gives us to a temp file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            PILImage.fromarray(image).save(tmp.name)
            tmp_path = tmp.name

        try:
            result = pipeline.run(tmp_path)
        finally:
            os.unlink(tmp_path)

        import json
        summary = json.dumps(result.summary(), indent=2)

        from retrace.export.svg import generate_svg
        svg = generate_svg(result)

        return summary, image, svg

    with gr.Blocks(title="re:trace PCB Analyzer") as demo:
        gr.Markdown("# re:trace — PCB Reverse Engineering Toolkit")
        with gr.Row():
            inp = gr.Image(label="PCB Photo", type="numpy")
            btn = gr.Button("Scan", variant="primary")
        with gr.Row():
            summary_out = gr.Textbox(label="Analysis Summary", lines=12)
            svg_out = gr.HTML(label="SVG Overlay")
        img_out = gr.Image(label="Annotated", visible=False)

        btn.click(_scan, inputs=[inp], outputs=[summary_out, img_out, svg_out])

    demo.launch(share=share, server_port=port)
