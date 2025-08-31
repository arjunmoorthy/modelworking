import json
import os
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.units import inch


REPO_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = REPO_ROOT / "model_inputs" / "rag" / "questions.json"
KB_PATH = REPO_ROOT / "model_inputs" / "rag" / "triage_kb_v2.json"
EXPORTS_DIR = REPO_ROOT / "exports"
OUTPUT_PDF = EXPORTS_DIR / "attribute_catalog.pdf"


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_question_stem_lookup(questions: List[Dict[str, Any]]) -> Dict[Tuple[str, str], str]:
    """Map (symptom, attribute_id) -> shortest stem from questions.json."""
    lookup: Dict[Tuple[str, str], str] = {}
    for q in questions:
        symptom = q.get("symptom")
        attr_id = q.get("attribute_id")
        text = q.get("text", "")
        if not symptom or not attr_id or not text:
            continue
        key = (symptom, attr_id)
        prev = lookup.get(key)
        if prev is None or len(text) < len(prev):
            lookup[key] = text
    return lookup


def ui_from_kb_template(kb: Dict[str, Any], attr_entry: Dict[str, Any]) -> Tuple[str, Optional[List[str]]]:
    """Derive friendly UI type and options (if any) from a KB attribute entry."""
    templates = kb.get("templates", {})
    option_sets = kb.get("option_sets", {})

    fallback = attr_entry.get("fallback_template", {})
    template_key = fallback.get("use")
    template = templates.get(template_key, {}) if template_key else {}
    response_type = template.get("response")

    # Map template response types to UI types used by the app
    response_to_ui = {
        "boolean": "single-select",
        "categorical": "single-select",
        "categorical_multi": "multi-select",
        "number": "number",
    }
    ui_type = response_to_ui.get(response_type, "unknown")

    vars_obj = fallback.get("vars", {})
    options_ref = vars_obj.get("options_ref")
    options = option_sets.get(options_ref) if options_ref else None

    return ui_type, options


def compile_rows_by_symptom() -> Dict[str, List[Dict[str, Any]]]:
    kb = load_json(KB_PATH)
    questions = load_json(QUESTIONS_PATH)

    stem_lookup = build_question_stem_lookup(questions)

    rows_by_symptom: Dict[str, List[Dict[str, Any]]] = {}

    # Track what we've covered to allow union with questions.json-only attributes
    covered_keys: set[Tuple[str, str]] = set()

    # First, enumerate all KB-defined symptoms/attributes
    for symptom_entry in kb.get("symptoms", []):
        symptom_id = symptom_entry.get("id")
        if not symptom_id:
            continue
        for a in symptom_entry.get("attributes", []):
            attr_id = a.get("attr")
            if not attr_id:
                continue
            key = (symptom_id, attr_id)
            covered_keys.add(key)

            stem = stem_lookup.get(key) or "(no canonical stem)"
            ui_type, options = ui_from_kb_template(kb, a)

            util = a.get("utility", {})
            info_gain = util.get("base_info_gain")
            burden = util.get("burden_cost")
            base_utility = None
            if isinstance(info_gain, (int, float)) and isinstance(burden, (int, float)):
                base_utility = round(float(info_gain) - float(burden), 3)

            rows_by_symptom.setdefault(symptom_id, []).append({
                "attribute_id": attr_id,
                "stem": stem,
                "ui": ui_type,
                "options": options,
                "info_gain": info_gain,
                "burden": burden,
                "base_utility": base_utility,
            })

    # Second, add any attributes that appear only in questions.json
    for (symptom, attr_id), stem in stem_lookup.items():
        key = (symptom, attr_id)
        if key in covered_keys:
            continue
        rows_by_symptom.setdefault(symptom, []).append({
            "attribute_id": attr_id,
            "stem": stem,
            "ui": "unknown",
            "options": None,
            "info_gain": None,
            "burden": None,
            "base_utility": None,
        })

    # Sort rows within each symptom by base_utility desc (None last), then attribute_id
    for symptom, rows in rows_by_symptom.items():
        def sort_key(r: Dict[str, Any]):
            bu = r.get("base_utility")
            # None utilities go last
            return (-(bu if isinstance(bu, (int, float)) else -1e9), r.get("attribute_id") or "")
        rows.sort(key=sort_key)

    return rows_by_symptom


def render_pdf(rows_by_symptom: Dict[str, List[Dict[str, Any]]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(LETTER),
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="OncoLife Attribute Catalog",
    )
    styles = getSampleStyleSheet()

    story: List[Any] = []

    title = Paragraph("OncoLife Attribute Catalog (Per Symptom)", styles["Title"])
    story.append(title)
    story.append(Spacer(1, 0.2 * inch))

    # Column headers
    header = [
        "Attribute ID",
        "Stem",
        "UI",
        "Options",
        "InfoGain",
        "Burden",
        "BaseUtility",
    ]

    first = True
    for symptom in sorted(rows_by_symptom.keys()):
        if not first:
            story.append(PageBreak())
        first = False

        story.append(Paragraph(f"Symptom: {symptom}", styles["Heading2"]))
        story.append(Spacer(1, 0.1 * inch))

        data: List[List[Any]] = [header]

        for r in rows_by_symptom[symptom]:
            options_text = ", ".join(r["options"]) if r.get("options") else ""
            row = [
                Paragraph(str(r.get("attribute_id", "")), styles["BodyText"]),
                Paragraph(str(r.get("stem", "")), styles["BodyText"]),
                Paragraph(str(r.get("ui", "")), styles["BodyText"]),
                Paragraph(options_text, styles["BodyText"]),
                Paragraph("" if r.get("info_gain") is None else f"{r['info_gain']:.2f}", styles["BodyText"]),
                Paragraph("" if r.get("burden") is None else f"{r['burden']:.2f}", styles["BodyText"]),
                Paragraph("" if r.get("base_utility") is None else f"{r['base_utility']:.2f}", styles["BodyText"]),
            ]
            data.append(row)

        # Compute column widths relative to available width to avoid cutoff
        available_width = doc.width  # total width excluding margins
        fractions = [0.16, 0.40, 0.08, 0.20, 0.06, 0.05, 0.05]
        col_widths = [f * available_width for f in fractions]

        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.hAlign = "LEFT"
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ]))

        story.append(table)

    doc.build(story)


def main() -> int:
    rows = compile_rows_by_symptom()
    render_pdf(rows, OUTPUT_PDF)
    print(f"Wrote PDF with full attribute catalog to: {OUTPUT_PDF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


