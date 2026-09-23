"""Render the sample FIRs as .docx and .pdf as well as plain text.

The demonstration should be able to drop in the format an officer would
actually hold, not only the one that is easiest to parse. Run from the repo
root:

    python samples/make_samples.py
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def to_docx(source: Path) -> Path:
    import docx
    from docx.shared import Pt

    doc = docx.Document()
    style = doc.styles["Normal"]
    style.font.name = "Consolas"
    style.font.size = Pt(9.5)
    for line in source.read_text(encoding="utf-8").splitlines():
        doc.add_paragraph(line)
    out = source.with_suffix(".docx")
    doc.save(out)
    return out


def to_pdf(source: Path) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    y, left = 46, 42
    for line in source.read_text(encoding="utf-8").splitlines():
        if y > 780:
            page = doc.new_page()
            y = 46
        # A PDF text layer holds no tabs, so the form's alignment is rebuilt
        # from spaces - which is also what a real exported FIR looks like.
        page.insert_text((left, y), re.sub(r"\t", "    ", line),
                         fontname="cour", fontsize=8.6)
        y += 11.4
    out = source.with_suffix(".pdf")
    doc.save(out)
    doc.close()
    return out


if __name__ == "__main__":
    for txt in sorted(HERE.glob("FIR-*.txt")):
        print("  ", to_docx(txt).name)
        print("  ", to_pdf(txt).name)
