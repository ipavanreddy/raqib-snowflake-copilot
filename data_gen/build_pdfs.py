"""
Render policy_docs/*.md into PDFs (data/generated/docs/) so the Snowflake pipeline can
exercise real unstructured-document processing (AI_PARSE_DOCUMENT -> chunk -> Cortex Search).

Supports the subset of Markdown used in policy_docs: front matter, headings, paragraphs,
bullets, numbered items, blockquotes, **bold** and pipe tables.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]

styles = getSampleStyleSheet()
H = {1: ParagraphStyle("h1", parent=styles["Heading1"], fontSize=17, spaceAfter=8, textColor=colors.HexColor("#0B3D5C")),
     2: ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceBefore=8, textColor=colors.HexColor("#0B3D5C")),
     3: ParagraphStyle("h3", parent=styles["Heading3"], fontSize=11, spaceBefore=6)}
BODY = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=13)
NOTE = ParagraphStyle("note", parent=BODY, textColor=colors.HexColor("#7A4B00"), backColor=colors.HexColor("#FFF6E0"),
                      borderPadding=4, spaceAfter=6)
META = ParagraphStyle("meta", parent=BODY, fontSize=8, textColor=colors.grey)


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    return text


def render(md_path: Path, out_dir: Path) -> Path:
    raw = md_path.read_text()
    meta = {}
    if raw.startswith("---"):
        _, fm, raw = raw.split("---", 2)
        meta = dict(line.split(":", 1) for line in fm.strip().splitlines() if ":" in line)
        meta = {k.strip(): v.strip() for k, v in meta.items()}
    flow = []
    if meta:
        flow.append(Paragraph(" | ".join(f"{k}: {v}" for k, v in meta.items()), META))
        flow.append(Spacer(1, 4))
    lines = raw.strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append([Paragraph(inline(c), BODY) for c in cells])
                i += 1
            t = Table(rows, hAlign="LEFT", colWidths=[(A4[0] - 40 * mm) / len(rows[0])] * len(rows[0]))
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0F5")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            flow += [t, Spacer(1, 6)]
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            flow.append(Paragraph(inline(m.group(2)), H[len(m.group(1))]))
        elif line.startswith(">"):
            flow.append(Paragraph(inline(line.lstrip("> ")), NOTE))
        elif re.match(r"^\s*[-*]\s+", line):
            flow.append(Paragraph("&bull; " + inline(re.sub(r"^\s*[-*]\s+", "", line)), BODY))
        else:
            flow.append(Paragraph(inline(line), BODY))
        i += 1
    out = out_dir / (md_path.stem + ".pdf")
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title=meta.get("title", md_path.stem), author="Gulf Horizon Bank (fictional)")
    doc.build(flow)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "policy_docs"))
    ap.add_argument("--out", default=str(ROOT / "data" / "generated" / "docs"))
    a = ap.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for md in sorted(Path(a.src).glob("*.md")):
        print("rendered", render(md, out_dir).relative_to(ROOT))


if __name__ == "__main__":
    main()
