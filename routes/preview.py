"""Subtitle / narration preview routes — render text over a sample background."""
import io
from flask import Blueprint, request, send_file, jsonify

bp = Blueprint("preview", __name__, url_prefix="")


@bp.route("/preview/samples", methods=["GET"])
def preview_samples():
    """Report which sample backgrounds exist (so the UI can disable missing ones)."""
    try:
        from preview_render import available_samples
        return jsonify(available_samples())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/preview/text", methods=["GET"])
def preview_text():
    """Render `text` over assets/samples/<format>.png and return a PNG.

    Query params: text, format (vertical|horizontal), style (dialog|narration),
    footnote, repeat_message. Errors come back as JSON so the UI can show them.
    """
    try:
        from preview_render import render_text_preview
        png = render_text_preview(
            request.args.get("text", ""),
            video_format  = request.args.get("format", "vertical"),
            style         = request.args.get("style", "dialog"),
            footnote      = request.args.get("footnote", ""),
            repeat_message= request.args.get("repeat_message", ""),
        )
        return send_file(io.BytesIO(png), mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
